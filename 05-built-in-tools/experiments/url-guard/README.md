# 瀏覽器 agent 的導覽白名單檢查

說明見 [browser-reliability-security.md](../../browser-reliability-security.md#防範網頁內容的-prompt-injection)。

```bash
python3 test_local.py
```

12 個案例（字串包含、`endswith`、query 夾帶、userinfo、非 https、同形異義字…），撰寫時全部通過。只用 Python 標準函式庫。
