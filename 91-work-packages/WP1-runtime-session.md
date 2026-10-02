# WP1 Runtime 冷啟動與「一人一實體」

> 回答：microVM 撐不撐得住對話體驗？V2 平台值不值得它的限制？「一位使用者的多個聊天室共用一台 microVM」可不可行？
>
> 估點：5。優先序：4（風險中、價值高）。前置：WP0。分群：A。

## 目標

拿到 V1 / V2 的冷啟動實際毫秒數，驗證 session 生命週期的行為和研究庫寫的一致，並確認單一 session 能承受多個聊天室的並行請求。

## 前提

| 前提 | 來源等級 | 出處 |
|---|---|---|
| 官方沒有公布冷啟動數字 | `[推測]` | [01 Runtime：冷啟動與效能](../01-runtime/README.md#冷啟動與效能) |
| 同一個 session ID 的請求會落到同一台 microVM；閒置逾時（預設 15 分鐘）或 8 小時到期後，再呼叫會開新 VM | `[官方已寫]` | [01 Runtime：Session 模型](../01-runtime/README.md#session-模型與生命週期) |
| V2 從快照還原，所有實例會拿到相同的啟動狀態（亂數、UUID 會重複） | `[官方已寫]`，未實證 | [01 Runtime：V1 vs V2](../01-runtime/README.md#平台版本v1-vs-v2) |
| Session storage 在停止再恢復後保留；更新 runtime 版本後會清空 | `[官方已寫]` | [01 Runtime：狀態要存在哪一層](../01-runtime/README.md#狀態要存在哪一層) |
| Endpoint 固定指向舊版本時，session storage 會不會清空 | `[矛盾]`（官方沒說明） | [coding-agent-architecture.md](../01-runtime/coding-agent-architecture.md#更新版本會清空工作區因應方案) |
| Session 建立速率上限 1.6/s 還是 25/s | `[矛盾]` | [01 Runtime 配額](../01-runtime/README.md) |
| 阻塞的 handler 會卡住 `/ping`，15 分鐘後被當閒置砍掉 | `[官方已寫]` | [01 Runtime：長時間與非同步任務](../01-runtime/README.md#長時間與非同步任務) |
| 「開聊天室時先送空請求預喚醒」能把首句延遲壓到暖機等級 | `[推測]`（討論中的設計） | — |

## 步驟

1. 用既有的 [`01-runtime/experiments/cold-start/bench.py`](../01-runtime/experiments/cold-start/bench.py)（已本機驗證、**從未在 AWS 跑**）。矩陣縮小成 4 組：V1 container、V2 container，各一組 PUBLIC 和 VPC。每組 20 次試驗。區域用東京（`ap-northeast-1`）。
2. 把 agent 的 image 加大到約 1 GB（塞一個無用的大檔案），再跑一次 V1 和 V2，看 image 大小的影響。
3. 用同一個 session ID 連打 3 次，記錄暖機延遲。
4. 把 `idleRuntimeSessionTimeout` 設成 60 秒，在 VM 裡寫一個檔案到記憶體和 session storage，等 90 秒再呼叫，檢查哪個還在。
5. 部署新版本 runtime（改一行程式碼），再呼叫同一個 session，檢查 session storage 是否清空。再做一次，但這次 endpoint 固定指向舊版本。
6. **並行測試：** 在 agent 裡用 async handler，同時送 3 個各需要 20 秒的請求（模擬 3 個聊天室），看是否都成功、`/ping` 有沒有被卡、有沒有 409。再故意改成同步阻塞的 handler 對照。
7. **預喚醒測試：** 先送一個空 payload 的請求，3 秒後送真正的請求，記錄第二個請求的延遲。
8. **速率測試：** 1 秒內用 30 個不同的 session ID 發請求，看第幾個開始被限流。
9. **成本情境：** 模擬 20 位使用者（20 個 session ID），每位每 5 分鐘呼叫一次、持續 2 小時，idle 設 30 分鐘。隔天用 WP0 的腳本拉帳單，再換算成「100 位使用者、每人在線 2 小時」的月費。

## 檢核點

| # | 檢核點 | 來源等級 | 判定 |
|---|---|---|---|
| 1 | V1 冷啟動 p50 / p90（小 image、約 1 GB image 各一） | `[推測]` | 毫秒 |
| 2 | V2 冷啟動 p50 / p90，與 V1 的差距 | `[推測]` | 毫秒；差距小於 2 秒就不值得 V2 的限制 |
| 3 | V2 多台實例的 `boot_token` 是否相同 | `[官方已寫]`，未實證 | 相同＝啟動階段的亂數必須改到 handler 裡產生 |
| 4 | 同一 session 的暖機延遲 p50 | `[官方已寫]` | 毫秒 |
| 5 | 閒置逾時後再呼叫：記憶體狀態消失、session storage 保留 | `[官方已寫]` | 是 / 否 |
| 6a | 更新 runtime 版本後，session storage 清空 | `[官方已寫]` | 是 / 否 |
| 6b | Endpoint 固定指向舊版本時，session storage 清空 | `[矛盾]` | 是 / 否 |
| 7 | 預喚醒後的首句延遲是否接近暖機延遲 | `[推測]` | 毫秒 |
| 8 | 單 session 3 個並行請求：全部成功、`/ping` 不被卡 | `[推測]` | 是 / 否；阻塞版本是否 15 分鐘後被砍 |
| 9 | Session 建立速率上限 | `[矛盾]` | 每秒幾個 |
| 10 | 20 位使用者 2 小時的實際帳單；換算 100 位使用者月費 | 成本 | USD |
| 11 | VPC 模式比 PUBLIC 多出的冷啟動時間 | `[官方已寫]`（官方只說「可能增加」） | 毫秒 |

## 判定對選型的影響

- 檢核點 1、7 決定「預喚醒」夠不夠，還是必須上 V2。
- 檢核點 8 決定「一人一實體」能不能直接做，還是每個聊天室一定要各自一個 session。
- 檢核點 6b 決定部署流程要不要配合「先備份工作區再部署」。
- 檢核點 10 和 WP6、WP7 的數字放進決策矩陣。

## 交付

- `bench.py` 的 `results.csv`，回填到 [`cold-start/README.md`](../01-runtime/experiments/cold-start/README.md) 的結果表。
- 本檔案下方的回填區。
- 要更正的研究庫段落列在回填區最後一節。

## 關聯

- 研究庫：[01 Runtime](../01-runtime/README.md)、[coding-agent-architecture.md](../01-runtime/coding-agent-architecture.md)、[instances-multi-agent.md](../01-runtime/instances-multi-agent.md)
- 既有腳本：[`01-runtime/experiments/cold-start/`](../01-runtime/experiments/cold-start/)（`bench.py`、`agent/`、README 有 Q1–Q6 的設計）

## 回填

（複製 [`_template.md`](_template.md) 的內容到這裡）
