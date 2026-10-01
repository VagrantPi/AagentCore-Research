# 萃取品質比較

說明見 [extraction-tuning.md](../../extraction-tuning.md#品質比較的方法)。

| 檔案 | 內容 | 狀態 |
|---|---|---|
| `conversations.json` | 三個 session 的測試對話，埋了事實、寒暄、注入、個資、更正、中英混雜 | — |
| `expectations.json` | 各指標的判斷依據 | — |
| `compare.py` | 計算召回、污染、過時、噪音、重複、語言一致性 | 本機實跑過 |
| `demo-records.json` | **手寫的假想萃取結果**，只用來驗證 `compare.py` | 不是 AgentCore 的輸出 |
| `run.py` | 在 AWS 建立 built-in 與 override 策略、灌對話、匯出 record | **沒有實跑過**；參數已對 botocore 1.43.105 離線驗證 |

```bash
python3 compare.py demo-records.json expectations.json
```
