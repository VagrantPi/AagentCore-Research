# Memory 多租戶隔離：後端參考實作

說明見 [multi-tenant-isolation.md](../../multi-tenant-isolation.md#第-1-層後端推導身分)。

```bash
python3 test_local.py
```

- `guard.py`：從已驗證的 JWT 推導 actorId（租戶前綴、拒絕 `/` 與 `:`）、組 namespace、刪除一個使用者的全部資料。
- 用假的 client 測試 9 個案例，撰寫時全部通過；呼叫 AWS 用到的參數已對 botocore 1.43.105 的 model 離線驗證。
- 假的 client 沒有模擬分頁、權限、非同步萃取；正式使用要補上 `nextToken` 分頁。
- **將由 [WP5](../../../91-work-packages/WP5-user-state-isolation.md) 改成真的 AWS client 實測**，IAM policy 範本放在 `aws/` 子目錄。
