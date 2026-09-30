"""從 LOG_ONLY 期間收集到的 guardrail 分數 + 人工標註，算出每個門檻的混淆矩陣與成本。

輸入 CSV 欄位：score（0/0.2/0.4/0.6/0.8/1.0），label（1 = 應該擋，0 = 不該擋）
規則假設：score >= 門檻 就擋（對應 Cedar 的 .greaterThanOrEqual(decimal("X"))）

用法：
  python calibrate.py sample.csv --cost-fp 1 --cost-fn 20
  --cost-fp：誤擋一次的成本；--cost-fn：漏擋一次的成本（相對值即可）
"""
import argparse
import csv
from collections import Counter

THRESHOLDS = [0.2, 0.4, 0.6, 0.8, 1.0]


def load(path):
    with open(path, newline="") as f:
        return [(round(float(r["score"]), 1), int(r["label"])) for r in csv.DictReader(f)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--cost-fp", type=float, default=1.0)
    ap.add_argument("--cost-fn", type=float, default=10.0)
    args = ap.parse_args()

    rows = load(args.csv)
    pos = sum(label for _, label in rows)
    print(f"樣本數 {len(rows)}（應擋 {pos}、不該擋 {len(rows) - pos}）")
    print("分數分布（score: 應擋/不該擋）：",
          ", ".join(f"{s}: {c[(s, 1)]}/{c[(s, 0)]}" for c in [Counter(rows)] for s in sorted({s for s, _ in rows})))
    print()
    print(f"{'門檻':>5} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4} {'precision':>9} {'recall':>7} {'誤擋率':>6} {'成本':>7}")
    best = None
    for t in THRESHOLDS:
        tp = sum(1 for s, l in rows if s >= t and l == 1)
        fp = sum(1 for s, l in rows if s >= t and l == 0)
        fn = sum(1 for s, l in rows if s < t and l == 1)
        tn = sum(1 for s, l in rows if s < t and l == 0)
        precision = tp / (tp + fp) if tp + fp else float("nan")
        recall = tp / (tp + fn) if tp + fn else float("nan")
        fpr = fp / (fp + tn) if fp + tn else float("nan")
        cost = fp * args.cost_fp + fn * args.cost_fn
        print(f"{t:>5.1f} {tp:>4} {fp:>4} {fn:>4} {tn:>4} {precision:>9.2f} {recall:>7.2f} {fpr:>6.2f} {cost:>7.1f}")
        if best is None or cost < best[1]:
            best = (t, cost)
    print(f"\n在 誤擋成本={args.cost_fp}、漏擋成本={args.cost_fn} 下，成本最低的門檻：{best[0]}")


if __name__ == "__main__":
    main()
