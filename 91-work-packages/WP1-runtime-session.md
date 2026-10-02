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
9. **成本情境：** 模擬 20 位使用者（20 個 session ID），每位每 5 分鐘呼叫一次、持續 2 小時，idle 設 30 分鐘。用 WP0 的方法估算費用，再換算成「100 位使用者、每人在線 2 小時」的月費。

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
| 10 | 20 位使用者 2 小時的估算費用；換算 100 位使用者月費 | 成本 | USD |
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

> **部分回填（2026-10-02）：** 除了 #10、#11 都跑完了，全部是 PUBLIC。#11（VPC 組）等 B 在 WP3 建好 VPC；#10（成本情境）要實測：用 `USAGE_LOGS` 量實際用量，全程約 3.5 小時，尚未跑。

- 負責人：kais
- 執行日期：2026-10-02
- 區域：`ap-northeast-1`
- 資源 tag：`wp=WP1`、`owner=kais`、`project=hyfai`
- 使用的 AWS 帳號：`050571774557`（execution role 沿用 WP0 的 `wp/wp0-runtime-exec`；image `wp-agentcore-coldstart:wp1`、`:wp1-big`、`:wp1-ss`、`:wp1-busy`）

### 結論（三句內）

1. **「一人一實體」可行，但 agent 有兩條硬性規定：** handler 必須 async 或多執行緒（同一 session 3 個並行請求才會 9/9 成功、無 409）；請求只要超過閒置逾時，`/ping` 就得回 `HealthyBusy`，否則 session 會被砍。
2. **V1 + 小 image + 預喚醒就夠了：** 預喚醒後的首句 p50 170–196 ms；池子（約 15 台）用光後，V1 small 的真冷啟動約 3.6 s，1 GB 約 17.8 s；V2 不論情況都在 2 秒左右，只有「大 image + 突發流量」才值得 V2。
3. **部署要用固定版本的 endpoint：** 透過 DEFAULT 恢復時，更新版本會清空 session storage；固定版本的 endpoint 不會。

### 檢核表

