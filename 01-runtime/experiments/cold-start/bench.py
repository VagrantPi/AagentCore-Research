"""AgentCore Runtime 冷啟動與 session 建立速率實驗。

子命令：
  build-zip   打包 direct code 用的 zip 並上傳到 S3
  deploy      依矩陣建立各變體的 runtime，等待 READY，並把狀態寫入 state.json
  measure     每個變體跑 N 次「新 session 冷啟動 → 同 session 熱呼叫」，結果寫入 results.csv
  burst       對單一變體並發建立 M 個新 session，觀察被 throttle 的比例與實際速率
  concurrent  同一個 session 同時送 N 個長請求（模擬多個聊天室），結果寫入 concurrent.csv
  prewarm     先送空請求預喚醒，隔幾秒再送真正的請求，結果寫入 prewarm.csv
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
CONCURRENT = HERE / "concurrent.csv"
PREWARM = HERE / "prewarm.csv"
ZIP_KEY = "agentcore-coldstart/agent.zip"

# 壓低 lifecycle，避免閒置 session 持續計費
LIFECYCLE = {"idleRuntimeSessionTimeout": 60, "maxLifetime": 600}
# 依 WP0 的資源 tag 規則；owner 由 deploy --owner 補上
TAGS = {"wp": "WP1", "project": "hyfai"}


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
                out.append({"name": f"wp1_cs_{pv.lower()}_{an}_{nn}", "platform": pv,
                            "artifact": art, "network": net})
    if args.blocking:
        # 並行測試的對照組：單執行緒 server，一次只處理一個請求
        out.append({"name": "wp1_cs_v1_img_pub_blk", "platform": "V1", "artifact": artifacts[0][1],
                    "network": networks[0][1], "env": {"AGENT_MODE": "blocking"}})
    if args.busy:
        # 長請求對照組：處理中 /ping 回 HealthyBusy
        out.append({"name": "wp1_cs_v1_img_pub_busy", "platform": "V1", "artifact": artifacts[0][1],
                    "network": networks[0][1], "env": {"PING_BUSY": "1"}})
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
            lifecycleConfiguration=LIFECYCLE, platformVersion=v["platform"],
            environmentVariables=v.get("env", {}), tags={**TAGS, "owner": args.owner})
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
        environmentVariables=v.get("env", {}), metadataConfiguration={"requireMMDSV2": True})
    print(f"{v['name']}: enabled MMDSv2, waiting for READY ...")
    print(f"{v['name']}: {wait_ready(ctl, v['id'])}")


def invoke(data, arn, session_id, payload=b'{"prompt":"ping"}'):
    t0 = time.perf_counter()
    resp = data.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId=session_id,
                                     qualifier="DEFAULT", contentType="application/json",
                                     payload=payload)
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
    append_csv(RESULTS, rows)
    summarize(rows)


def append_csv(path, rows):
    new_file = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        if new_file:
            w.writeheader()
        w.writerows(rows)


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
        return try_invoke(data, v["arn"], new_session_id(), b'{"prompt":"ping"}')

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(one, range(args.sessions)))
    elapsed = time.perf_counter() - start
    codes = {}
    for code, _, _ in results:
        codes[code] = codes.get(code, 0) + 1
    ok = codes.get("ok", 0)
    print(f"{args.variant}: {args.sessions} new sessions, concurrency={args.concurrency}, "
          f"elapsed={elapsed:.1f}s, ok={ok} ({ok / elapsed:.2f}/s), results={codes}")
    # boot_age_s 很小代表 process 是為這個請求才啟動的（真冷啟動），很大代表來自預熱池
    oks = [(ms, b["boot_age_s"]) for c, ms, b in results if c == "ok"]
    for label, xs in (("pool", [ms for ms, age in oks if age >= 5]),
                      ("fresh", [ms for ms, age in oks if age < 5])):
        if xs:
            print(f"  {label}: n={len(xs)} latency p50={pct(xs, 50):.0f}ms p90={pct(xs, 90):.0f}ms")
    append_csv(HERE / "burst.csv", [{"variant": args.variant, "status": c, "latency_ms": ms,
                                     "boot_age_s": b.get("boot_age_s")} for c, ms, b in results])
    print("註：這些 session 沒有主動 stop，會在閒置 60 秒後自動回收")


def find_variant(name):
    return next(r for r in load_state()["runtimes"] if r["name"] == name)


def try_invoke(data, arn, sid, payload):
    """回傳 (狀態, 延遲 ms, 回應)；失敗時狀態是錯誤碼，不重試。"""
    t0 = time.perf_counter()
    try:
        ms, body = invoke(data, arn, sid, payload)
        return "ok", ms, body
    except ClientError as e:
        return e.response["Error"]["Code"], round((time.perf_counter() - t0) * 1000, 1), {}


def cmd_concurrent(args):
    """WP1 #8：同一個 session 同時送 N 個各睡 S 秒的請求，模擬一位使用者的多個聊天室。"""
    _, data = clients(args.region, retries=False)
    rows = []
    payload = json.dumps({"sleep": args.sleep}).encode()
    for name in args.variants.split(","):
        v = find_variant(name)
        for i in range(args.trials):
            sid = new_session_id()
            status, cold_ms, _ = try_invoke(data, v["arn"], sid, b'{"prompt":"ping"}')  # 先把 VM 叫起來
            with ThreadPoolExecutor(max_workers=args.n) as pool:
                futs = [pool.submit(try_invoke, data, v["arn"], sid, payload) for _ in range(args.n)]
                res = [f.result() for f in futs]
            for j, (code, ms, body) in enumerate(res):
                rows.append({"variant": name, "trial": i, "req": j, "status": code, "latency_ms": ms,
                             "boot_token": body.get("boot_token"),
                             "inflight_at_start": body.get("inflight_at_start"),
                             "pings_during": body.get("pings_during"),
                             "handler_s": body.get("handler_s")})
            try:
                data.stop_runtime_session(agentRuntimeArn=v["arn"], runtimeSessionId=sid,
                                          qualifier="DEFAULT")
            except data.exceptions.ResourceNotFoundException:
                print(f"{name} #{i}: session 已被平台終止")
            print(f"{name} #{i}: warmup={status}/{cold_ms}ms | " + " | ".join(
                f"{c} {ms / 1000:.1f}s inflight={b.get('inflight_at_start')} pings={b.get('pings_during')}"
                for c, ms, b in res))
            time.sleep(args.gap)
    append_csv(CONCURRENT, rows)


