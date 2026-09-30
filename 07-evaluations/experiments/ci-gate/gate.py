"""CI 的通過門檻：服務端沒有門檻設定，要在 client 端自己判斷。

輸入：results.json，格式為 [{"scenario": "...", "evaluator": "...", "value": 0.83}, ...]
      （把 on-demand runner / Evaluate API 的結果整理成這個扁平格式）
設定：thresholds.json，例如 {"Builtin.Correctness": {"mean": 0.8, "min": 0.5}, "Custom.NoPII": {"min": 1.0}}
結束碼：全部通過 0；任一不通過 1；有評估器完全沒有結果 2（通常是 CloudWatch 還沒收進資料）
"""
import json
import statistics
import sys
from collections import defaultdict


def main(results_path, thresholds_path):
    results = json.load(open(results_path))
    thresholds = json.load(open(thresholds_path))
    by_eval = defaultdict(list)
    for r in results:
        if r.get("value") is not None:
            by_eval[r["evaluator"]].append((r["scenario"], float(r["value"])))

    code = 0
    for ev, rule in thresholds.items():
        vals = by_eval.get(ev)
        if not vals:
            print(f"MISSING {ev}: 沒有任何結果")
            code = max(code, 2)
            continue
        scores = [v for _, v in vals]
        mean, low = statistics.mean(scores), min(scores)
        worst = min(vals, key=lambda x: x[1])[0]
        fails = []
        if "mean" in rule and mean < rule["mean"]:
            fails.append(f"mean {mean:.2f} < {rule['mean']}")
        if "min" in rule and low < rule["min"]:
            fails.append(f"min {low:.2f} < {rule['min']}（最差：{worst}）")
        status = "FAIL" if fails else "PASS"
        if fails:
            code = max(code, 1)
        print(f"{status:<4} {ev:<24} n={len(scores):<3} mean={mean:.2f} min={low:.2f} {'；'.join(fails)}")
    sys.exit(code)


if __name__ == "__main__":
    main(*sys.argv[1:3])
