# OpenAPI → Gateway 工具的事前檢查

說明見 [api-to-tools.md](../../api-to-tools.md#事前檢查openapi-lint)。

```bash
python3 lint.py sample-internal-api.json --target OrderApi   # 有 ERROR 時結束碼為 1，可以放進 CI
```

- 只用 Python 標準函式庫（YAML 規格需要 `pyyaml`）。
- `sample-internal-api.json` 刻意放了幾個問題：缺 `operationId`、`oneOf`、過長的工具名稱、缺說明、非 JSON 的 content type。
- 檢查規則依據 2026-09 的官方限制；「工具名稱 64 字元」與 token 估算是經驗值，不是官方限制。
