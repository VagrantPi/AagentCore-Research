"""AgentCore Runtime 冷啟動與 session 建立速率實驗。

子命令：
  build-zip   打包 direct code 用的 zip 並上傳到 S3
  deploy      依矩陣建立各變體的 runtime，等待 READY，並把狀態寫入 state.json
  measure     每個變體跑 N 次「新 session 冷啟動 → 同 session 熱呼叫」，結果寫入 results.csv
  burst       對單一變體並發建立 M 個新 session，觀察被 throttle 的比例與實際速率
  cleanup     刪除 state.json 裡記錄的 runtime

用法見同目錄的 README.md。
"""

import argparse
import csv
import json
import statistics
import sys
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

HERE = Path(__file__).parent
STATE = HERE / "state.json"
RESULTS = HERE / "results.csv"
ZIP_KEY = "agentcore-coldstart/agent.zip"

# 壓低 lifecycle，避免閒置 session 持續計費
LIFECYCLE = {"idleRuntimeSessionTimeout": 60, "maxLifetime": 600}


def clients(region, retries=True):
    cfg = Config(region_name=region, read_timeout=900,
                 retries={"mode": "standard", "total_max_attempts": 5 if retries else 1})
    return (boto3.client("bedrock-agentcore-control", config=cfg),
            boto3.client("bedrock-agentcore", config=cfg))


def new_session_id():
    return f"{uuid.uuid4()}-{uuid.uuid4().hex[:8]}"  # 45 字元，符合至少 33 字元的要求


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {"runtimes": []}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=2))


def variants(args):
    """產生實驗矩陣：平台版本 × 打包方式 × 網路模式，外加可選的大 image。"""
    out = []
    networks = [("pub", {"networkMode": "PUBLIC"})]
    if args.subnets:
        networks.append(("vpc", {"networkMode": "VPC", "networkModeConfig": {
            "subnets": args.subnets.split(","), "securityGroups": args.security_groups.split(",")}}))
    artifacts = [("img", {"containerConfiguration": {"containerUri": args.image}})]
    if args.bucket:
        artifacts.append(("zip", {"codeConfiguration": {
            "code": {"s3": {"bucket": args.bucket, "prefix": ZIP_KEY}},
            "runtime": "PYTHON_3_12", "entryPoint": ["main.py"]}}))
    if args.big_image:
        artifacts.append(("bigimg", {"containerConfiguration": {"containerUri": args.big_image}}))
    for pv in ("V1", "V2"):
        for an, art in artifacts:
            for nn, net in networks:
                if an == "bigimg" and nn == "vpc":
                    continue
                out.append({"name": f"cs_{pv.lower()}_{an}_{nn}", "platform": pv,
                            "artifact": art, "network": net})
    return out


def wait_ready(ctl, runtime_id, timeout=1200):
    start = time.time()
    while time.time() - start < timeout:
        status = ctl.get_agent_runtime(agentRuntimeId=runtime_id)["status"]
        if status == "READY" or status.endswith("FAILED"):
            return status, round(time.time() - start, 1)
        time.sleep(10)
    return "TIMEOUT", round(time.time() - start, 1)


def cmd_build_zip(args):
    zpath = HERE / "agent.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("main.py")
        info.external_attr = 0o644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, (HERE / "agent" / "main.py").read_text())
    boto3.client("s3", region_name=args.region).upload_file(str(zpath), args.bucket, ZIP_KEY)
    print(f"uploaded s3://{args.bucket}/{ZIP_KEY}")


def cmd_deploy(args):
    ctl, _ = clients(args.region)
    state = load_state()
    existing = {r["name"] for r in state["runtimes"]}
    for v in variants(args):
        if v["name"] in existing:
            print(f"skip {v['name']} (already in state.json)")
            continue
        resp = ctl.create_agent_runtime(
            agentRuntimeName=v["name"], roleArn=args.role_arn,
            agentRuntimeArtifact=v["artifact"], networkConfiguration=v["network"],
            lifecycleConfiguration=LIFECYCLE, platformVersion=v["platform"])
        v.update(id=resp["agentRuntimeId"], arn=resp["agentRuntimeArn"])
        state["runtimes"].append(v)
        save_state(state)
        print(f"created {v['name']} -> {v['id']}")
    for v in state["runtimes"]:
        status, waited = wait_ready(ctl, v["id"])
        v["ready_status"], v["ready_wait_s"] = status, waited
        print(f"{v['name']}: {status} (waited {waited}s)")
    save_state(state)


def ensure_mmdsv2(ctl, v):
    """MMDSv2 自 2026-06-30 起強制啟用，但 CreateAgentRuntime 沒有這個參數，只能事後 update。"""
    ctl.update_agent_runtime(
        agentRuntimeId=v["id"], roleArn=v.get("role_arn") or ARGS.role_arn,
        agentRuntimeArtifact=v["artifact"], networkConfiguration=v["network"],
        lifecycleConfiguration=LIFECYCLE, platformVersion=v["platform"],
        metadataConfiguration={"requireMMDSV2": True})
    print(f"{v['name']}: enabled MMDSv2, waiting for READY ...")
    print(f"{v['name']}: {wait_ready(ctl, v['id'])}")


