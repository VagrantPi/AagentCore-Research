# Memory 月費與檢索速率估算

說明見 [read-write-cost.md](../../read-write-cost.md#成本估算)。

```bash
python3 cost.py                          # Strands 預設（每則訊息一個 event）
python3 cost.py --batch                  # 開啟 batching
python3 cost.py --mau 200000 --batch --storage-rate 0.25
```

寫入次數依 Strands `AgentCoreMemorySessionManager`（bedrock-agentcore 1.24.0）的原始碼與模擬測試；價格依 2026-10 的官方定價頁。
