# WP0 成本量測基礎

> 前置工作。目的：讓之後每個 WP 都能用同一種方法算出**實際用量換算的費用**，而且算法一致、可以重現。
>
> 估點：2。優先序：前置（不參與排序）。前置：無。分群：A。

## 為什麼不用帳單（2026-10-02 確認）

公司 AWS Organizations 的管理帳號（`070221791376`）有一條 SCP（`p-b6ce2j3k`），**明確禁止**實驗帳號 `050571774557` 使用 Budgets 與 Cost Explorer。SCP 的拒絕高於任何 IAM 權限，這個權限拿不到。所以：

- **拿不到帳單數字**，也不能依 tag 拉金額、不能設預算警報。
- 成本一律改成「**實際用量 × 官網單價**」，標「估算」。用量來自 AgentCore 自己吐的 log 與 metric，不是猜的。
- 資源仍然要加 tag（見下方），日後管理帳號若願意提供帳單，可以回頭對數字。

## 目標

1. 驗證 Runtime 的 `USAGE_LOGS` 真的能給出每個 session 的資源用量（這是 WP5 分攤每位使用者成本的前提）。
2. 寫好依用量估算費用的腳本，讓之後每個 WP 用同一套算法。
3. 沒有預算警報，改用「每包結束清資源 + 清理確認」兜底。

## 資源 tag 規則（所有 WP 都遵守）

每個建立的資源都加這三個 tag：

| Key | Value | 說明 |
|---|---|---|
| `wp` | `WP0`…`WP7` | 屬於哪個工作包 |
| `owner` | 負責人，例如 `kais`、`roman` | 誰建的、誰要清 |
| `project` | `hyfai` | 公司規定，所有新開的服務都要有 |

資源名稱用 `wp-`（或 `wp0_` 這類，視服務的命名規則）開頭，IAM 角色建在 `/wp/` 路徑下。

## 前提

| 前提 | 來源等級 | 出處 |
|---|---|---|
| Runtime 可以開啟 `USAGE_LOGS`，內容是每個 session 每秒的 vCPU-hours 和 GB-hours | `[官方已寫]`，研究庫寫成事實但從未實跑 | [06 Observability](../06-observability/README.md) |
| 服務提供的 `CPUUsed-vCPUHours` / `MemoryUsed-GBHours` metric 最多延遲 60 分鐘，而且不等於帳單 | `[官方已寫]` | 同上 |
| Runtime v1、Code Interpreter、Browser 單價：$0.0895 / vCPU-hour、$0.00945 / GB-hour | `[官方已寫]` | [00 總覽的定價表](../00-overview/README.md) |

## 步驟

1. **測試 Runtime：** 部署研究庫 `01-runtime/experiments/cold-start/agent/` 的最小 agent，加上三個 tag，開啟 `USAGE_LOGS` 投遞到 CloudWatch Logs。
2. 呼叫幾個 session，之後讓它閒置到 session 逾時（預設 15 分鐘）。
3. 看 `USAGE_LOGS` 的內容；和 `AWS/Bedrock-AgentCore` 的 `CPUUsed-vCPUHours`、`MemoryUsed-GBHours` 對照。
4. 寫估算腳本 `scripts/usage_cost.py`：讀 `USAGE_LOGS`，依 session 加總 vCPU-hours、GB-hours，乘上單價，輸出 CSV。
5. 刪除所有資源。

## 檢核點

| # | 檢核點 | 來源等級 | 判定 |
|---|---|---|---|
| 1 | `USAGE_LOGS` 裡有每個 session 的紀錄，欄位包含 session ID、vCPU-hours、GB-hours | `[官方已寫]`，未實證 | 貼一筆 log 樣本 |
| 2 | `USAGE_LOGS` 加總和 `CPUUsed-vCPUHours` / `MemoryUsed-GBHours` metric 差多少 | `[推測]` | 差異百分比 |
| 3 | session 閒置期間，記憶體的 GB-hours 是否繼續累積（驗證「閒置時記憶體照算」） | `[官方已寫]` | 是 / 否；閒置 15 分鐘的估算金額 |
| 4 | `usage_cost.py` 能從 `USAGE_LOGS` 算出每個 session 的估算金額 | — | CSV |

## 同事的實驗身分

同事的受限 IAM 身分範本見 [`iam/`](iam/)。Cost Explorer、Budgets 在這個帳號被 SCP 擋住，任何人都用不到，所以範本裡也不給。

## 交付

- `scripts/usage_cost.py` 與使用說明。
- 本檔案下方的回填區。
- [`_template.md`](_template.md) 的「費用」說明改成估算的做法。

## 關聯

- 研究庫：[06 Observability](../06-observability/README.md)（`USAGE_LOGS`、metric 延遲）、[00 總覽的定價表](../00-overview/README.md)
- 既有腳本：`01-runtime/experiments/cold-start/agent/`（最小 agent）

## 回填

（複製 [`_template.md`](_template.md) 的內容到這裡）
