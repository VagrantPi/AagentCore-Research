"""檢查回答有沒有遵守 Web Search 的使用規定：用到的每一筆搜尋結果，都要在輸出中保留並顯示來源連結。

做法：要求模型在回答裡用 [n] 標註引用，程式端再把 [n] 對應的 URL 附在輸出最後，
      並檢查「引用了不存在的編號」「沒有 URL 的結果被引用」這兩種情況。
"""
import re


def render(answer, results):
    """results：Web Search 回傳的 results 陣列（url、title 可能缺）"""
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
    problems, lines = [], []
    for n in cited:
        if not 1 <= n <= len(results):
            problems.append(f"引用了不存在的來源 [{n}]")
            continue
        r = results[n - 1]
        if not r.get("url"):
            problems.append(f"[{n}] 沒有 URL，無法顯示來源連結：不應作為引用依據")
            continue
        date = f"（{r['publishedDate']}）" if r.get("publishedDate") else ""
        lines.append(f"[{n}] {r.get('title') or r['url']}{date} {r['url']}")
    if not cited:
        problems.append("回答沒有標註任何來源")
    return answer + ("\n\n來源：\n" + "\n".join(lines) if lines else ""), problems
