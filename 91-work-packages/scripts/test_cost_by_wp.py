"""不連 AWS 的檢查：用假的 GetCostAndUsage 回應驗證加總與 CSV。執行：python3 test_cost_by_wp.py"""

import io

from cost_by_wp import aggregate, write_csv


def group(tag, service, amount):
    return {"Keys": [tag, service], "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}}}


days = [
    {"Groups": [group("wp$WP0", "Amazon Bedrock AgentCore", "0.10"), group("wp$", "AWS Lambda", "1.00")]},
    {"Groups": [group("wp$WP0", "Amazon Bedrock AgentCore", "0.25")]},
]
totals = aggregate(days)
assert abs(totals[("WP0", "Amazon Bedrock AgentCore")] - 0.35) < 1e-9
assert totals[("(未標記)", "AWS Lambda")] == 1.0

out = io.StringIO()
write_csv(totals, out)
lines = out.getvalue().splitlines()
assert lines[0] == "wp,service,unblended_usd"
assert "WP0,（小計）,0.3500" in lines
print("ok")
