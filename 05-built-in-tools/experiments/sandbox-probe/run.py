# /// script
# requires-python = ">=3.10"
# dependencies = ["boto3"]
# ///
"""把 probe.py 送進指定的 Code Interpreter 執行，印出結果與 session 起訖時間。

用法：uv run run.py <codeInterpreterId> [--region ap-northeast-1] [--hold 0]
--hold：跑完 probe 後讓 session 再存活幾秒（量閒置費用用），之後一定會呼叫 StopCodeInterpreterSession。
"""

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config


def run_code(data, ci_id, session_id, code):
    resp = data.invoke_code_interpreter(codeInterpreterIdentifier=ci_id, sessionId=session_id,
                                        name="executeCode", arguments={"language": "python", "code": code})
    out = []
    for event in resp["stream"]:
        result = event.get("result", {})
        sc = result.get("structuredContent", {})
        out.append(sc.get("stdout") or "".join(c.get("text", "") for c in result.get("content", [])))
        if sc.get("stderr"):
            out.append("[stderr] " + sc["stderr"])
    return "\n".join(o for o in out if o)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ci_id")
    p.add_argument("--region", default="ap-northeast-1")
    p.add_argument("--hold", type=int, default=0)
    args = p.parse_args()

    # Sandbox 模式下每個連不上的測試都要等逾時，總時間會超過預設的 60 秒讀取逾時
    data = boto3.client("bedrock-agentcore", region_name=args.region, config=Config(read_timeout=600))
    started = datetime.now(timezone.utc)
    sid = data.start_code_interpreter_session(codeInterpreterIdentifier=args.ci_id, name="wp3-probe",
                                              sessionTimeoutSeconds=900)["sessionId"]
    print(f"session {sid} started {started:%H:%M:%S}Z")
    try:
        print(run_code(data, args.ci_id, sid, (Path(__file__).parent / "probe.py").read_text()))
        if args.hold:
            time.sleep(args.hold)
    finally:
        data.stop_code_interpreter_session(codeInterpreterIdentifier=args.ci_id, sessionId=sid)
        print(f"session stopped {datetime.now(timezone.utc):%H:%M:%S}Z")


if __name__ == "__main__":
    main()
