"""Memory 多租戶隔離的後端參考實作。

原則：actorId、sessionId、namespace 一律由後端從「已驗證的身分」推導，前端傳來的一概不用。

  - actor_id_for()：從已驗證的 JWT claims 產生 actorId（租戶前綴 + sub），並拒絕 / 與 : ——
    AgentCore 的 actorId 允許這兩個字元，`alice/x` 會落進 namespacePath `.../alice/*` 的範圍
  - MemoryFacade：所有讀寫都經過這裡，前端只能給「內容」與「查詢字串」
  - forget_actor()：刪除一個使用者的短期與長期記憶（沒有官方的整批刪除 API，只能逐筆）

client 介面與 boto3 的 bedrock-agentcore 相同（參數名稱依 botocore 1.43.105）。
"""
import re

SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")


class IsolationError(ValueError):
    pass


def actor_id_for(claims):
    tenant, sub = claims.get("tenant"), claims.get("sub")
    if not tenant or not sub:
        raise IsolationError("已驗證的 token 缺少 tenant 或 sub")
    actor = f"{tenant}_{sub}"
    if not SAFE.match(actor):
        raise IsolationError(f"actorId 含不允許的字元：{actor!r}")
    return actor


def actor_namespace(strategy_id, actor_id):
    return f"/strategy/{strategy_id}/actor/{actor_id}/"   # 結尾一定要有 /，避免 alice 前綴比對到 alice2


class MemoryFacade:
    def __init__(self, client, memory_id, strategy_ids):
        self.c, self.memory_id, self.strategy_ids = client, memory_id, strategy_ids

    def create_event(self, claims, session_id, messages, event_time):
        if not SAFE.match(session_id):
            raise IsolationError("sessionId 格式錯誤")
        return self.c.create_event(
            memoryId=self.memory_id, actorId=actor_id_for(claims), sessionId=session_id,
            eventTimestamp=event_time,
            payload=[{"conversational": {"role": role, "content": {"text": text}}} for role, text in messages])

    def retrieve(self, claims, query, top_k=5):
        actor = actor_id_for(claims)
        out = []
        for sid in self.strategy_ids:
            resp = self.c.retrieve_memory_records(
                memoryId=self.memory_id, namespace=actor_namespace(sid, actor),
                searchCriteria={"searchQuery": query, "topK": top_k})
            out += resp.get("memoryRecordSummaries", [])
        return out


def forget_actor(client, memory_id, actor_id, strategy_ids):
    """刪除一個 actor 的所有事件與 record。回傳刪除數量。

    限制：只刪得到「namespace 含 actorId」的 record；strategy 層級（跨使用者）的 reflection 無法歸屬到個人。
    """
    events = records = 0
    sessions = client.list_sessions(memoryId=memory_id, actorId=actor_id).get("sessionSummaries", [])
    for s in sessions:
        evs = client.list_events(memoryId=memory_id, actorId=actor_id, sessionId=s["sessionId"]).get("events", [])
        for e in evs:
            client.delete_event(memoryId=memory_id, actorId=actor_id, sessionId=s["sessionId"], eventId=e["eventId"])
            events += 1
    for sid in strategy_ids:
        ns = actor_namespace(sid, actor_id)
        ids = [r["memoryRecordId"] for r in
               client.list_memory_records(memoryId=memory_id, namespace=ns).get("memoryRecordSummaries", [])]
        for i in range(0, len(ids), 100):   # BatchDeleteMemoryRecords 每次最多 100 筆
            client.batch_delete_memory_records(
                memoryId=memory_id, records=[{"memoryRecordId": r, "namespace": ns} for r in ids[i:i + 100]])
        records += len(ids)
    return {"events": events, "records": records}
