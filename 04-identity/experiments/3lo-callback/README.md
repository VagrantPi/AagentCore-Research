# 3LO callback 端點的參考實作

說明見 [3lo-reference.md](../../3lo-reference.md#你的-callback-端點)。

```bash
python3 test_local.py
```

- 只用 Python 標準函式庫（WSGI）。AgentCore 的 `CompleteResourceTokenAuth` 以假的 client 代替。
- 6 個案例：沒登入、連結被轉傳給別人、正常完成、重放、被轉傳過的連結作廢、過期。撰寫時全部通過。
- 正式環境要把記憶體儲存換成有 TTL 的共享儲存，並把假的 client 換成 `boto3.client("bedrock-agentcore")`。
