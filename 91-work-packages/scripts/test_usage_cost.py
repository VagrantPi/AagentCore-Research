"""不連 AWS 的檢查：用 USAGE_LOGS 格式的假資料驗證加總與金額。執行：python3 test_usage_cost.py"""

import io
import json

from usage_cost import aggregate, write_csv


def rec(session, vcpu, gb):
    return json.dumps({
        "resource_arn": "arn:aws:bedrock-agentcore:ap-northeast-1:1:runtime/wp0_min-x",
        "attributes": {"agent.name": "wp0_min", "session.id": session, "time_elapsed_seconds": 1.0},
        "metrics": {"agent.runtime.vcpu.hours.used": vcpu, "agent.runtime.memory.gb_hours.used": gb},
    })


totals = aggregate([rec("s1", 1.0, 10.0), rec("s1", 1.0, 10.0), rec("s2", 0.0, 1.0)])
assert totals[("wp0_min", "s1")] == [2.0, 2.0, 20.0]

out = io.StringIO()
write_csv(totals, out)
lines = out.getvalue().splitlines()
assert lines[1] == "wp0_min,s1,2,2.000000,20.000000,0.368000"  # 2 × 0.0895 + 20 × 0.00945
assert lines[-1] == "（合計）,,,,,0.377450"
print("ok")
