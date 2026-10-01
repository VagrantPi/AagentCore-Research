# 延伸：Memory 在 Runtime session 中的讀寫模式與成本

> 接續 [02-memory](README.md#值得注意的配額) 與 [00 延伸：Harness vs Runtime](../00-overview/harness-vs-runtime.md)。這篇整理：一輪對話實際會寫幾個 event、檢索幾次；這些數字怎麼換算成月費和檢索速率；以及 Harness 的自動讀寫和自己控制之間怎麼取捨。
>
> 資料查核日期：2026-10-01。標示「推論」的部分是官方文件沒有明說、由我推導的。
>
> 每輪的 API 呼叫次數來自 **Strands 的 `AgentCoreMemorySessionManager` 原始碼與模擬測試**（bedrock-agentcore 1.24.0、strands-agents 1.57.1；用假的 botocore 計數，**沒有呼叫 AWS**）。成本估算工具：[experiments/cost-model](experiments/cost-model/)（已實跑）。

## 結論先講

- **短期記憶通常是最貴的一項，不是長期記憶。** 一次 `CreateEvent` 呼叫算一個計費 event，而 Strands 預設**每則訊息就呼叫一次**：一般回合 2 次，帶一次工具呼叫的回合 5 次。
- **開啟 `batch_size` 能把每輪的寫入降到約 2 次**，短期記憶費用少一半以上。代價是程序意外結束時，還沒送出的訊息會遺失。
- **檢索的主要問題是速率，不是費用：** `RetrieveMemoryRecords` 整個帳號預設 **30 TPS**。Strands 每個使用者回合、**每個 namespace 各檢索一次**，兩個 namespace 就是兩次。月活 20 萬人的規模，尖峰就會超過預設配額。
- **`relevance_score` 是在 client 端過濾的**：檢索結果拿回來之後才丟掉低分的，**費用照算**。想省檢索費，要減少呼叫次數，而不是提高門檻。
- **Strands 讀取短期歷史時不設上限：** 恢復 session 時會把**全部**的歷史訊息讀回來（最多 10,000 則），再由 conversation manager 決定送進 prompt 的部分。長 session 的恢復會很慢。

## 計費規則

| 項目 | 價格 | 怎麼算 |
|---|---|---|
| 短期記憶 | $0.25 / 1,000 events | **每次 `CreateEvent` 呼叫算一個**，不論帶幾則訊息（一次最多 100 則）。官方原文：「billing is calculated per create event request」 |
| 長期儲存（built-in） | $0.75 / 1,000 筆 / 月 | 依小時計，以 31 天為一個月 |
| 長期儲存（override、self-managed） | $0.25 / 1,000 筆 / 月 | 模型或 pipeline 費用另計 |
| 長期檢索 | $0.50 / 1,000 次 | **每次 `RetrieveMemoryRecords` 呼叫**，不是每筆回傳的 record |
| `ListEvents`、`GetEvent`、`ListMemoryRecords`、`GetMemoryRecord` | 定價頁沒有列出 | 推論為不計費，**未經官方確認** |

官方範例：每月 10 萬個短期 event、1 萬筆長期 record、2 萬次檢索 → $25 + $7.50 + $10 = **$42.50**。

⚠️ 定價頁的用詞不一致：表格寫「record retrievals」，說明寫「per retrieve memory request」，範例寫「retrieval calls」。以「每次呼叫」理解。

## Strands 的實際讀寫行為

### 寫入：每輪幾次 `CreateEvent`

| 情境 | `batch_size=1`（預設） | `batch_size=10` |
|---|---|---|
| 一般回合（使用者說話、模型回答） | **2 次**（USER、ASSISTANT） | 約 2 次（訊息一批 + 狀態一批） |
| 一次工具呼叫的回合 | **5 次**（USER、ASSISTANT 的 toolUse、toolResult、ASSISTANT、agent 狀態） | 2 次 |
| 新 session 開始 | 另外 2 次（SESSION 和 AGENT 的狀態 blob） | — |

- **每次工具呼叫多 2 個 event**（toolUse 和 toolResult 各一個），而且 toolResult 是以 **USER** 角色寫入的，不是 TOOL。
- **Agent 狀態也寫成 event**（blob 格式），在第一輪、工具呼叫後、對話視窗被截斷時寫入。這些 event 也會計費（推論：依「每次 CreateEvent 計費」的規則）。
- 寫入的內容是整個訊息物件序列化成 JSON；**超過 10 萬字元的訊息改存成 blob**。
- **Batching 的設定：** `batch_size`（1–100）、`flush_interval_seconds`（預設關閉）。緩衝區滿、invocation 結束、計時器到、或呼叫 `close()` 時才送出。**程序在送出前結束，緩衝的訊息就會遺失。**
- 其他選項：`persistence_mode=NONE` 完全不寫入；`async_mode` 把呼叫移到背景執行緒。

### 檢索：每輪幾次

- **預設不檢索**，要設定 `retrieval_config` 才會開啟。
- **只在最後一則是使用者的文字訊息時檢索**，工具結果不會觸發。
- **每個 namespace 各呼叫一次**（平行執行），查詢字串就是使用者的原話，**不帶 metadata 過濾**。
- 預設 `top_k=10`、`relevance_score=0.2`，**分數門檻是拿回結果後在 client 端過濾**。
- 結果包在 `<user_context>...</user_context>` 裡，**插在目前這則使用者訊息的最前面**，不會被寫回記憶。
- ⚠️ Strands 的 `top_k` 允許到 1,000，但 API 的上限是 100。

### 讀取短期歷史

恢復一個 session 時：

1. 兩次 `ListEvents` 找 SESSION 和 AGENT 的狀態 blob。
2. 接著**讀回全部的歷史訊息**，每頁 100 筆，最多 10,000 則。實測 250 則訊息需要 5 次 `ListEvents`。
3. 讀完之後，才由 conversation manager（預設滑動視窗 40 則）決定哪些進 prompt。

**也就是說，SDK 限制的是「送進 prompt 的量」，不是「讀取的量」。** 長期使用的 session（例如一個客服對話持續好幾天）每次恢復都會讀完全部歷史。需要限制的話，用 `MemoryClient.get_last_k_turns` 或自己呼叫 `ListEvents`（推論：這些 API 可能不計費，但延遲和 `ListEvents` 每個 actor + session 20 TPS 的限制仍然存在）。

## 成本估算

`cost.py` 依上面的行為計算。假設：月活 1 萬人、每人每月 8 個 session、每個 session 6 回合、每回合 1 次工具呼叫、檢索 2 個 namespace、每人累積 30 筆長期記憶：

| 情境 | 短期記憶 | 長期儲存 | 長期檢索 | 合計／月 |
|---|---|---|---|---|
| Strands 預設 | $640 | $225 | $480 | **$1,345** |
| 開啟 batching | $280 | $225 | $480 | **$985** |
| Batching + 不自動檢索 | $280 | $225 | $0 | **$505** |

規模放大到月活 20 萬人（batching）：

| 情境 | 短期記憶 | 長期儲存 | 長期檢索 | 合計／月 | 檢索尖峰 |
|---|---|---|---|---|---|
| Built-in | $5,600 | $4,500 | $9,600 | **$19,700** | **約 37 TPS** |
| Override（儲存費較低，模型費另計） | $5,600 | $1,500 | $9,600 | **$16,700** | 約 37 TPS |

（尖峰以平均的 5 倍估算。）

怎麼讀：

- **工具呼叫多的 agent，短期記憶費用會快速增加。** 每次工具呼叫多 2 個 event，batching 的效果在這種 agent 上最明顯。
- **檢索是第二大的成本，而且隨 namespace 數量線性增加。** 每個使用者回合都檢索 2 個 namespace，就是 2 倍的費用和速率。
- **月活 20 萬人左右，檢索尖峰就會超過預設的 30 TPS。** 這是整個帳號共用的配額，同帳號的其他 agent 也會一起消耗。要提早申請調高。
- **Override 省下的儲存費要跟模型費一起看。** 萃取是由你帳號裡的模型執行，每次萃取都會讀整段對話；對話量大時，模型費可能超過省下的儲存費（推論，視模型與對話長度而定）。

## 設計選擇

### 每輪都檢索，還是讓模型自己決定

| | 每輪自動檢索（Strands、Harness 的預設） | 檢索做成工具（`AgentCoreMemoryToolProvider`） |
|---|---|---|
| 呼叫次數 | 每個使用者回合 × namespace 數 | 只在模型判斷需要時 |
| 品質 | 穩定，不會漏掉 | 模型可能忘記查，或查錯 |
| 延遲 | 每輪都多一次檢索 | 需要時多一次工具往返 |
| 適合 | 個人化很重要、對話短 | 大部分回合不需要記憶（例如技術問答） |

**官方沒有提供這方面的建議**，兩個官方元件的預設都是每輪檢索。

**折衷做法（判斷）：**

- **Session 開始時檢索一次**，結果放進 system prompt；之後的回合只靠短期記憶。長期記憶記的是「使用者是誰、偏好什麼」，在一個 session 內通常不會變。
- **只檢索真正需要的 namespace：** 例如 user preference 每輪都查，summary 只在 session 開始時查。
- **`topK` 不要設太大：** 每一筆都會被塞進 prompt，10 筆 × 每筆 50 字，每輪就多了幾百個 token 的模型費用。從 3–5 開始，依品質調整。

### 寫入的取捨

| 選項 | 好處 | 代價 |
|---|---|---|
| `batch_size=1`（預設） | 每則訊息立即持久化 | 費用最高；每個 actor + session 只有 5 TPS，工具呼叫密集時可能撞到上限 |
| `batch_size>1` | 費用降一半以上 | 程序意外結束時遺失緩衝的訊息 |
| 不寫工具訊息（自己控制） | 再省一些 | 失去完整的對話紀錄；episodic 策略官方建議要帶工具結果 |
| `extractionMode: SKIP` | 不參與長期萃取（但仍然計 event 費用） | — |

**判斷：** 一般對話型 agent 開 batching，並設定 `flush_interval_seconds` 作為保險。Runtime 的 microVM 可能在閒置時被回收，**invocation 結束時一定要 flush**（Strands 在 AfterInvocation 時會自動 flush）。

## Harness 自動讀寫 vs 自己控制

| | Harness 的 managed memory | Runtime + 自己控制 |
|---|---|---|
| 預設 | 透過 API 建立時**預設開啟**（CLI 建立時預設關閉）；策略為 semantic + summary；event 保留 30 天 | 自己決定 |
| 寫入 | 自動，次數文件沒寫 | 自己控制，可以 batching |
| 檢索 | 每次呼叫自動檢索，每個策略 `topK=10`、`relevanceScore=0.2` | 自己決定時機與 namespace |
| 可以調的 | 策略清單；CLI 的設定精靈可以調訊息數、topK、分數門檻；也可以接自己的 memory，用 `retrievalConfig` 指定每個 namespace 的參數 | 全部 |
| 刪除 | **刪除 harness 時預設連 memory 一起刪**，要傳 `deleteManagedMemory=false` 才會保留 | 獨立管理 |

- Harness 的預設值（topK 10、門檻 0.2）跟 Strands 完全一樣，推測底層用的是同一套 session manager，也就是**每個策略 namespace 每次呼叫檢索一次**（推論，未確認）。
- 官方原文：「AgentCore Memory bills when the harness writes events or retrieves records. Managed Memory is enabled by default」。**用 API 建 harness 時，就算沒打算用記憶，也已經在付費。**

**判斷：** Harness 適合「先跑起來」；流量大或對成本敏感時，改用 Runtime 自己控制讀寫，或至少把 harness 接到自己的 memory，用 `retrievalConfig` 調低 topK、減少 namespace。

## 配額

| API | 帳號 TPS | 每個 actor + session |
|---|---|---|
| `CreateEvent` | 200（可調整） | **5**（有對話內容時）/ 10（沒有時），**不可調整** |
| `ListEvents` | 200（可調整） | 20（不可調整） |
| `RetrieveMemoryRecords` | **30**（可調整） | — |
| `ListMemoryRecords` | 30（可調整） | — |
| `DeleteEvent` | 20（可調整） | 5（可調整） |
| 其他 Memory API | 20（可調整） | — |

- `topK` 1–100（預設 10）；`maxResults` 1–100（預設 20）；metadata 過濾最多 5 個條件。
- ⚠️ 檢索頁寫「每頁預設最多 100 筆」，API 參考寫 `maxResults` 預設 20。`topK` 設超過 20 時兩者怎麼互動，**文件沒寫**。
- ⚠️ Harness 的 event 保留期間最短 3 天，Memory 的配額頁寫最短 7 天；botocore 的 model 也允許 3。

## 參考資料

- [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)、[Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)
- [Retrieve records](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-retrieve-records.html)、[Metadata](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-memory-metadata.html)
- [Harness memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-memory.html)、[Harness operations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-operations.html)
- [aws/bedrock-agentcore-sdk-python](https://github.com/aws/bedrock-agentcore-sdk-python)：`memory/integrations/strands/session_manager.py`、`config.py`、`bedrock_converter.py`、`memory/client.py`
- [strands-agents/tools](https://github.com/strands-agents/tools)：`agent_core_memory.py`
