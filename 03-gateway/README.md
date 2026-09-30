# Gateway

> 讓 agent 透過單一入口使用工具、其他 agent 與模型：把 API、Lambda、既有服務轉成 MCP 工具，也可以當作 agent 和 LLM 的代理。
>
> 資料查核日期：2026-09-30。本篇也一併整理了官方元件清單中的 **AWS Agent Registry**（本 repo 沒有獨立的資料夾）。

## TL;DR

- **Gateway 現在有三種角色：**
  - **MCP 聚合器**：把多個後端合併成一個虛擬的 MCP server。
  - **HTTP 代理**：轉送請求給 Runtime 上的 agent、A2A 服務，或任意 HTTP 端點。
  - **LLM 代理**（inference target）：一個端點統一轉送給 Bedrock、OpenAI、Anthropic 等不同的模型供應商。
  - 定位已經從「API 轉 MCP 工具」擴大成「**agent 流量的統一入口**」。
- **Inbound 驗證四選一：** JWT、IAM、`AUTHENTICATE_ONLY`、`NONE`。後兩種**Gateway 本身不做授權**，必須另外搭配 Policy、interceptor，或由後端自行授權，否則**任何人都能打到你的後端**。
- **Outbound 憑證依 target 類型有不同選擇：** gateway service role（SigV4）、呼叫者自己的 IAM、OAuth（2LO / 3LO / **on-behalf-of 換發**）、token 直通、API key。**Service role 是所有 target 共用的**，它的權限就是任何呼叫者透過這個 gateway 能碰到的上限。
- **工具多了要開語意搜尋：** 每個工具的定義都會吃模型的 input token，幾百個工具全部塞進 prompt 既貴又會降低準確度。
- **四種治理手段：** 可以寫程式改寫請求與回應的 interceptor（Lambda）、依呼叫者或工具限流的 rate limit、做 A/B 與路由的 gateway rules、Policy（Cedar，留到 [08](../08-policy/)）。
- **Registry** 是組織層級的「agent / MCP server / skill 目錄」，附審核流程。⚠️ 預覽版使用的 `bedrock-agentcore` namespace **將在 2026-10-30 停止支援**，要遷移到新的 `agent-registry`。

## 先對齊幾個 AI 名詞

| 名詞 | 白話解釋 | 類比 |
|------|---------|------|
| **Tool definition** | 工具的名稱、說明和參數 schema，**每次呼叫模型時都要一起送進去**，模型才知道有哪些工具可以用 | 一份 OpenAPI 文件，而且每次請求都要附上 |
| **MCP 的 tools / prompts / resources** | 除了工具之外，MCP server 還可以提供可重複使用的 prompt 範本，以及用 URI 讀取的資料 | 一個 server 同時提供 RPC 方法、範本和檔案 |
| **Elicitation** | 工具執行到一半，**反過來問使用者**要更多資訊或確認 | 互動式 CLI 的 prompt |
| **Sampling** | 工具反過來**請 agent 端的 LLM 幫忙產生內容** | 伺服器對客戶端發起 callback |
| **3LO**（three-legged OAuth） | 代替**特定使用者**去存取第三方服務，需要使用者本人按下同意 | 「用 Google 登入並授權存取你的行事曆」 |

## 核心概念

### 三種 target

```
                           ┌── MCP targets（聚合成一個虛擬的 MCP server，路徑 /mcp）
                           │     Lambda、API Gateway stage、OpenAPI、Smithy、
Agent ──► Gateway ─────────┤     遠端 MCP server、整合範本、內建 connector（KB、Web Search、Memory…）
   （inbound 驗證）          │
                           ├── HTTP targets（直接轉送，不做協定轉換，依路徑 /<target>/… 分流）
                           │     AgentCore Runtime、A2A、passthrough 到任意 HTTP 端點
                           │
                           └── Inference targets（LLM 代理：依請求裡的 model 欄位轉送）
                                 connector（零設定）或 provider（自己控制端點與模型對應）
```

