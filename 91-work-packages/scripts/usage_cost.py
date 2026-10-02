# /// script
# requires-python = ">=3.10"
# dependencies = ["boto3"]
# ///
"""從 USAGE_LOGS 依 session 加總 vCPU-hours、GB-hours，乘上官網單價，輸出 CSV 到 stdout。

本帳號拿不到帳單（SCP 禁用 Cost Explorer），這是 WP0 定義的費用估算方法，結果一律標「估算」。

用法：
  uv run usage_cost.py --log-group /aws/vendedlogs/bedrock-agentcore/wp0-usage --since 2026-10-02T03:30
  uv run usage_cost.py --log-group ... --since ... --until 2026-10-02T05:00 > wp0-cost.csv

USAGE_LOGS 一筆 = 一個 session 的一秒，欄位見 WP0 回填區的樣本。
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

# 官網單價（Runtime v1、Code Interpreter、Browser 相同），見 00-overview/README.md 的定價表
PRICE_VCPU_HOUR = 0.0895
PRICE_GB_HOUR = 0.00945


def aggregate(messages):
    """把 USAGE_LOGS 的 JSON 訊息依 (resource, session) 加總成 {key: [秒數, vcpu_h, gb_h]}。"""
    totals = defaultdict(lambda: [0.0, 0.0, 0.0])
    for raw in messages:
        rec = json.loads(raw)
        attrs = rec["attributes"]
        key = (attrs.get("agent.name") or rec["resource_arn"].rsplit("/", 1)[-1], attrs["session.id"])
        t = totals[key]
        t[0] += attrs.get("time_elapsed_seconds", 0)
        for name, value in rec["metrics"].items():
            if name.endswith("vcpu.hours.used"):
                t[1] += value
            elif name.endswith("gb_hours.used"):
                t[2] += value
    return totals


def fetch(log_group, region, since, until):
    import boto3

    logs = boto3.client("logs", region_name=region)
    kwargs = {"logGroupName": log_group, "startTime": int(since.timestamp() * 1000)}
    if until:
        kwargs["endTime"] = int(until.timestamp() * 1000)
    for page in logs.get_paginator("filter_log_events").paginate(**kwargs):
        for event in page["events"]:
            yield event["message"]


def write_csv(totals, out):
    w = csv.writer(out)
    w.writerow(["resource", "session_id", "seconds", "vcpu_hours", "gb_hours", "est_usd"])
    grand = 0.0
    for (resource, session), (secs, vcpu, gb) in sorted(totals.items()):
        usd = vcpu * PRICE_VCPU_HOUR + gb * PRICE_GB_HOUR
        grand += usd
        w.writerow([resource, session, f"{secs:.0f}", f"{vcpu:.6f}", f"{gb:.6f}", f"{usd:.6f}"])
    w.writerow(["（合計）", "", "", "", "", f"{grand:.6f}"])


def parse_time(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--log-group", required=True)
    p.add_argument("--since", required=True, type=parse_time, help="UTC，例如 2026-10-02T03:30")
    p.add_argument("--until", type=parse_time, help="UTC，省略表示到現在")
    p.add_argument("--region", default="ap-northeast-1")
    args = p.parse_args()
    write_csv(aggregate(fetch(args.log_group, args.region, args.since, args.until)), sys.stdout)


if __name__ == "__main__":
    main()
