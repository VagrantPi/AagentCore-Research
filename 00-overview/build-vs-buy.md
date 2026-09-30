# 延伸：自建 vs 用 AgentCore

> 接續 [總覽](README.md)。「自建」在這裡指：在自己的 EKS / ECS 上跑開源 agent 框架（例如 LangGraph、Strands），並自行組裝 Redis / Postgres、OpenTelemetry 等周邊元件。這篇回答兩個問題：自建要多做哪些事？用 AgentCore 會被綁住多少？
>
> 資料查核日期：2026-09-30。AgentCore 端的事實來自官方文件；自建端的難度評估屬於工程判斷，文中會標示「判斷」。

## 結論先講

- **自建的難點不在 agent loop 本身**（開源框架都寫好了），而在三個地方：**① 每個 session 的強隔離（因為 agent 可能執行它自己產生的程式碼）② 代替每個使用者保管第三方 OAuth token ③ 長期記憶的萃取流程**。AgentCore 最值錢的也正是這三塊。
- **綁定程度比想像中低：** Runtime 的服務契約就是一般的 HTTP container；Observability 用 OTel；Policy 用開源的 Cedar；Harness 可以 export 成 Python 程式碼；模型也不綁 Bedrock。**真正黏的只有 Memory**（專有 API 加上萃取邏輯），其次是 Identity 的 token vault。
- 由於各元件可以單獨使用，**混合策略往往是最務實的選擇**：自己跑 agent，只買最難自建的那幾塊。

## 元件對照：自建要做什麼

難度欄是判斷：**低**＝現成方案接上就能用；**中**＝需要整合與維運；**高**＝需要專門的知識，或有安全上的風險。

| AgentCore 元件 | 自建常見做法（舉例） | 難度 | 真正難的地方 |
|----------------|---------------------|:---:|-------------|
| Harness（agent loop） | LangGraph、Strands、Claude Agent SDK | 低 | 框架都已經處理好了 |
| Runtime：一般 hosting | ECS / EKS / Lambda | 低 | — |
| Runtime：**session 強隔離** | 每個 session 開一個 Firecracker / gVisor / Kata sandbox | **高** | 一般 container 共用 kernel，執行不受信任的程式碼時隔離不夠。要做到「每個 session 一台 microVM、用完就清掉、能縮到 0、最長活 8 小時」，需要自己寫一整套排程器 |
| Memory：短期 | Redis / Postgres 存對話歷史 | 低 | — |
| Memory：**長期** | 向量資料庫（例如 pgvector）加上一條**用 LLM 萃取事實的 pipeline** | 中–高 | 什麼時候萃取、如何合併與去重、新舊資訊衝突時怎麼處理、如何依使用者隔離 namespace，全部要自己設計，而且萃取本身也要花 token |
| Gateway | 自己架 MCP server 或 proxy，把 API 包成工具 | 中 | 工具多了之後，要讓 agent 找得到合適的工具（語意搜尋），才不會把幾百個工具定義全部塞進 prompt |
| Identity：inbound | 串接現有的 IdP（Cognito、Okta 等）驗 JWT | 低 | — |
| Identity：**outbound** | 為每個使用者走 OAuth 授權流程，並保管 refresh token | **高** | 每個 SaaS 的 OAuth 實作都有差異，還要處理 token 加密保存、自動刷新、撤銷，以及**「agent 代替這位使用者行事」的授權鏈** |
| Policy | 在工具 proxy 前面放 OPA 或 Cedar | 中 | 引擎是現成的，但要在每次工具呼叫前都攔截，並把工具的參數轉成 policy 能評估的格式 |
| Code Interpreter | 自己架沙箱，或向 E2B 這類第三方購買 | **高** | 跟 Runtime 隔離是同一個問題，而且更嚴重，因為這裡**本來就是要執行任意程式碼** |
| Browser | 自己維運一組 headless Chrome | 中–高 | 並發擴展、錄製 session、live view、登入狀態保存、代理設定 |
| Observability | OTel Collector 加上 Langfuse、Phoenix、Tempo 這類工具 | 低–中 | 標準成熟，主要工作是整合 |
| Evaluations | DeepEval、Ragas 等開源工具，外加自己的排程 pipeline | 中 | 「對正式流量做抽樣、持續評分」這條 pipeline 要自己寫 |
| Payments | 自行串接加密貨幣錢包與 x402 | 高 | 應用領域很窄，大多數團隊用不到 |

### 自建的隱性成本

- **維運：** 每一個元件都要有人負責值班、升級、修補安全漏洞。
- **安全審查：** 「agent 在我們的環境裡執行它自己產生的程式碼」這件事，在資安審查時會被嚴格檢視。AgentCore 的 microVM 隔離可以直接拿來回答這個問題。
- **跟進速度：** Agent 領域的標準（例如 MCP、A2A）和最佳實踐大約每季都在變，自建就得自己追。

