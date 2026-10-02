# WP0 成本量測基礎

> 前置工作。目的：讓之後每個 WP 都能用同一種方法拉出**帳單數字**，而不是單價換算。
>
> 估點：2。優先序：前置（不參與排序）。前置：無。分群：A。

## 目標

1. 任何 WP 開的資源都能依 tag 從 Cost Explorer 拉出實際金額。
2. 預算警報生效，避免實驗失控。
3. 驗證 Runtime 的 `USAGE_LOGS` 真的能給出每個 session 的資源用量（這是 WP5 分攤每位使用者成本的前提）。

## 前提

| 前提 | 來源等級 | 出處 |
|---|---|---|
| Runtime 可以開啟 `USAGE_LOGS`，內容是每個 session 每秒的 vCPU-hours 和 GB-hours | `[官方已寫]`，研究庫寫成事實但從未實跑 | [06 Observability](../06-observability/README.md) |
| 服務提供的 `CPUUsed-vCPUHours` / `MemoryUsed-GBHours` metric 最多延遲 60 分鐘，而且不等於帳單 | `[官方已寫]` | 同上 |
| Cost Explorer 依 tag 分組需要先啟用 cost allocation tag，啟用後約 24 小時才會出現 | `[官方已寫]`（AWS 通用） | — |

## 步驟

1. **AWS Budgets：** 建一個每日成本預算（例如 $50 / 日），警報送到團隊信箱或 Slack。送一次測試通知確認收得到。
2. **啟用 cost allocation tag：** 在 Billing console 啟用 `wp` 和 `owner` 兩個 user-defined tag。**啟用後要等 24 小時**，所以 WP0 要最先做。
3. **寫拉帳單的腳本**（放在本目錄 `scripts/cost_by_wp.py`）：呼叫 Cost Explorer `GetCostAndUsage`，依 `wp` tag 分組，輸出每個 WP 的 UnblendedCost 和依服務的細項。輸出 CSV，讓各 WP 直接貼進回填表。
4. **測試 Runtime：** 建一個最小的 Runtime（研究庫 `01-runtime/experiments/cold-start/agent/` 的範例 agent 即可），加 tag `wp=WP0`，開啟 `USAGE_LOGS`，呼叫幾次並讓它跑 10 分鐘，然後刪除。
5. 隔天：用腳本拉 `wp=WP0` 的金額；到 CloudWatch Logs 看 `USAGE_LOGS` 的內容。

## 檢核點

| # | 檢核點 | 來源等級 | 判定 |
|---|---|---|---|
| 1 | Budgets 測試通知有收到 | — | 是 / 否 |
| 2 | 隔天 Cost Explorer 能依 `wp=WP0` 看到那個測試 Runtime 的金額 | `[官方已寫]` | 金額（USD） |
| 3 | `USAGE_LOGS` 裡有每個 session 的紀錄，欄位包含 session ID、vCPU-hours、GB-hours | `[官方已寫]`，未實證 | 貼一筆 log 樣本 |
| 4 | `USAGE_LOGS` 加總的 vCPU-hours × 單價，和 Cost Explorer 的金額差多少 | `[推測]`（研究庫說「不等於帳單」） | 差異百分比 |
| 5 | 10 分鐘閒置的 Runtime 實際被收了多少錢（驗證「閒置時記憶體照算」） | `[官方已寫]` | 金額 |

## 交付

- `scripts/cost_by_wp.py` 與使用說明。
- 本檔案下方的回填區。
- 把「怎麼拉帳單」的一段寫進 [`_template.md`](_template.md) 的「實際費用」說明（如果和模板寫的不同）。

## 關聯

- 研究庫：[06 Observability](../06-observability/README.md)（`USAGE_LOGS`、metric 延遲）、[00 總覽的定價表](../00-overview/README.md)
- 既有腳本：`01-runtime/experiments/cold-start/agent/`（最小 agent）

## 回填

（複製 [`_template.md`](_template.md) 的內容到這裡）