| 類別 | 特色 | 不支援的功能 |
|------|------|-------------|
| MCP | 聚合成單一的 `tools/list`、支援能力同步、語意搜尋、在 target 層級做 3LO | — |
| HTTP | 轉送給 Runtime 或其他 agent；**可以把 Gateway 放在 Runtime 前面當唯一入口**（見 [01 安全要點](../01-runtime/README.md#安全要點)、[延伸](runtime-front-door.md)）。⚠️ Runtime target **只能加到沒有設定 `protocolType` 的 gateway** | 能力同步、語意搜尋 |
| Inference | 可以直接用 OpenAI SDK 或 Anthropic SDK 呼叫 Gateway，換模型只需要改 model 字串；集中套用 Guardrails 和 Policy；提供彙整所有供應商的模型清單 | — |

- **工具命名規則是 `${target名稱}___${工具名稱}`**，中間是三個底線。你的 Lambda handler 要自己把前綴去掉。
- **遠端 MCP server 的兩種同步模式：**
  - **DEFAULT**：建立或更新 target 時自動同步一次；之後後端的工具有變動，**要自己呼叫 `SynchronizeGatewayTargets`**，否則 agent 看到的會是舊的清單。這是非同步操作，大型目錄可能要好幾分鐘。
  - **DYNAMIC**：每次呼叫時才即時向後端查詢，但**不能搭配語意搜尋和 3LO**。
- **支援的 MCP 版本：** `2026-07-28`、`2025-11-25`、`2025-06-18`、`2025-03-26`。`2026-07-28` 版是無狀態的，elicitation 和 sampling 改用 multi round-trip requests，**要由你的 MCP server 自己驗證往返的 `requestState` 是不是屬於同一個使用者**，Gateway 不會檢查。

### Inbound：誰可以呼叫 Gateway

| 類型 | Gateway 做什麼 | 什麼時候用 |
|------|---------------|-----------|
| `CUSTOM_JWT` | 驗證 JWT，依 discovery URL、audience、client、scope、自訂 claim 設定；缺少 scope 時回 403 並附上 `WWW-Authenticate`，MCP client 可以依此自動發現需要的 scope | 終端使用者或外部 agent |
| `AWS_IAM` | 驗證 SigV4 並檢查 `InvokeGateway` 權限 | AWS 內部服務之間的呼叫 |
| `AUTHENTICATE_ONLY` | **只驗證 SigV4 簽章，不做授權** | 把既有的 Runtime 接到 Gateway 後面，但暫時不想改它的驗證方式 |
| `NONE` | **什麼都不檢查** | 真的要公開的服務，而且已經有自己的限流與檢查機制 |

- JWT 的 `sub` claim **會被記錄到 CloudTrail**，官方建議不要在 `sub` 裡放個人資料，改用 GUID 這類識別碼。
- 可以用 `bedrock-agentcore:GatewayAuthorizerType` 這個 condition key，在組織層級禁止建立 `NONE` 類型的 gateway。
- IdP 在 VPC 內部時，可以透過 VPC Lattice 設定 `privateEndpoint` 連線。

### Outbound：Gateway 用什麼身分去呼叫後端

| Target 類型 | 不驗證 | Service role | 呼叫者的 IAM | OAuth 2LO | OAuth 3LO | OAuth 換發（OBO） | Token 直通 | API key |
|------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| API Gateway stage | ✓ | ✓ | | | | | | ✓ |
| Lambda | | ✓ | | | | | | |
| MCP server | ✓ | ✓ | | ✓ | ✓ | ✓ | | ✓ |
| OpenAPI | ✓ | ✓ | | ✓ | ✓ | ✓ | | ✓ |
| Smithy（**只支援 AWS 服務的 model**） | | ✓ | | ✓ | | | | |
| AgentCore Runtime（HTTP） | | ✓ | ✓ | ✓ | | ⚠️ 文件說不支援，但官方範例有用 | ✓ | |

- **On-behalf-of（OBO，代表使用者換發 token）是官方建議的正式環境做法：** Gateway 拿使用者的 token 換一張**範圍更小、audience 只限於目標服務**的新 token。新 token 同時帶有「使用者是誰」和「agent 是誰」的資訊，下游每一層都能各自做授權。Token 直通（passthrough）只建議在試驗或初期導入時使用。
- **3LO 的流程：** 使用者第一次用到某個需要授權的工具時，Gateway 會回傳一個授權 URL，使用者在瀏覽器裡同意後才能繼續。有 **session binding** 機制：同意完成後，應用程式要呼叫 `CompleteResourceTokenAuth`，由 Identity 驗證「發起授權的人」和「按下同意的人」是同一個人，避免授權 URL 被轉傳給別人使用。URL 的有效期限是 10 分鐘。細節留到 [04-identity](../04-identity/)。
- **最小權限的原則（官方）：** 不同信任等級的 target 要**拆成不同的 gateway**，各自使用不同的 service role。共用同一個 gateway 時，用 Policy 限制哪些呼叫者可以用哪些 target。

## 治理手段

| 手段 | 能做什麼 | 限制與注意事項 |
|------|---------|---------------|
| **Interceptor**（Lambda） | REQUEST：在呼叫後端之前驗證、授權、改寫請求，或直接回應（短路）；RESPONSE：在回傳給呼叫者之前遮罩或加工內容 | Lambda 同步呼叫有 **6 MB** 的 payload 上限，LLM 的大回應可能會超過，這時要用 payload filter 排除 body；HTTP target 的 interceptor **不支援串流模式**；MCP 串流回應時，interceptor **每個事件都會被呼叫一次** |
| **Rate limit** | 依 JWT claim、IAM 身分、target、工具等維度（最多 10 個）分組限流；inference target 可以限制每分鐘的 token 數；把速率設為 0 就等於封鎖 | **預設 fail-open**：限流服務不可用，或無法解析維度時，請求會直接放行，**不能當作安全邊界**；變更最多 30 秒才會生效；每個 gateway 最多 50 條規則 |
| **Gateway rules** | 依呼叫者或路徑，把流量導到指定的 target，或切換 configuration bundle 版本；支援依權重分流（A/B） | 每個 gateway 最多 20 條規則；依權重分流只能分成 2 組；路徑條件只支援 HTTP target；`routeToTarget` 的依權重分流**只記載支援 HTTP target**，inference target 的模型分流要用 interceptor 改寫 `model`（見[延伸](llm-proxy.md#在模型之間分流或備援)） |
| **Policy**（Cedar） | 在工具被呼叫之前做確定性的允許或拒絕判斷 | 見 [08-policy](../08-policy/) |
| 其他 | WAF、自訂網域、KMS CMK 加密、header 傳遞、CloudTrail 的資料事件 | — |

**判斷：**

- **授權用 Policy**，因為它是宣告式的、可以稽核。
- **內容加工用 interceptor**，例如遮罩個資、加上 header。
- **防濫用用 rate limit**，但不能拿它當安全機制。
- **灰度發布用 rules。**

## 語意搜尋工具

**為什麼需要：** 工具定義會吃 input token。以 [00 延伸](../00-overview/harness-vs-runtime.md#踩雷清單)的數據來看，光是兩個內建工具就要約 900 token。如果一個 gateway 掛了幾百個工具，**每次呼叫模型都要送幾萬 token 的工具說明**，既貴又容易讓模型選錯工具。

**做法：**

- 建立 gateway 時開啟語意搜尋，agent 就會多一個 `x_amz_bedrock_agentcore_search` 工具，可以用自然語言找出相關的工具。
- 典型的模式是：agent 一開始只看得到這個搜尋工具，搜到需要的工具之後才去呼叫它（判斷）。

**限制：**

- 只支援 MCP target，而且 DYNAMIC 模式的 target 不支援。
- **搜尋速率預設只有每分鐘 25 次**，很容易成為瓶頸。
- 計費：搜尋每千次 $0.025，另外依索引的工具數量收費。

## AWS Agent Registry（組織層級的目錄）

| 項目 | 內容 |
|------|------|
| 收錄什麼 | MCP server、agent（依 A2A schema 驗證）、skill，以及自訂類型（API、Lambda、KB、DB 等，搭配自訂的 metadata schema） |
| 審核流程 | 送審 → EventBridge 通知 → 你既有的審核流程 → 呼叫 `UpdateRegistryRecordStatus` 核准或退回；過時的項目可以標記為 deprecated，下架後就搜尋不到；開發環境可以設定自動核准 |
| 搜尋 | 語意搜尋和關鍵字搜尋同時進行；每個 registry 都有一個 **MCP 端點**，coding assistant 可以直接連上來搜尋 |
| 同步 | 從外部 MCP server 的 URL 抓取名稱和工具說明，每次同步都會產生一個新版本 |
| 組織整合 | 搭配 AWS Organizations，可以**自動偵測**所有成員帳號的 Runtime 和 Gateway 並建檔；也可以用 RAM 跨帳號分享 |
| 驗證 | 搜尋和 MCP 端點可以用 IAM 或 JWT；控制面永遠用 IAM |
| 區域 | us-east-1、us-west-2、愛爾蘭、雪梨、**東京** |
| ⚠️ 遷移 | 已經改用新的 `agent-registry` namespace。預覽版的 `bedrock-agentcore` namespace **將在 2026-10-30 停止支援** |

**跟 Gateway 的分工：** Registry 負責「**找**」，也就是組織內有哪些工具和 agent 可以用，並經過審核；Gateway 負責「**用**」，也就是實際的連線、驗證與治理。

## 值得注意的配額

| 項目 | 預設值 |
|------|--------|
| 每個 gateway 的 target 數 / 每個 target 的工具數 | 100 / 1,000 |
| 工具呼叫與列出工具的速率 | 每個 gateway 200 TPS，**整個帳號也是 200 TPS**（多個 gateway 共用這個額度） |
| 並發連線數 | 每個 gateway 5,000，整個帳號也是 5,000 |
| **搜尋型工具呼叫** | **每分鐘 25 次** |
| 呼叫逾時 / payload | 15 分鐘 / 6 MB |
| Web Search Tool | 10 TPS |

以上配額都可以申請調高。**整個帳號共用 200 TPS** 是很容易被忽略的限制：拆成多個 gateway 並不會增加總額度。

## 踩雷清單

1. **`AUTHENTICATE_ONLY` 和 `NONE` 不做授權**，必須另外搭配 Policy、interceptor，或由後端自行授權。
2. **Service role 是所有 target 共用的**，權限就是所有呼叫者能碰到的上限。不同信任等級的 target 要拆開成不同的 gateway。
3. **遠端 MCP server 的工具有變動時，要手動呼叫 `SynchronizeGatewayTargets`**（DEFAULT 模式）。
4. **工具名稱會自動加上 `target___` 前綴**，後端要自己處理。
5. **Rate limit 預設 fail-open**，不能當作安全機制。
6. **Interceptor 受 Lambda 6 MB 的 payload 上限影響**，HTTP target 也還不支援串流模式。
7. **語意搜尋每分鐘只能 25 次**，而且帳號層級的工具呼叫只有 200 TPS。
8. **MCP `2026-07-28` 版的 `requestState` 要由你的 server 自己驗證**是否屬於同一個使用者。
9. **JWT 的 `sub` 會出現在 CloudTrail 裡。**
10. **Registry 預覽版的 namespace 將在 2026-10-30 停止支援。**

## 與其他元件的關係

- **Runtime：** 可以把 Gateway 放在 Runtime 前面當唯一入口；Runtime 也可以是 Gateway 的 HTTP target，或是 MCP server target（用 SigV4 驗證）。
- **Harness：** 設定一個 `agentcore_gateway` 工具，就能取得 gateway 上的所有工具。
- **Memory：** 可以透過 Memory connector 讓 Memory 經由 Gateway 對外，再搭配 Cedar 做 per-user 的 FGAC（見 [02](../02-memory/README.md#權限控制的三道防線)）。
- **Identity：** outbound 用的 OAuth / API key 憑證都存放在 Identity 的 token vault。
- **Policy / Optimization：** Policy 的評估點在 Gateway 上；Optimization 的 A/B 測試靠 gateway rules 分流。

## 研究問題

- [x] 支援的 target 類型（MCP：Lambda、API GW、OpenAPI、Smithy、MCP server、connector；HTTP；Inference）
- [x] Inbound / outbound 驗證設定
- [x] 工具的語意搜尋
- [x] 與 Policy（Cedar）的串接點（細節留到 08）

## 延伸調研

- [把既有的內部 API 接成 agent 工具](api-to-tools.md)：target 怎麼選（Smithy 只支援 AWS 服務）、名稱與說明的寫法、從 API 設計轉成工具設計、語意搜尋與分組
- [Gateway 當成 Runtime 唯一入口](runtime-front-door.md)：inbound 與 outbound 的搭配、用 resource policy 和 `allowedWorkloadConfiguration` 防止繞過、各種控制放哪一層
- [Inference target 當成企業的 LLM 代理](llm-proxy.md)：憑證集中、依團隊限制 token、模型分流的實際做法、跟 LiteLLM 比較

## 實驗

- [OpenAPI 事前檢查](experiments/openapi-lint/)：接入前檢查規格是否符合 Gateway 的限制，已實跑

## 參考資料

- [Core concepts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-core-concepts.html)、[Supported targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-supported-targets.html)、[Inference targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-targets-inference.html)
- [MCP server targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-MCPservers.html)、[Tool naming](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html)
- [Inbound auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html)、[Outbound auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-outbound-auth.html)
- [Interceptor types](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors-types.html)、[Rate limits](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-rate-limits.html)、[Gateway rules](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-rules.html)
- [Semantic search](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using-mcp-semantic-search.html)
- [AWS Agent Registry：Key capabilities](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry-key-capabilities.html)
- [Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)

## 延伸調研方向

範圍在 00–03 之內，以 03 為主：

1. **把既有的內部 API 接成 agent 工具的實作指南：** OpenAPI、Lambda、Smithy 三種 target 怎麼選；工具的名稱與說明怎麼寫，才能讓模型選對工具並降低 token 消耗；搭配語意搜尋時的分組策略。
2. **Gateway 當成 Runtime 唯一入口的完整部署：** inbound 驗證、outbound 的 OBO 或呼叫者 IAM 怎麼選；如何用 resource policy 或 `allowedWorkloadConfiguration` 防止直接呼叫 Runtime；以及 interceptor、rate limit、rules 各自該放在哪一層。
3. **Inference target 當成企業的 LLM 代理：** 統一的模型端點、憑證集中管理、每個團隊的 token 限流、依權重分流做模型 A/B，並評估跟自己架 LiteLLM 這類代理相比的取捨。
