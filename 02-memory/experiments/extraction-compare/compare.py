"""比較不同萃取策略產生的長期記憶 record 品質。

輸入：records.json
  {"<策略名稱>": [{"text": "...", "namespace": "..."}...], ...}
  （由 run.py 從 ListMemoryRecords 匯出；也可以手動整理）
對照：expectations.json
  {"must_have": [["關鍵字A", "關鍵字B"], ...],   # 每一組代表一個「應該被記住的事實」，record 含任一關鍵字即算命中
   "must_not_have": ["VIP", "免運", ...],         # 不該被記住的內容（注入、權限宣稱、敏感資料）
   "noise": ["你好", "謝謝", ...],                # 客套話、無資訊量的內容
   "stale": ["住在台北", ...],                    # 已經被後來的對話推翻、不該再當成現況的事實
   "language": "zh"}                              # 期望的 record 語言
輸出：每個策略的 record 數、事實召回、污染、噪音、重複、語言一致性
"""
import difflib
import json
import re
import sys
from itertools import combinations

CJK = re.compile(r"[一-鿿]")
LATIN = re.compile(r"[A-Za-z]")


def lang_of(text):
    c, l = len(CJK.findall(text)), len(LATIN.findall(text))
    if c + l == 0:
        return "other"
    return "zh" if c >= l * 0.5 else "en"  # 中文字資訊密度高，給較低門檻


def near_dups(texts, threshold=0.8):
    """字面相似度；「吃素」和「是素食者」這種語意重複抓不到，需要 embedding 或人工檢查。"""
    pairs = []
    for (i, a), (j, b) in combinations(enumerate(texts), 2):
        if difflib.SequenceMatcher(None, a, b).ratio() >= threshold:
            pairs.append((i, j))
    return pairs


def score(records, exp):
    texts = [r["text"] for r in records]
    hit = sum(any(any(k in t for k in group) for t in texts) for group in exp["must_have"])
    polluted = [t for t in texts if any(k in t for k in exp["must_not_have"])]
    noisy = [t for t in texts if any(k in t for k in exp["noise"]) and len(t) < 30]
    stale = [t for t in texts if any(k in t for k in exp.get("stale", []))]
    dups = near_dups(texts)
    langs = [lang_of(t) for t in texts]
    lang_ok = sum(l == exp["language"] for l in langs)
    return {
        "records": len(texts),
        "recall": f"{hit}/{len(exp['must_have'])}",
        "polluted": len(polluted),
        "noise": len(noisy),
        "stale": len(stale),
        "dups": len(dups),
        "lang_ok": f"{lang_ok}/{len(texts)}" if texts else "-",
        "avg_chars": round(sum(map(len, texts)) / len(texts)) if texts else 0,
        "_polluted_examples": polluted[:3],
    }


def main(records_path, exp_path):
    data = json.load(open(records_path, encoding="utf-8"))
    exp = json.load(open(exp_path, encoding="utf-8"))
    cols = ["records", "recall", "polluted", "stale", "noise", "dups", "lang_ok", "avg_chars"]
    print(f"{'策略':<20}" + "".join(f"{c:>10}" for c in cols))
    results = {}
    for name, recs in data.items():
        s = results[name] = score(recs, exp)
        print(f"{name:<20}" + "".join(f"{str(s[c]):>10}" for c in cols))
    for name, s in results.items():
        for t in s["_polluted_examples"]:
            print(f"  ⚠ {name} 被污染：{t}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
