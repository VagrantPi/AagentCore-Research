"""LLM 評審 vs 人工標註的一致性分析。

輸入 CSV 欄位：
  session_id, human, <評審1>, <評審2>, ..., response_chars
  human 與各評審的值都是 0/1（Fail/Pass）；多級量表請先依你的標準二值化
輸出：每個評審的一致率、Cohen's kappa、混淆矩陣，以及「回覆長度」偏誤檢查
用法：python agreement.py sample.csv
"""
import csv
import sys


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa1, pb1 = sum(a) / n, sum(b) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan"), po


def main(path):
    rows = list(csv.DictReader(open(path)))
    judges = [c for c in rows[0] if c not in ("session_id", "human", "response_chars")]
    human = [int(r["human"]) for r in rows]
    lengths = [int(r["response_chars"]) for r in rows]
    median_len = sorted(lengths)[len(lengths) // 2]
    print(f"樣本數 {len(rows)}，人工判定 Pass 比例 {sum(human)/len(human):.2f}，回覆長度中位數 {median_len} 字\n")
    print(f"{'評審':<22}{'一致率':>6}{'kappa':>7}{'  TP  FP  FN  TN':>18}{'  偽陽率(短)':>10}{'  偽陽率(長)':>10}")
    for j in judges:
        pred = [int(r[j]) for r in rows]
        k, po = kappa(human, pred)
        tp = sum(h == 1 and p == 1 for h, p in zip(human, pred))
        fp = sum(h == 0 and p == 1 for h, p in zip(human, pred))
        fn = sum(h == 1 and p == 0 for h, p in zip(human, pred))
        tn = sum(h == 0 and p == 0 for h, p in zip(human, pred))

        # 長度偏誤：在「人工判定 Fail」的樣本裡，評審誤判為 Pass 的比例，短回覆 vs 長回覆
        def fpr(cond):
            idx = [i for i in range(len(rows)) if human[i] == 0 and cond(lengths[i])]
            return sum(pred[i] for i in idx) / len(idx) if idx else float("nan")
        short, long_ = fpr(lambda x: x < median_len), fpr(lambda x: x >= median_len)
        print(f"{j:<22}{po:>6.2f}{k:>7.2f}{tp:>6}{fp:>4}{fn:>4}{tn:>4}{short:>10.2f}{long_:>10.2f}")
    print("\nkappa 參考：< 0.4 差、0.4–0.6 普通、0.6–0.8 良好、> 0.8 很好（Landis & Koch 的常用分級）")


if __name__ == "__main__":
    main(sys.argv[1])
