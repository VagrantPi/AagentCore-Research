# CI 門檻與 code-based 評估器

說明見 [test-pyramid-ci.md](../../test-pyramid-ci.md)。

```bash
python3 test_local.py
```

| 檔案 | 內容 |
|---|---|
| `code_evaluator.py` | Code-based 評估器的 Lambda handler：禁止的工具、回覆中的 email / 手機號碼 |
| `gate.py` | CI 門檻：依評估器設定 mean / min 門檻；結束碼 0 通過、1 分數不足、2 缺結果 |
| `test_local.py` | 用合成的 span 與結果做本機測試 |

- 只用 Python 標準函式庫；撰寫時本機測試全部通過。
- **沒有在 AWS 上跑過。** span 的欄位名稱（`gen_ai.tool.name` 等）依框架而異，接真實 agent 前要先撈一份真的 `sessionSpans` 對照。
