"""WP1 #5、#6：session storage 在閒置逾時、停止再恢復、更新 runtime 版本後還在不在。

用法：
  python storage.py run --role-arn <role> --image <ecr>:wp1-ss --owner <人>
  python storage.py cleanup

建一個掛 session storage（/mnt/ws）的 V1 runtime，依序做：
  idle        寫入 → 等超過閒置逾時 → 再呼叫，看記憶體與檔案（#5）
  stop        寫入 → StopRuntimeSession → 再呼叫，同版本的基準
  update      寫入 → 停止 → 更新 runtime 版本 → 透過 DEFAULT 再呼叫（#6a）
  pinned      建固定指向目前版本的 endpoint → 寫入 → 停止 → 更新版本 → 透過固定 endpoint 再呼叫（#6b）
結果寫入 storage.csv。
"""

import argparse
import json
import time
import uuid

from bench import HERE, TAGS, append_csv, clients, load_state, new_session_id, save_state, wait_ready

NAME = "wp1_ss_v1_img_pub"
ENDPOINT = "wp1_pinned"
IDLE = 60


def invoke(data, arn, sid, payload, qualifier="DEFAULT"):
    resp = data.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId=sid, qualifier=qualifier,
                                     contentType="application/json", payload=json.dumps(payload).encode())
    return json.loads(resp["response"].read())


def stop(data, arn, sid, qualifier="DEFAULT"):
    data.stop_runtime_session(agentRuntimeArn=arn, runtimeSessionId=sid, qualifier=qualifier)


def bump_version(ctl, rid, version):
    """改環境變數 AGENT_VERSION 產生新的 runtime 版本，回傳新版本號。"""
    cur = ctl.get_agent_runtime(agentRuntimeId=rid)
    keep = ("roleArn", "agentRuntimeArtifact", "networkConfiguration", "lifecycleConfiguration",
            "filesystemConfigurations", "metadataConfiguration")
    resp = ctl.update_agent_runtime(
        agentRuntimeId=rid, **{k: cur[k] for k in keep if k in cur},
        environmentVariables={**cur.get("environmentVariables", {}), "AGENT_VERSION": str(version)})
    print(f"  update -> runtime version {resp['agentRuntimeVersion']}: {wait_ready(ctl, rid)}")
    return resp["agentRuntimeVersion"]


def row(test, step, body, runtime_version=None):
    r = {"test": test, "step": step, "version": body.get("version"), "boot_token": body.get("boot_token"),
         "mem": body.get("mem"), "disk": body.get("disk"), "disk_error": body.get("disk_error"),
         "runtime_version": runtime_version}
    print(f"  {test}/{step}: " + json.dumps({k: v for k, v in r.items() if k not in ("test", "step")}))
    return r


def cmd_run(args):
    ctl, data = clients(args.region)
    state = load_state()
    v = next((r for r in state["runtimes"] if r["name"] == NAME), None)
    if not v:
        resp = ctl.create_agent_runtime(
            agentRuntimeName=NAME, roleArn=args.role_arn,
            agentRuntimeArtifact={"containerConfiguration": {"containerUri": args.image}},
            networkConfiguration={"networkMode": "PUBLIC"},
            lifecycleConfiguration={"idleRuntimeSessionTimeout": IDLE, "maxLifetime": 3600},
            filesystemConfigurations=[{"sessionStorage": {"mountPath": "/mnt/ws"}}],
            environmentVariables={"AGENT_VERSION": "1", "SESSION_DIR": "/mnt/ws"},
            platformVersion="V1", tags={**TAGS, "owner": args.owner})
        v = {"name": NAME, "id": resp["agentRuntimeId"], "arn": resp["agentRuntimeArn"], "platform": "V1"}
        state["runtimes"].append(v)
        save_state(state)
        print(f"created {NAME} -> {v['id']}: {wait_ready(ctl, v['id'])}")
    rid, arn = v["id"], v["arn"]
    rows = []
    tag = uuid.uuid4().hex[:6]

    print("[idle] #5")
    sid = new_session_id()
    rows.append(row("idle", "put", invoke(data, arn, sid, {"put": f"idle-{tag}"})))
    rows.append(row("idle", "within_idle_30s", (time.sleep(30), invoke(data, arn, sid, {}))[1]))
    time.sleep(IDLE + 30)
    rows.append(row("idle", f"after_idle_{IDLE + 30}s", invoke(data, arn, sid, {})))
    stop(data, arn, sid)

    print("[stop] 同版本停止再恢復")
    sid = new_session_id()
    rows.append(row("stop", "put", invoke(data, arn, sid, {"put": f"stop-{tag}"})))
    stop(data, arn, sid)
    rows.append(row("stop", "after_stop", invoke(data, arn, sid, {})))
    stop(data, arn, sid)

    print("[update] #6a")
    cur_version = ctl.get_agent_runtime(agentRuntimeId=rid)["agentRuntimeVersion"]
    sid = new_session_id()
    rows.append(row("update", "put", invoke(data, arn, sid, {"put": f"update-{tag}"}), runtime_version=cur_version))
    stop(data, arn, sid)
    new_version = bump_version(ctl, rid, int(cur_version) + 1)
    rows.append(row("update", "after_update_default", invoke(data, arn, sid, {}), runtime_version=new_version))
    stop(data, arn, sid)

    print("[pinned] #6b")
    pinned_version = ctl.get_agent_runtime(agentRuntimeId=rid)["agentRuntimeVersion"]
    try:
        ctl.create_agent_runtime_endpoint(agentRuntimeId=rid, name=ENDPOINT, agentRuntimeVersion=pinned_version,
                                          tags={**TAGS, "owner": args.owner})
    except ctl.exceptions.ConflictException:
        ctl.update_agent_runtime_endpoint(agentRuntimeId=rid, endpointName=ENDPOINT,
                                          agentRuntimeVersion=pinned_version)
    for _ in range(90):
        ep = ctl.get_agent_runtime_endpoint(agentRuntimeId=rid, endpointName=ENDPOINT)
        if ep["status"] == "READY" and ep.get("liveVersion") == pinned_version:
            break
        time.sleep(10)
    print(f"  endpoint {ENDPOINT} -> version {ep.get('liveVersion')} ({ep['status']})")
    sid = new_session_id()
    rows.append(row("pinned", "put", invoke(data, arn, sid, {"put": f"pinned-{tag}"}, ENDPOINT),
                    runtime_version=pinned_version))
    stop(data, arn, sid, ENDPOINT)
    new_version = bump_version(ctl, rid, int(pinned_version) + 1)
    rows.append(row("pinned", "after_update_pinned", invoke(data, arn, sid, {}, ENDPOINT),
                    runtime_version=new_version))
    stop(data, arn, sid, ENDPOINT)

    append_csv(HERE / "storage.csv", rows)


def cmd_cleanup(args):
    ctl, _ = clients(args.region)
    v = next((r for r in load_state()["runtimes"] if r["name"] == NAME), None)
    if v:
        try:
            ctl.delete_agent_runtime_endpoint(agentRuntimeId=v["id"], endpointName=ENDPOINT)
            print(f"deleted endpoint {ENDPOINT}")
        except ctl.exceptions.ResourceNotFoundException:
            pass
    print("runtime 本身由 bench.py cleanup 刪除")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--region", default="ap-northeast-1")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--role-arn", required=True)
    r.add_argument("--image", required=True)
    r.add_argument("--owner", required=True)
    sub.add_parser("cleanup")
    args = p.parse_args()
    {"run": cmd_run, "cleanup": cmd_cleanup}[args.cmd](args)


if __name__ == "__main__":
    main()