def cmd_prewarm(args):
    """WP1 #7：開聊天室時先送空請求（不等它回來），D 秒後送真正的請求。"""
    _, data = clients(args.region, retries=False)
    rows = []
    for name in args.variants.split(","):
        v = find_variant(name)
        for i in range(args.trials):
            sid = new_session_id()
            with ThreadPoolExecutor(max_workers=1) as pool:
                warm = pool.submit(try_invoke, data, v["arn"], sid, b"{}")
                time.sleep(args.delay)
                code, real_ms, real = try_invoke(data, v["arn"], sid, b'{"prompt":"ping"}')
                pcode, pre_ms, pre = warm.result()
            rows.append({"variant": name, "trial": i, "delay_s": args.delay,
                         "prewarm_status": pcode, "prewarm_ms": pre_ms,
                         "real_status": code, "real_ms": real_ms,
                         "real_first_request": real.get("first_request"),
                         "same_boot": pre.get("boot_token") == real.get("boot_token")})
            data.stop_runtime_session(agentRuntimeArn=v["arn"], runtimeSessionId=sid,
                                      qualifier="DEFAULT")
            print(f"{name} #{i}: prewarm={pcode}/{pre_ms}ms real={code}/{real_ms}ms")
            time.sleep(args.gap)
    append_csv(PREWARM, rows)
    print(f"\n{'variant':<26}{'ok':>4}{'real p50':>10}{'real p90':>10}{'prewarm p50':>13}")
    for name in dict.fromkeys(r["variant"] for r in rows):
        rs = [r for r in rows if r["variant"] == name and r["real_status"] == "ok"]
        if rs:
            print(f"{name:<26}{len(rs):>4}{pct([r['real_ms'] for r in rs], 50):>10.0f}"
                  f"{pct([r['real_ms'] for r in rs], 90):>10.0f}"
                  f"{pct([r['prewarm_ms'] for r in rs], 50):>13.0f}")


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
    d.add_argument("--blocking", action="store_true", help="另建單執行緒 agent 的 V1 變體（並行測試對照組）")
    d.add_argument("--busy", action="store_true", help="另建處理中 /ping 回 HealthyBusy 的 V1 變體")
    d.add_argument("--owner", required=True, help="tag owner 的值，例如 kais")

    m = sub.add_parser("measure")
    m.add_argument("--role-arn", required=True, help="若需要補開 MMDSv2 時使用")
    m.add_argument("--trials", type=int, default=10)
    m.add_argument("--gap", type=float, default=2.0, help="兩次試驗之間的間隔秒數")
    m.add_argument("--only", help="只量測指定的變體，逗號分隔")

    u = sub.add_parser("burst")
    u.add_argument("--variant", required=True)
    u.add_argument("--sessions", type=int, default=60)
    u.add_argument("--concurrency", type=int, default=30)

    c = sub.add_parser("concurrent")
    c.add_argument("--variants", required=True, help="逗號分隔")
    c.add_argument("--n", type=int, default=3, help="同時送幾個請求")
    c.add_argument("--sleep", type=float, default=20, help="每個請求在 handler 裡睡幾秒")
    c.add_argument("--trials", type=int, default=3)
    c.add_argument("--gap", type=float, default=2.0)

    w = sub.add_parser("prewarm")
    w.add_argument("--variants", required=True, help="逗號分隔")
    w.add_argument("--delay", type=float, default=3.0, help="預喚醒後隔幾秒送真正的請求")
    w.add_argument("--trials", type=int, default=20)
    w.add_argument("--gap", type=float, default=2.0)

    sub.add_parser("cleanup")

    global ARGS
    ARGS = p.parse_args()
    {"build-zip": cmd_build_zip, "deploy": cmd_deploy, "measure": cmd_measure,
     "burst": cmd_burst, "concurrent": cmd_concurrent, "prewarm": cmd_prewarm,
     "cleanup": cmd_cleanup}[ARGS.cmd](ARGS)


if __name__ == "__main__":
    sys.exit(main())
