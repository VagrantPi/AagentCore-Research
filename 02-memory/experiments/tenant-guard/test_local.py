"""本機測試：用假的 client 驗證身分推導、namespace 隔離、刪除流程。"""
import sys
from collections import defaultdict

from guard import IsolationError, MemoryFacade, actor_id_for, actor_namespace, forget_actor


class FakeMemory:
    """只模擬本測試用到的行為；分頁、權限、非同步萃取都沒有模擬。"""

    def __init__(self):
        self.events = defaultdict(list)       # (actor, session) -> [eventId]
        self.records = defaultdict(list)      # namespace -> [recordId]
        self.calls = []

    def create_event(self, **kw):
        self.calls.append(("create_event", kw["actorId"]))
        self.events[(kw["actorId"], kw["sessionId"])].append(f"e{len(self.calls)}")

    def retrieve_memory_records(self, **kw):
        self.calls.append(("retrieve", kw["namespace"]))
        return {"memoryRecordSummaries": [{"memoryRecordId": r} for r in self.records[kw["namespace"]]]}

    def list_sessions(self, memoryId, actorId):
        return {"sessionSummaries": [{"sessionId": s} for (a, s) in self.events if a == actorId]}

    def list_events(self, memoryId, actorId, sessionId):
        return {"events": [{"eventId": e} for e in self.events[(actorId, sessionId)]]}

    def delete_event(self, memoryId, actorId, sessionId, eventId):
        self.events[(actorId, sessionId)].remove(eventId)

    def list_memory_records(self, memoryId, namespace):
        return {"memoryRecordSummaries": [{"memoryRecordId": r} for r in self.records[namespace]]}

    def batch_delete_memory_records(self, memoryId, records):
        for r in records:
            self.records[r["namespace"]].remove(r["memoryRecordId"])


def expect_error(fn):
    try:
        fn()
        return False
    except IsolationError:
        return True


def main():
    alice = {"tenant": "acme", "sub": "alice"}
    alice2 = {"tenant": "acme", "sub": "alice2"}
    evil = {"tenant": "acme", "sub": "alice/x"}
    m = FakeMemory()
    f = MemoryFacade(m, "mem-1", ["sem", "pref"])
    m.records[actor_namespace("sem", "acme_alice")] = [f"r{i}" for i in range(150)]
    m.records[actor_namespace("sem", "acme_alice2")] = ["other"]
    m.records["/strategy/refl/"] = ["cross-actor-reflection"]

    checks = []
    f.create_event(alice, "s1", [("USER", "我吃素")], 0)
    f.create_event(alice, "s2", [("USER", "我在台北")], 0)
    f.create_event(alice2, "s1", [("USER", "我是 alice2")], 0)
    checks.append(("actorId 由後端推導（租戶前綴）", m.calls[0] == ("create_event", "acme_alice")))
    checks.append(("sub 含 / 會被拒絕", expect_error(lambda: actor_id_for(evil))))
    checks.append(("缺 tenant claim 會被拒絕", expect_error(lambda: actor_id_for({"sub": "alice"}))))
    checks.append(("sessionId 含 / 會被拒絕", expect_error(lambda: f.create_event(alice, "s/../x", [], 0))))
    got = f.retrieve(alice, "飲食偏好")
    checks.append(("alice 只檢索到自己的 150 筆", len(got) == 150))
    checks.append(("namespace 結尾有 /", all(ns.endswith("/") for op, ns in m.calls if op == "retrieve")))

    res = forget_actor(m, "mem-1", "acme_alice", ["sem", "pref"])
    checks.append(("刪除 alice：2 筆事件、150 筆 record（分兩批）", res == {"events": 2, "records": 150}))
    checks.append(("alice2 的資料不受影響", m.records[actor_namespace("sem", "acme_alice2")] == ["other"]
                   and m.events[("acme_alice2", "s1")]))
    checks.append(("跨使用者的 reflection 刪不到（已知限制）", m.records["/strategy/refl/"] == ["cross-actor-reflection"]))

    ok = True
    for name, passed in checks:
        ok &= bool(passed)
        print(f"{'✓' if passed else '✗'} {name}")
    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
