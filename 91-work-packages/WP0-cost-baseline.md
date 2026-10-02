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

- 負責人：Kais
- 執行日期：2026-10-02
- 區域：ap-northeast-1
- 資源 tag：`wp=WP0`、`owner=kais`、`project=hyfai`
- 使用的 AWS 帳號：050571774557（公司帳號，IAM user `KaisLinCli` 加掛 [`iam/wp0-owner-policy.json`](iam/wp0-owner-policy.json)）

### 結論（三句內）

1. `USAGE_LOGS` 可用：每個 session 每秒一筆，有 session ID、vCPU-hours、GB-hours，加總和 CloudWatch metric **完全一致**，可以當費用估算與分攤到使用者的依據。
2. **閒置時記憶體照算**：每個 session 呼叫完後閒置到 15 分鐘逾時才結束，這段期間 CPU 幾乎為 0，記憶體約 1 GB 持續計費；閒置成本約占 session 費用九成。
3. 最小 agent 的 session 估算約 $0.003 / 個（含 15 分鐘閒置）；`scripts/usage_cost.py` 已能從 log 算出每個 session 的金額。

### 檢核表

| # | 檢核點 | 來源等級 | 結果 | 證據 | 對選型的影響 |
|---|---|---|---|---|---|
| 1 | `USAGE_LOGS` 有每個 session 的紀錄，欄位含 session ID、vCPU-hours、GB-hours | `[官方已寫]` | 通過 | 下方樣本；log group `/aws/vendedlogs/bedrock-agentcore/wp0-usage` | WP5 可依 session ID 分攤到使用者（session ID 要能對回使用者） |
| 2 | `USAGE_LOGS` 加總和 metric 差多少 | `[推測]` | 通過，差 0% | metric：vCPU-hours 0.011301、GB-hours 0.858831；log 加總相同 | 兩者擇一即可；metric 只到資源層級，要分攤到使用者必須用 log |
| 3 | 閒置期間 GB-hours 是否繼續累積 | `[官方已寫]` | 是 | 每個 session 記錄 910 秒 ≈ 15 分鐘閒置逾時 + 使用時間；閒置時每秒 vCPU 約 1.7e-6 小時、記憶體約 1.08 GB | 必須縮短閒置逾時或主動 `StopRuntimeSession`，WP1 要納入 |
| 4 | `usage_cost.py` 能算出每個 session 的估算金額 | — | 通過 | 下方 CSV | 之後各 WP 共用 |

`USAGE_LOGS` 樣本（一筆 = 一個 session 的一秒）：

```json
{"resource_arn": "arn:aws:bedrock-agentcore:ap-northeast-1:050571774557:runtime/wp0_min-HsBwOc6VWU",
 "event_timestamp": 1790912445988,
 "resource": {"cloud.provider": "aws", "service.name": "AgentCore.Runtime", "cloud.region": "ap-northeast-1"},
 "attributes": {"account.id": "050571774557", "time_elapsed_seconds": 1.0, "agent.name": "wp0_min", "region": "ap-northeast-1",
                "session.id": "wp0-session-3-12E26BF9616640039AEDAE9AD13D7A52",
                "resource.id": "arn:aws:bedrock-agentcore:ap-northeast-1:050571774557:runtime/wp0_min-HsBwOc6VWU/runtime-endpoint/DEFAULT"},
 "metrics": {"agent.runtime.memory.gb_hours.used": 0.000196962254825, "agent.runtime.vcpu.hours.used": 0.000329480833333}}
```

其他觀察：

- **log 延遲：** 03:41 第一次呼叫，03:58 才出現第一筆 log（session 約 03:56 閒置逾時結束），但這時還沒到齊（見下一點）。**費用一律在 session 結束 1 小時後再算。**
- **資料到齊要約 1 小時：** session 結束約 14 分鐘後查，log 只到約 75%、metric 約 80%；約 1 小時後兩者才完全一致。
- **metric 的維度：** 要帶 `Service=AgentCore.Runtime` + `Resource=<runtime ARN>`（或 `Service` + `Name=<agent>::DEFAULT`），只帶 `Resource` 查不到資料。
- **Code Interpreter 也有 `USAGE_LOGS`**（`service.name` 為 `AgentCore.CodeInterpreter`，欄位 `codeInterpreter.vcpu.hours.used`、`codeInterpreter.memory.gb_hours.used`），同一支腳本可用。
- **呼叫延遲（WP1 參考）：** 從台灣呼叫，每個新 session 第一次約 0.85–0.95 秒，同 session 第二次約 0.65 秒。第一次呼叫時回應的 `boot_age_s` 已約 32 秒，VM 在呼叫前就開好了，像是建立 runtime 後預先開好的；WP1 要確認這是不是預喚醒池。

### 實際費用

| 資源 | 用量（vCPU-hours、GB-hours、次數、token） | 用量來源 | 單價（官網，2026-09-30 查證） | 估算金額（USD） |
|---|---|---|---|---|
| Runtime `wp0_min`，3 個 session（各 2 次呼叫 + 15 分鐘閒置） | 0.011301 vCPU-h、0.858831 GB-h | `USAGE_LOGS`，與 metric 一致 | $0.0895 / vCPU-h、$0.00945 / GB-h | 0.009127 |

```
resource,session_id,seconds,vcpu_hours,gb_hours,est_usd
wp0_min,wp0-session-1-6E32C1F787474C299D63A95083C2F4F6,910,0.003871,0.279610,0.002989
wp0_min,wp0-session-2-C5C155C5456B4AE8B7B28538EF9F0F5C,918,0.003704,0.286571,0.003040
wp0_min,wp0-session-3-12E26BF9616640039AEDAE9AD13D7A52,910,0.003726,0.292650,0.003099
（合計）,,,,,0.009127
```

- ECR 儲存（一個 python:3.12-slim 的小 image）、CloudWatch Logs 的寫入量很小，未列。

### 否定項目的替代方案

| 被否定的檢核點 | 替代方案 | 多出的成本或限制 |
|---|---|---|
| （原）Budgets、Cost Explorer 依 tag 拉帳單 | 用量 × 官網單價估算（本 WP） | 拿不到稅、折扣、免費額度等帳單層級的差異；沒有預算警報 |

### 清理確認

- [ ] Runtime / Harness 已刪除 — **保留** `wp0_min-HsBwOc6VWU`、ECR `wp-agentcore-coldstart`、role `/wp/wp0-runtime-exec`、`USAGE_LOGS` 投遞（delivery source `wp0-usage-src`、destination `wp0-usage-dst`、log group `/aws/vendedlogs/bedrock-agentcore/wp0-usage`，保留 14 天），給 WP5、WP1 沿用
- [x] Browser session 已停止、profile 已刪除（未使用）
- [x] Gateway、Policy 已刪除（未使用）
- [x] Memory 已刪除（未使用）
- [x] VPC endpoint、NAT 已刪除（未使用）
- [ ] 隔天確認沒有仍在跑的資源 — WP1 結束時一起確認；`KaisLinCli` 的 `wp0-account-owner` 也在那時移除

### 要更正研究庫的段落

| 檔案:行號 | 原本寫的 | 實測結果 |
|---|---|---|
| `06-observability/README.md:67` | `CPUUsed-vCPUHours`、`MemoryUsed-GBHours`「接近帳單上的數字……不等於實際帳單」 | 與 `USAGE_LOGS` 加總完全一致；和帳單的差異無法驗證（拿不到帳單） |
| `06-observability/README.md:75` | `USAGE_LOGS`「官方文件的說法，尚未實測」 | 已實測，見本檔 |
