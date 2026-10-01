# Web Search 的月費估算與引用檢查

說明見 [web-search-grounding.md](../../web-search-grounding.md)。

```bash
python3 test_local.py      # 引用檢查 4 個案例 + 三種成本情境
python3 cost.py --turns 1000000 --search-rate 0.2 --queries 1.5
```

撰寫時已實跑。**沒有實際呼叫過 Web Search**；價格依 2026-10 的官方定價頁。
