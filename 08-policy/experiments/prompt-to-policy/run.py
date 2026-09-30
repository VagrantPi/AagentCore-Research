"""在本機用 Cedar 驗證「從 prompt 搬到 policy」的規則。

用法：pip install cedarpy && python run.py
會做兩件事：
1. 用 schema 驗證 policies.cedar（應該通過）和 bad-policy.cedar（應該被抓出來）
2. 跑一組授權案例，對照預期結果
"""
import json
import sys
from pathlib import Path

import cedarpy

HERE = Path(__file__).parent
SCHEMA = (HERE / "schema.cedarschema").read_text()
POLICIES = (HERE / "policies.cedar").read_text()
BAD = (HERE / "bad-policy.cedar").read_text()
GW = 'AgentCore::Gateway::"arn:aws:bedrock-agentcore:ap-northeast-1:111122223333:gateway/demo"'


def user(uid, **tags):
    return {"uid": {"type": "AgentCore::OAuthUser", "id": uid}, "attrs": {"id": uid}, "parents": [], "tags": tags}


ENTITIES = [
    user("alice", role="customer"),
    user("bob", role="supervisor"),
    user("mallory"),  # 沒有 role claim
    {"uid": {"type": "AgentCore::Gateway", "id": "arn:aws:bedrock-agentcore:ap-northeast-1:111122223333:gateway/demo"}, "attrs": {}, "parents": []},
]


def refund(who, amount, country="US", customer=None, reason="damaged"):
    inp = {"orderId": "o-1", "customerId": customer or who, "amountCents": amount, "country": country}
    if reason is not None:
        inp["reason"] = reason
    return {
        "principal": f'AgentCore::OAuthUser::"{who}"',
        "action": 'AgentCore::Action::"OrderTarget___process_refund"',
        "resource": GW,
        "context": {"input": inp},
    }


CASES = [
    ("alice 退自己的 $120", refund("alice", 12000), "Allow"),
    ("alice 退 $500（剛好上限）", refund("alice", 50000), "Allow"),
    ("alice 退 $500.01", refund("alice", 50001), "Deny"),
    ("alice 退款到日本", refund("alice", 12000, country="JP"), "Deny"),
    ("alice 沒填原因", refund("alice", 12000, reason=None), "Deny"),
    ("alice 退 mallory 的訂單", refund("alice", 12000, customer="mallory"), "Deny"),
    ("bob（主管）退別人 $3,000", refund("bob", 300000, customer="alice"), "Allow"),
    ("bob（主管）退 $6,000", refund("bob", 600000, customer="alice"), "Deny"),
    ("mallory 沒有 role claim，退自己的 $50", refund("mallory", 5000), "Allow"),
    ("查詢訂單", {"principal": 'AgentCore::OAuthUser::"mallory"', "action": 'AgentCore::Action::"OrderTarget___get_order"', "resource": GW, "context": {"input": {"orderId": "o-1"}}}, "Allow"),
]


def main():
    ok = True
    good = cedarpy.validate_policies(POLICIES, SCHEMA)
    print(f"[validate] policies.cedar   -> {'PASS' if good.validation_passed else 'FAIL'}")
    for e in good.errors:
        print("   ", e)
    ok &= good.validation_passed

    bad = cedarpy.validate_policies(BAD, SCHEMA)
    print(f"[validate] bad-policy.cedar -> {'PASS' if bad.validation_passed else 'FAIL（預期會失敗）'}")
    for e in bad.errors:
        print("   ", e)
    ok &= not bad.validation_passed

    print()
    for name, req, want in CASES:
        got = cedarpy.is_authorized(req, POLICIES, ENTITIES, SCHEMA)
        decision = "Allow" if got.decision == cedarpy.Decision.Allow else "Deny"
        mark = "✓" if decision == want else "✗"
        ok &= decision == want
        reasons = ",".join(got.diagnostics.reasons) or "-"
        print(f"{mark} {name:<34} want={want:<5} got={decision:<5} by={reasons}")
    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