## 綁定程度分析

依「離開 AgentCore 需要付出多少代價」排序：

| 元件 | 介面是否為開放標準 | 資料能否帶走 | 離開的代價 |
|------|-------------------|-------------|-----------|
| 模型 | 支援 Bedrock、OpenAI、Gemini、LiteLLM | — | **低**：模型不綁 AWS |
| Runtime | 服務契約是一般的 HTTP：`0.0.0.0:8080`，`POST /invocations`、`GET /ping`、可選的 `/ws`；ARM64 container | 無狀態 | **低**：container 可以直接搬到其他地方跑，只要把 SDK 提供的 entrypoint 換掉 |
| Observability | OpenTelemetry | Trace 可以送到任何支援 OTel 的後端 | **低** |
| Policy | Cedar（AWS 開源的 policy 語言） | Policy 原始碼本來就在你手上 | **低**：可以改用 Cedar 開源引擎自己跑 |
| Harness | 專有的設定格式 | 可以 export 成 Strands Python 程式碼 | **中低**：export 之後，能在任何地方執行 |
| Evaluations | 專有 API，但也能跑 DeepEval 的評估器 | 評估結果存在 CloudWatch | **中低** |
| Gateway | **對 agent 端**是標準的 MCP | Target 的設定格式是專有的 | **中**：agent 那邊不用改，但要在別處重建 proxy |
| Identity | OAuth / OIDC 標準 | Token vault 裡的使用者 token 能否匯出，官方文件**沒有說明** | **中**：推論是遷移時使用者需要重新授權所有第三方服務（未經證實） |
| **Memory** | **專有 API** | 可以透過 `ListEvents` / `ListMemoryRecords` 匯出原始資料 | **中高**：資料帶得走，但**萃取與檢索的行為帶不走**；換成自建方案後，agent「記住事情的方式」會改變，需要重新調整 |

**綁定的重點在 Memory。** 如果很在意被綁住，可以考慮讓 Memory 走自建或其他方案，其他元件都用 AgentCore。代價是 Harness 的一鍵 memory 功能就用不到了。

## 成本面：什麼情況下自建比較便宜

以下為判斷，沒有實際數據：

- **AgentCore 的計價偏向「流量不穩定、大部分時間在等」的工作負載：** 等待 I/O 的時間不收 CPU 費用，沒有流量時費用趨近於 0。Agent 呼叫模型時大多數時間都在等，正好吃到這個優勢。
- **自建的成本結構是「固定成本 + 人力」：** 叢集要常駐，還要有人值班。流量低或不穩定的時候，這部分的成本通常高過 AgentCore。
- **流量高且穩定的時候，自建才可能比較便宜：** 用 reserved 或 spot 機器攤平費用。但 AgentCore 也提供 **Runtime Instances**（用自己的 EC2，外加 12% 管理費）和 2026-10 起的 committed baseline 價格，差距會縮小。
- **人力成本通常才是主要差距：** 單是 session 強隔離和 outbound OAuth 這兩項，自建就是以「人月」計的工作量。

## 什麼時候該自建

| 情境 | 建議 |
|------|------|
| 資料**必須留在台灣**（法規、合約） | AgentCore 沒有台灣區，**這是硬限制**，只能自建或找本地的雲端方案 |
| 多雲、地端部署是硬需求 | 自建，或只把 AgentCore 用在 AWS 那一側 |
| 已經有成熟的 K8s 平台團隊，而且 agent 不會執行不受信任的程式碼 | 自建 hosting 的難度會降到「低」，可以只買 Identity 或 Code Interpreter |
| 流量極高又穩定，而且成本是首要考量 | 先評估 Runtime Instances；還是不划算，再考慮自建 |
| 需要 AgentCore 不支援的隔離或網路模型 | 自建 |
| **以上都不是** | 用 AgentCore，先從 Harness 開始 |

## 混合策略的常見組合

由於元件可以單獨使用，以下是幾種常見的組法（判斷）：

1. **全部用 AgentCore，只有 Memory 自建：** 降低最主要的綁定點。
2. **Agent 跑在自己的 EKS 上，只買最難自建的部分：** 用 Identity 管 outbound OAuth、用 Code Interpreter 或 Browser 當沙箱、用 Gateway + Policy 做工具的治理。
3. **先全部用 AgentCore 快速上線，把 Harness export 當成退場路線：** 等規模起來、需求明確之後，再逐一評估要不要把某個元件換成自建。

## 參考資料

- [Runtime HTTP protocol contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html)
- [Runtime：How it works](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html)
- [Export harness to code](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-export.html)
- [What is Amazon Bedrock AgentCore?](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)（Policy 使用 Cedar、Observability 使用 OTel）
- [Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)（Memory 的 `ListEvents` / `ListMemoryRecords` API）
- [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
