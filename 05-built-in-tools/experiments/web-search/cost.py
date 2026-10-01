"""Web Search 月費估算：$7 / 1,000 次查詢（依官方定價頁，2026-10）。

變因：
  --turns         每月使用者回合數
  --search-rate   有多少比例的回合會觸發搜尋（模型自己決定，或由你的路由規則決定）
  --queries       每次觸發平均送出幾個查詢（模型常會換關鍵字重查）
  --cache-hit     重複查詢命中快取的比例（使用條款只禁止「大量」儲存，短期快取屬灰色地帶）
Gateway 的工具呼叫費 $0.005 / 1,000 次另計，金額相對很小。
"""
import argparse

ap = argparse.ArgumentParser()
ap.add_argument("--turns", type=float, default=1_000_000)
ap.add_argument("--search-rate", type=float, default=0.6)
ap.add_argument("--queries", type=float, default=2.0)
ap.add_argument("--cache-hit", type=float, default=0.0)
a = ap.parse_args()

queries = a.turns * a.search_rate * a.queries * (1 - a.cache_hit)
search = queries / 1000 * 7
gw = queries / 1000 * 0.005
peak_tps = queries / (30 * 86400) * 5
print(f"查詢 {queries:,.0f} 次／月：Web Search ${search:,.0f} + Gateway ${gw:,.2f}；"
      f"每回合平均 ${search / a.turns:.4f}；尖峰約 {peak_tps:.1f} TPS（預設 10 TPS）")