| # | 檢核點 | 來源等級 | 結果 | 證據 | 對選型的影響 |
|---|---|---|---|---|---|
| 1 | V1 冷啟動 p50 / p90 | `[推測]` | 從池子：small 561 / 673 ms、1 GB 559 / 616 ms。池子用光後的真冷啟動：small 3617–3762 / 3658–4177 ms、1 GB 17828 / 17888 ms | `results.csv`、`burst.csv`；[結果表](../01-runtime/experiments/cold-start/README.md#結果) | 池子約 15 台（`boot_age_s` 中位數 36 s / 97 s）。image 大小只在池子用光後才有影響，而且影響很大：image 要保持小 |
| 2 | V2 冷啟動 p50 / p90，與 V1 的差距 | `[推測]` | small 1898 / 2313 ms；1 GB 1861 / 2260 ms；burst 60 個也在 2130 ms 左右 | 同上 | 池子裡比 V1 慢約 1.3 s；池子用光後比 V1 small 快約 1.7 s、比 V1 1 GB 快約 15.7 s。小 image 下差距小於 2 秒，依判定不值得 V2 的限制 |
| 3 | V2 多台實例的 `boot_token` 是否相同 | `[官方已寫]` | 通過：small 20 次裡 19 次相同、big 20 次全部相同；V1 40 次全部不同 | `results.csv` 的 `boot_token` | 若用 V2，啟動階段的亂數、ID 一律改到 handler 裡產生 |
| 4 | 同一 session 的暖機延遲 p50 | `[官方已寫]` | 190–217 ms | `results.csv` 的 `warm_ms` | 呼叫端在台灣不是同區域，大多是網路來回 |
| 5 | 閒置逾時後再呼叫：記憶體狀態消失、session storage 保留 | `[官方已寫]` | 通過：閒置 90 秒（逾時 60 秒）後換了一台 VM，記憶體是空的，檔案還在；`StopRuntimeSession` 後再恢復也一樣 | `storage.csv` | 工作區放 session storage，記憶體只當快取 |
| 6a | 更新 runtime 版本後，session storage 清空 | `[官方已寫]` | 通過：停止 → 更新到 version 2 → 透過 DEFAULT 恢復，檔案被清空 | `storage.csv` | 透過 DEFAULT 部署會丟使用者工作區 |
| 6b | Endpoint 固定指向舊版本時，session storage 清空 | `[矛盾]` | **不清空**：endpoint 固定在 version 2，runtime 更新到 version 3 後透過它恢復，檔案還在，請求仍跑在 version 2 | `storage.csv` | 用固定版本的 endpoint 部署，就不用「先備份工作區再部署」；切換 endpoint 到新版本時才會清空，這一步沒有測 |
| 7 | 預喚醒後的首句延遲是否接近暖機 | `[推測]` | 通過：真正請求 p50 V1 170 ms、V2 196 ms；80 次全部落在預喚醒開的那台 VM | `prewarm.csv` | 採用「開聊天室時送空請求」；預喚醒請求本身不等回應，即使冷啟動還沒結束也不會撞 409 |
| 8 | 單 session 3 個並行請求：全部成功、`/ping` 不被卡 | `[推測]` | 通過（多執行緒版）：9/9 成功、延遲都是 20.2–20.3 s、同一台 VM、每個請求期間收到 10 次 `/ping`。阻塞版：9/9 成功但排隊成 20/40/60 s、`/ping` 0 次；**有 1 次第 3 個請求花 87 s 且換了 `boot_token`**（process 被重啟或換 VM，記憶體狀態會遺失） | `concurrent.csv` | 一人一 session、多聊天室共用可行；agent 的 handler 必須 async 或多執行緒 |
| 8′ | 阻塞版本是否在閒置逾時後被砍 | `[官方已寫]` | 通過，而且範圍更大：180 秒的請求（閒置逾時 60 秒）在阻塞版（156.7 s）和**回 `Healthy` 的多執行緒版**（246.8 s）都收到 `RuntimeClientError`、session 被終止；處理中回 `HealthyBusy` 的版本 180.2 s 成功 | `concurrent.csv` | 長任務一定要回 `HealthyBusy`。正式環境閒置逾時預設 15 分鐘，所以超過 15 分鐘的請求適用 |
| 9 | Session 建立速率上限 | `[矛盾]` | 沒有碰到上限：100 個新 session 在約 1 秒內送出，0 次 throttle | `burst.csv` | 1.6/s 不成立；25/s 是持續速率還是上限，這個規模分辨不出來。不影響選型 |

- 平台在 handler 忙碌時約每 2 秒打一次 `/ping`。
- 阻塞版那次 87 s、換了 `boot_token`：和 8′ 一致，阻塞約 60 秒、超過閒置逾時後 VM 被換掉。
- 8′ 每組只跑 1 次（回 `Healthy` 的那組前後被砍 2 次）。這批 runtime 的閒置逾時是 60 秒，沒有用預設的 15 分鐘重跑。

### 實際費用

| 資源 | 用量（vCPU-hours、GB-hours、次數、token） | 用量來源（`USAGE_LOGS`、metric、自己計數） | 單價（官網，標日期） | 估算金額（USD） |
|---|---|---|---|---|
| Runtime（7 個 wp1_ runtime） | 約 470 個 session，每個活幾秒到約 4 分鐘；burst 的 280 個沒有主動停止，閒置 60 秒後回收 | 自己計數；這批 runtime 沒開 `USAGE_LOGS` | $0.0895 / vCPU-hour、$0.00945 / GB-hour | 遠低於 1（未精算） |
| ECR | 約 1.1 GB（`:wp1`、`:wp1-big`、`:wp1-ss`、`:wp1-busy`，小的幾乎不佔空間） | 自己計數 | — | 每月約 0.1 |

### 否定項目的替代方案

| 被否定的檢核點 | 替代方案 | 多出的成本或限制 |
|---|---|---|
| #2 小 image 下 V2 值得它的限制 | 用 V1 + 小 image + 預喚醒 | 預喚醒那一次請求的費用；session 提早開始計費約幾秒；突發流量用光池子時首句約 3.6 s |
| 8′ 回 `Healthy` 的長請求不會被砍 | 處理中 `/ping` 回 `HealthyBusy` | agent 要自己追蹤處理中的請求數 |

### 清理確認

- [ ] Runtime 已刪除——**刻意保留**給 #11（VPC 組要跟 PUBLIC 比）與 #10：`wp1_cs_v1_img_pub`、`wp1_cs_v2_img_pub`、`wp1_cs_v1_bigimg_pub`、`wp1_cs_v2_bigimg_pub`、`wp1_cs_v1_img_pub_blk`、`wp1_cs_v1_img_pub_busy`、`wp1_ss_v1_img_pub`（含 endpoint `wp1_pinned`）。沒有 session 時不計運算費
- [ ] ECR image `wp-agentcore-coldstart:wp1`、`:wp1-big`、`:wp1-ss`、`:wp1-busy` 待 WP1 全部跑完再刪
- [ ] 隔天確認 Runtime 沒有仍在跑的 session

### 要更正研究庫的段落

| 檔案:行號 | 原本寫的 | 實測結果 |
|---|---|---|
| `01-runtime/README.md:12`、`:58` | V2 冷啟動時間穩定 | 穩定是真的（約 2 s）；但 V1 池子裡只要 0.56 s，V2 只在池子用光後才比較快 |
| `01-runtime/README.md:216`、`:217` | V1 隨 image 大小變動；image 大小對 V1 影響明顯 | V1 有約 15 台的預熱池，池子裡 image 大小沒影響；池子用光後 small 3.6 s、1 GB 17.8 s |
| `01-runtime/README.md` 長時間與非同步任務一節 | 阻塞的 handler 會卡住 `/ping`，15 分鐘後被當閒置砍掉 | 不只阻塞：`/ping` 照常回 `Healthy` 的請求超過閒置逾時也會被砍，只有 `HealthyBusy` 能保住 |
| `01-runtime/coding-agent-architecture.md` 更新版本會清空工作區一節 | endpoint 固定舊版本時會不會清空不明 | 不會清空；用固定版本的 endpoint 部署即可保住工作區 |
| `01-runtime/README.md` 配額 | session 建立速率 1.6/s 或 25/s | 100 個在約 1 秒內送出都沒被 throttle |
| `01-runtime/README.md:202` | 沒設定 `requireMMDSV2` 的 runtime 呼叫會失敗 | `CreateAgentRuntime` 新建的 runtime 預設就是 `requireMMDSV2: true` |
| `01-runtime/README.md:210` 一節 | 冷啟動沒有數字 | 補上本次結果，連到實驗 README |