def invoke(data, arn, session_id):
    t0 = time.perf_counter()
    resp = data.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId=session_id,
                                     qualifier="DEFAULT", contentType="application/json",
                                     payload=b'{"prompt":"ping"}')
    body = json.loads(resp["response"].read())
    return round((time.perf_counter() - t0) * 1000, 1), body


def cmd_measure(args):
    ctl, data = clients(args.region)
    state = load_state()
    rows = []
    for v in state["runtimes"]:
        if args.only and v["name"] not in args.only.split(","):
            continue
        for i in range(args.trials):
            sid = new_session_id()
            try:
                cold_ms, cold = invoke(data, v["arn"], sid)
            except ClientError as e:
                if "MMDS" in str(e) and not v.get("mmdsv2"):
                    ensure_mmdsv2(ctl, v)
                    v["mmdsv2"] = True
                    save_state(state)
                    cold_ms, cold = invoke(data, v["arn"], sid)
                else:
                    raise
            warm_ms, warm = invoke(data, v["arn"], sid)
            rows.append({"variant": v["name"], "trial": i, "cold_ms": cold_ms, "warm_ms": warm_ms,
                         "cold_first_request": cold["first_request"],
                         "warm_same_boot": cold["boot_token"] == warm["boot_token"],
                         "boot_token": cold["boot_token"], "boot_random": cold["boot_random"],
                         "boot_age_s": cold["boot_age_s"], "hostname": cold["hostname"],
                         "pid": cold["pid"]})
            data.stop_runtime_session(agentRuntimeArn=v["arn"], runtimeSessionId=sid,
                                      qualifier="DEFAULT")
            print(f"{v['name']} #{i}: cold={cold_ms}ms warm={warm_ms}ms boot={cold['boot_token']}")
            time.sleep(args.gap)
    new_file = not RESULTS.exists()
    with RESULTS.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        if new_file:
            w.writeheader()
        w.writerows(rows)
    summarize(rows)


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def summarize(rows):
    print(f"\n{'variant':<22}{'n':>4}{'cold p50':>10}{'cold p90':>10}{'warm p50':>10}{'uniq boot':>11}")
    for name in dict.fromkeys(r["variant"] for r in rows):
        rs = [r for r in rows if r["variant"] == name]
        cold = [r["cold_ms"] for r in rs]
        warm = [r["warm_ms"] for r in rs]
        uniq = len({r["boot_token"] for r in rs})
        print(f"{name:<22}{len(rs):>4}{pct(cold, 50):>10.0f}{pct(cold, 90):>10.0f}"
              f"{statistics.median(warm):>10.0f}{uniq:>8}/{len(rs)}")


def cmd_burst(args):
    _, data = clients(args.region, retries=False)
    v = next(r for r in load_state()["runtimes"] if r["name"] == args.variant)

    def one(_):
        t = time.perf_counter()
        try:
            invoke(data, v["arn"], new_session_id())
            return "ok", t
        except ClientError as e:
            return e.response["Error"]["Code"], t

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(one, range(args.sessions)))
    elapsed = time.perf_counter() - start
    codes = {}
    for code, _ in results:
        codes[code] = codes.get(code, 0) + 1
    ok = codes.get("ok", 0)
    print(f"{args.variant}: {args.sessions} new sessions, concurrency={args.concurrency}, "
          f"elapsed={elapsed:.1f}s, ok={ok} ({ok / elapsed:.2f}/s), results={codes}")
    print("註：這些 session 沒有主動 stop，會在閒置 60 秒後自動回收")


def cmd_cleanup(args):
    ctl, _ = clients(args.region)
    state = load_state()
    for v in state["runtimes"]:
        try:
            ctl.delete_agent_runtime(agentRuntimeId=v["id"])
            print(f"deleted {v['name']}")
        except ClientError as e:
            print(f"{v['name']}: {e.response['Error']['Code']}")
    STATE.unlink(missing_ok=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--region", default="ap-northeast-1")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build-zip")
    b.add_argument("--bucket", required=True)

    d = sub.add_parser("deploy")
    d.add_argument("--role-arn", required=True)
    d.add_argument("--image", required=True, help="小 image 的 ECR URI")
    d.add_argument("--big-image", help="加了填充檔的大 image 的 ECR URI（可選）")
    d.add_argument("--bucket", help="direct code zip 所在的 bucket（可選）")
    d.add_argument("--subnets", help="逗號分隔；給了才會建立 VPC 變體")
    d.add_argument("--security-groups")

    m = sub.add_parser("measure")
    m.add_argument("--role-arn", required=True, help="若需要補開 MMDSv2 時使用")
    m.add_argument("--trials", type=int, default=10)
    m.add_argument("--gap", type=float, default=2.0, help="兩次試驗之間的間隔秒數")
    m.add_argument("--only", help="只量測指定的變體，逗號分隔")

    u = sub.add_parser("burst")
    u.add_argument("--variant", required=True)
    u.add_argument("--sessions", type=int, default=60)
    u.add_argument("--concurrency", type=int, default=30)

    sub.add_parser("cleanup")

    global ARGS
    ARGS = p.parse_args()
    {"build-zip": cmd_build_zip, "deploy": cmd_deploy, "measure": cmd_measure,
     "burst": cmd_burst, "cleanup": cmd_cleanup}[ARGS.cmd](ARGS)


if __name__ == "__main__":
    sys.exit(main())
