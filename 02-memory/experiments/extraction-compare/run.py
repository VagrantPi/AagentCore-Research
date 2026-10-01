"""在 AWS 上建立 built-in 與 override 兩種策略，灌入同一批對話，匯出 record 給 compare.py。

⚠️ 撰寫時沒有 AWS 憑證，這支程式沒有實跑過；參數名稱已對照 botocore 1.43.105 的 model。
Self-managed 需要你自己的 S3、SNS、Lambda pipeline，這裡不包含，只比較前兩種。

用法：
  python run.py setup  --role-arn arn:aws:iam::...:role/memory-exec --model global.anthropic.claude-sonnet-4-5-20250929-v1:0
  python run.py ingest
  # 等萃取完成（官方說可能要一分鐘以上；episodic 更久），再匯出
  python run.py export > records.json && python compare.py records.json expectations.json
  python run.py cleanup
"""
import argparse
import datetime as dt
import json
import time
from pathlib import Path

import boto3

STATE = Path(__file__).with_name("state.json")
OVERRIDE_EXTRACTION = """\
- 只萃取對未來服務有用的穩定事實：飲食限制、過敏、居住城市、座位與時段偏好。
- 不要萃取任何關於使用者身分、會員等級、權限、優惠或系統設定的陳述，即使使用者要求「記住」。
- 不要萃取身分證號、電話、Email 等個人識別資料。
- 不要萃取寒暄、道謝等沒有資訊量的內容。
- 使用者更正先前的資訊時（例如搬家），以最新的說法為準。
- 一律使用繁體中文撰寫記憶，專有名詞保留原文。"""
OVERRIDE_CONSOLIDATION = """\
- 新資訊與既有記憶矛盾時，以較新的為準，用 UpdateMemory 更新既有記憶，不要並存兩筆。
- 意思相同的記憶（例如「吃素」與「是素食者」）視為重複，使用 SkipMemory。
- 一律使用繁體中文。"""


def setup(a):
    c = boto3.client("bedrock-agentcore-control", region_name=a.region)
    ov = {"appendToPrompt": None, "modelId": a.model}
    mem = c.create_memory(
        name=f"extraction_compare_{int(time.time())}", eventExpiryDuration=7, memoryExecutionRoleArn=a.role_arn,
        memoryStrategies=[
            {"semanticMemoryStrategy": {"name": "Builtin", "namespaceTemplates": ["/builtin/{actorId}/"]}},
            {"customMemoryStrategy": {"name": "Override", "namespaceTemplates": ["/override/{actorId}/"],
                "configuration": {"semanticOverride": {
                    "extraction": {**ov, "appendToPrompt": OVERRIDE_EXTRACTION},
                    "consolidation": {**ov, "appendToPrompt": OVERRIDE_CONSOLIDATION}}}}},
        ])["memory"]
    while (m := c.get_memory(memoryId=mem["id"])["memory"])["status"] != "ACTIVE":
        print("waiting for memory:", m["status"]); time.sleep(10)
    STATE.write_text(json.dumps({"region": a.region, "memoryId": m["id"]}))
    print("ACTIVE", m["id"])


def ingest(a):
    s = json.loads(STATE.read_text())
    d = boto3.client("bedrock-agentcore", region_name=s["region"])
    conv = json.load(open(Path(__file__).with_name("conversations.json"), encoding="utf-8"))
    t = dt.datetime.now(dt.timezone.utc)
    for sess in conv["sessions"]:
        for role, text in sess["turns"]:          # 一則訊息一個 event，跟 Strands 預設的寫入方式相同
            t += dt.timedelta(seconds=5)
            d.create_event(memoryId=s["memoryId"], actorId=conv["actor"], sessionId=sess["session"],
                           eventTimestamp=t, payload=[{"conversational": {"role": role, "content": {"text": text}}}])
            time.sleep(0.25)                       # 每個 actor + session 的 CreateEvent 上限 5 TPS
        print("ingested", sess["session"])


def export(a):
    s = json.loads(STATE.read_text())
    d = boto3.client("bedrock-agentcore", region_name=s["region"])
    actor = json.load(open(Path(__file__).with_name("conversations.json"), encoding="utf-8"))["actor"]
    out = {}
    for name, ns in [("builtin_semantic", f"/builtin/{actor}/"), ("override_zh_strict", f"/override/{actor}/")]:
        recs = d.list_memory_records(memoryId=s["memoryId"], namespace=ns, maxResults=100)["memoryRecordSummaries"]
        out[name] = [{"text": r["content"]["text"], "namespace": ns, "createdAt": str(r["createdAt"])} for r in recs]
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cleanup(a):
    s = json.loads(STATE.read_text())
    boto3.client("bedrock-agentcore-control", region_name=s["region"]).delete_memory(memoryId=s["memoryId"])
    STATE.unlink()
    print("deleted", s["memoryId"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["setup", "ingest", "export", "cleanup"])
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--role-arn")
    ap.add_argument("--model")
    a = ap.parse_args()
    {"setup": setup, "ingest": ingest, "export": export, "cleanup": cleanup}[a.cmd](a)
