# /// script
# requires-python = ">=3.10"
# dependencies = ["boto3"]
# ///
"""依 `wp` tag 拉 Cost Explorer 的實際金額（UnblendedCost），輸出 CSV 到 stdout。

每列是一個 (wp, 服務) 的金額，最後附每個 WP 的小計。沒掛 `wp` tag 的花費歸在 `(未標記)`。

用法：
  uv run cost_by_wp.py --start 2026-10-01 --end 2026-10-08              # 全部 WP
  uv run cost_by_wp.py --start 2026-10-01 --end 2026-10-08 --wp WP0    # 只看 WP0
  uv run cost_by_wp.py --start 2026-10-01 --end 2026-10-08 --owner kais > wp.csv

--end 不含當天（Cost Explorer 的慣例）。需要 ce:GetCostAndUsage 權限，同事的實驗身分沒有，由帳號負責人執行。
"""

import argparse
import csv
import sys
from collections import defaultdict


def aggregate(results_by_time):
    """把 GetCostAndUsage 的 ResultsByTime（依 TAG wp + SERVICE 分組）加總成 {(wp, service): usd}。"""
    totals = defaultdict(float)
    for period in results_by_time:
        for group in period["Groups"]:
            tag, service = group["Keys"]
            wp = tag.split("$", 1)[1] or "(未標記)"  # 回傳格式是 "wp$WP0"，未標記為 "wp$"
            totals[(wp, service)] += float(group["Metrics"]["UnblendedCost"]["Amount"])
    return totals


def fetch(start, end, wp=None, owner=None):
    import boto3

    ce = boto3.client("ce", region_name="us-east-1")  # Cost Explorer 只有 us-east-1 端點
    filters = [{"Tags": {"Key": k, "Values": [v], "MatchOptions": ["EQUALS"]}} for k, v in (("wp", wp), ("owner", owner)) if v]
    kwargs = {
        "TimePeriod": {"Start": start, "End": end},
        "Granularity": "DAILY",
        "Metrics": ["UnblendedCost"],
        "GroupBy": [{"Type": "TAG", "Key": "wp"}, {"Type": "DIMENSION", "Key": "SERVICE"}],
    }
    if filters:
        kwargs["Filter"] = filters[0] if len(filters) == 1 else {"And": filters}
    results = []
    while True:
        resp = ce.get_cost_and_usage(**kwargs)
        results += resp["ResultsByTime"]
        if not resp.get("NextPageToken"):
            return results
        kwargs["NextPageToken"] = resp["NextPageToken"]


def write_csv(totals, out):
    w = csv.writer(out)
    w.writerow(["wp", "service", "unblended_usd"])
    subtotal = defaultdict(float)
    for (wp, service), usd in sorted(totals.items()):
        w.writerow([wp, service, f"{usd:.4f}"])
        subtotal[wp] += usd
    for wp, usd in sorted(subtotal.items()):
        w.writerow([wp, "（小計）", f"{usd:.4f}"])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", required=True, help="YYYY-MM-DD，含當天")
    p.add_argument("--end", required=True, help="YYYY-MM-DD，不含當天")
    p.add_argument("--wp", help="只看某個 WP，例如 WP0")
    p.add_argument("--owner", help="只看某人的資源")
    args = p.parse_args()
    write_csv(aggregate(fetch(args.start, args.end, args.wp, args.owner)), sys.stdout)


if __name__ == "__main__":
    main()
