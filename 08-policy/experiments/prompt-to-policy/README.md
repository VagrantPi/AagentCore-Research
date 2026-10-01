# Prompt 規則改寫成 Cedar：本機驗證

說明見 [prompt-to-policy.md](../../prompt-to-policy.md#第四步在本機先驗證)。

> 這裡只在本機驗證 Cedar 語法與授權邏輯。在 AgentCore Gateway 上的實測（陣列型 claim、`tools/list` 過濾）由 [WP2](../../../91-work-packages/WP2-capability-boundary.md) 進行。

```bash
pip install cedarpy   # 撰寫時使用 4.12.1（Cedar 4.x）
python run.py
```

| 檔案 | 內容 |
|---|---|
| `schema.cedarschema` | 仿照 AgentCore 自動產生的 schema 結構，手寫的近似版本 |
| `policies.cedar` | 從 system prompt 搬過來的四條規則 |
| `bad-policy.cedar` | 反例：引用非必填欄位卻沒先 `has`，validator 應該抓出來 |
| `run.py` | schema 驗證 + 10 個授權案例 |

撰寫時已實跑：validator 對 `policies.cedar` 通過、對 `bad-policy.cedar` 報錯，10 個案例全部符合預期。
