# 延伸：Inference target 當成企業的 LLM 代理

> 接續 [03-gateway](README.md#三種-target)。這篇討論：用 inference target 做統一的模型端點、集中管理供應商憑證、依團隊限制 token 用量、在模型之間分流；並跟自己架設 LiteLLM 這類開源代理比較。
>
> 資料查核日期：2026-09-30。標示「推論」的部分是官方文件沒有明說、由我推導的。**沒有實際部署驗證過**。

## 結論先講

- **它做得好的：** 一個端點相容 OpenAI 和 Anthropic 的 SDK、供應商的 API key 集中放在 Identity 的 token vault、**依團隊或使用者限制每分鐘 token 數**、用模型清單當白名單，而且不用自己維運。
- **它缺的，剛好是 LLM 代理常見的核心功能：** **沒有文件記載的自動重試、備援（fallback）到其他供應商、回應快取**；沒有依團隊統計 token 用量的 metric（做不了成本分攤）；**不同格式之間不會自動轉換**（用 OpenAI 格式呼叫，不會自動轉成 Anthropic 原生格式）。
- **「依權重分流」不像 03 本文寫的那麼直接：** gateway rules 的 `weightedRoute` 只記載支援 HTTP target。要在模型之間分流，官方的做法是用 **REQUEST interceptor 改寫 `model` 欄位**，也就是自己寫程式。
- **判斷：** 需求是「統一入口 + 憑證集中 + 依團隊限流」，而且已經全面在 AWS 上，inference target 很合適。需要備援、快取、成本分攤報表的話，LiteLLM 這類代理目前功能完整得多。**兩者也可以串接**：Gateway 當入口做驗證和限流，後面接 LiteLLM。

## 兩種設定方式

### Connector：零設定

```json
{"inference": {"connector": {"source": {"connectorId": "bedrock-mantle"}}}}
```

`connectorId` 可以是 `bedrock-mantle`、`openai`、`anthropic`。模型清單、路徑改寫都由 connector 處理。

### Provider：自己控制端點與模型

```json
{"inference": {"provider": {
  "endpoint": "https://bedrock-mantle.us-east-1.api.aws",
  "modelMapping": {"providerPrefix": {"strip": true, "separator": "."}},
  "operations": [
    {"path": "/v1/chat/completions",
     "models": [{"model": "anthropic.claude-opus-*"}, {"model": "anthropic.claude-sonnet-*"}, {"model": "openai.gpt-oss-*"}]},
    {"path": "/v1/messages", "providerPath": "/anthropic/v1/messages",
     "models": [{"model": "anthropic.claude-opus-*"}, {"model": "anthropic.claude-sonnet-*"}]}
  ]}}}
```

- **`operations` 就是模型白名單：** 沒列出的模型會被拒絕（「Model '...' not found on any target」）。模型名稱可以用 `*`、`?` 萬用字元。
- **任何相容 OpenAI 的端點都能接**，官方範例接了 Google Gemini 的 OpenAI 相容端點。
- ⚠️ 文件說 provider target 可以「設定每個模型的 token 上限」，但 **API 裡沒有這個欄位**。實際做法是用 rate limit，以 `qualifiedModelId` 為維度。

### 呼叫方式

| 端點 | 用途 |
|---|---|
| `/inference/v1/chat/completions` | OpenAI Chat Completions 格式 |
| `/inference/v1/responses` | OpenAI Responses 格式 |
| `/inference/v1/messages` | Anthropic Messages 格式 |
| `/inference/v1/models` | 彙整所有 target 的模型清單，ID 會加上 target 名稱前綴 |

- OpenAI SDK 設 `base_url=.../inference/v1`；Anthropic SDK 設 `.../inference`。
- **串流是原封不動轉送（SSE passthrough）。**
- **不做格式轉換：** 呼叫端用什麼格式，後端就要支援什麼格式。Bedrock 是透過 Mantle 的 OpenAI 相容與 Anthropic 相容端點接入，**不是** Bedrock 原生的 Converse / InvokeModel。

## 路由：請求會送到哪個 target

| `model` 欄位的寫法 | 行為 |
|---|---|
| `target名稱/模型` | 直接送到指定的 target |
| 只寫模型名稱，只有一個 target 符合 | 送到那個 target |
| 多個 target 符合 | 完全比對優先於萬用字元；同樣精確時，**有 Bedrock 就選 Bedrock**；否則隨機或輪流（⚠️ connector 頁寫「每次隨機」，provider 頁寫「round-robin」，互相矛盾） |

### 在模型之間分流或備援

| 需求 | 做法 | 說明 |
|---|---|---|
| 模型別名（例如 `auto-claude`） | **REQUEST interceptor 改寫 `model`** | 官方範例：依輸入長度選 Haiku、Sonnet 或 Opus |
| 依權重做 A/B | REQUEST interceptor 用亂數改寫 `model` | 要自己記錄分組，後續才能比較效果 |
| 備援（主要供應商失敗時換一家） | **沒有內建機制** | Interceptor 只能改寫請求，**看不到後端的回應是否失敗後再重送**；要在 client 端或另外的代理層處理（推論） |
| Gateway rules 的 `weightedRoute` | ⚠️ 只記載支援 **HTTP target** | Inference 請求走 `/inference` 路徑，rules 能不能套用，**文件沒寫** |

**這是 03 本文需要更正的地方：** 本文把「依權重分流（A/B）」列為 gateway rules 的功能，這沒錯，但**它不直接適用於 inference target**。

## 憑證集中管理

| 供應商 | Outbound 設定 |
|---|---|
| Bedrock | Gateway 的 service role（SigV4），或 Bedrock API key |
| OpenAI | API key，放在 Identity 的 token vault：`{"credentialLocation": "HEADER", "credentialParameterName": "Authorization", "credentialPrefix": "Bearer "}` |
| Anthropic | API key，header 用 `x-api-key` |

- **使用者和應用程式完全接觸不到供應商的 key。** 他們只需要能通過 Gateway 的 inbound 驗證（JWT 或 IAM）。離職、換團隊時撤銷的是公司自己的身分，供應商的 key 不用換。
- **所有使用者共用同一把供應商 key。** 所以供應商那邊的速率限制（TPM）是全公司共用的，這就是為什麼 Gateway 端的限流很重要。
- Bedrock 的短期 API key 最長 12 小時就過期，要透過 Secrets Manager 輪替。

## 依團隊限制 token 用量

### 設定方式

維度（最多 10 個，**建立後不能修改**）：`targetName`、`toolName`、`qualifiedModelId`、`$.context.jwt.<claim>`（例如 `$.context.jwt.team`）、`$.context.iam.principal`、`$.context.iam.sourceIdentity`。

```
--dimension-keys '["targetName","qualifiedModelId","$.context.jwt.sub"]'
--entries '[
  {"dimensions": {"targetName": "my-inference-target", "qualifiedModelId": "anthropic.claude-3-sonnet-20240229-v1:0", "$.context.jwt.sub": "*"},
   "requests": [{"rate": 100, "period": "minute"}],
   "tokens":   [{"rate": 50000, "period": "minute"}]},
  {"dimensions": {"targetName": "*", "qualifiedModelId": "*", "$.context.jwt.sub": "*"},
   "requests": [{"rate": 30, "period": "minute"}],
   "tokens":   [{"rate": 10000, "period": "minute"}]}
]'
```

- `*` 代表「每個不同的值各自一個額度」。例如 `$.context.jwt.sub: "*"` 就是每個使用者各自每分鐘 50,000 token。
- **最精確的那條生效**；有多條 rate limit 時，**全部都要通過**。
- Token 限制**只能以分鐘為單位**，而且只適用於 `/v1/chat/completions`、`/v1/messages`、`/v1/responses`。
- 另外還有 `connections`（同時進行中的請求數），可以防止單一使用者開很多條長串流。
- **每個團隊一個額度：** 在 IdP 裡加一個 `team` claim，維度用 `$.context.jwt.team`。

### Token 限制是怎麼算的

1. **請求進來時先估算 input token 並預扣**，超過剩餘額度就直接回 429，不會呼叫模型。
2. **回應結束後，依供應商回報的實際 input 和 output token 校正。**
3. **已經開始的回應不會被中斷**，所以一個很長的回應可能讓額度暫時變成負的。
4. 串流時，Gateway 會自動在 chat completions 請求加上 `stream_options.include_usage=true`，才拿得到用量。
5. **Prompt caching 的 token 沒有特別處理**，怎麼算取決於供應商怎麼回報。

### 精確度與失敗模式

- **最終一致：** 新建的限制一開始會多放行一些，token 限制收斂得比次數限制慢。
- **Fail-open：** 限流服務逾時就放行；**JWT 裡缺少維度用的 claim，整條限制就會被略過**。所以 `team` claim 一定要在 inbound 驗證時用 `customClaims` 強制存在。
- 429 的回應有 OpenAI 相容和 Anthropic 相容兩種格式，帶有 `limitKey` 和 `retryAfter`，SDK 的重試機制可以直接處理。
- ⚠️ **官方特別警告：** Gateway 對串流的長度和大小**沒有上限**。沒有設定 token 限制的話，單一使用者就能用光整個供應商的額度。

## 用量與成本的可見度

- **CloudWatch metric** 有 Invocations、Throttles、錯誤、延遲等，但**沒有依團隊或模型統計 token 用量的 metric**。
- 要做成本分攤，得從 `aws/spans` 的 span 或供應商的帳單自己彙整（推論：需要開啟 Gateway 的 tracing，並自己寫查詢）。
- **沒有找到內建的成本分攤功能。**

## 計費

- Gateway 每千次呼叫 $0.005，**inference 沒有額外的費用項目**；模型的 token 費用由各供應商（Bedrock、OpenAI…）自己收。
- 透過 Gateway 使用 Identity 不另外收費。
- 其他可能相關的限制：每個 gateway / 帳號 200 TPS、5,000 個同時連線、6 MB payload、15 分鐘逾時。這些是列在「工具呼叫」底下的配額，**是否同樣適用於 inference，文件沒寫**。

## 跟 LiteLLM 這類開源代理比較

LiteLLM 是常見的開源 LLM 代理：一個相容 OpenAI 的端點，後面可以接上百種模型供應商，要自己部署（容器 + 資料庫 + Redis）。以下比較依據它的公開功能（判斷，版本變化快，導入前要再確認）。

| 面向 | AgentCore inference target | LiteLLM（自架） |
|---|---|---|
| 維運 | **全託管**，沒有伺服器 | 自己部署、擴展、升級、監控 |
| 統一端點 | OpenAI、Anthropic 格式 | OpenAI 格式為主，**會自動轉換成各家的原生格式** |
| 供應商支援 | Bedrock（Mantle）、OpenAI、Anthropic，加上任何 OpenAI 相容端點 | 非常多，包括各家原生 API |
| 憑證管理 | Identity token vault，跟 IAM 整合 | 自己的資料庫 + 虛擬 key |
| 驗證 | JWT（企業 IdP）、IAM | 虛擬 key；企業 SSO 通常要付費版 |
| 依團隊限流 | ✓（token / 次數 / 連線數，依 JWT claim） | ✓（依虛擬 key、團隊） |
| **備援、重試** | **沒有文件記載** | ✓ 內建 |
| **回應快取** | **沒有** | ✓ |
| **成本分攤報表** | **沒有**，要自己彙整 | ✓ 內建依 key / 團隊的花費統計與預算 |
| 模型分流 | 要寫 interceptor | 內建依權重、依延遲等路由策略 |
| 內容安全 | Guardrails、授權規則（08） | 透過外掛整合 |
| 與 agent 工具整合 | **同一個 Gateway 同時管工具和模型** | 只管模型 |
| 資料是否離開 AWS | 看後端供應商 | 看部署位置與供應商 |

### 怎麼選（判斷）

| 情境 | 建議 |
|---|---|
| 主要用 Bedrock，要企業 IdP 驗證、依團隊限流、不想維運 | **Inference target** |
| 已經用 Gateway 管理 agent 工具，希望模型和工具同一個入口、同一套授權 | **Inference target** |
| 需要跨供應商自動備援、回應快取、完整的成本分攤與預算 | **LiteLLM** |
| 大量使用非 OpenAI 相容的供應商 API | **LiteLLM** |
| 兩種需求都有 | **串接**：Gateway（驗證、限流、guardrail）→ provider target 指向 LiteLLM（備援、快取、成本統計） |

串接的代價是多一跳的延遲和一套要維運的服務，但可以同時拿到 AWS 的身分整合和 LiteLLM 的代理功能。

## 參考資料

- [Inference targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-targets-inference.html)：[Connector](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-inference-connector.html)、[Provider](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-inference-provider.html)
- [Rate limits](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-rate-limits.html)
- [Interceptors](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors.html)、[Gateway rules](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-rules.html)
- [Gateway metrics](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-gateway-metrics.html)
- [awslabs/amazon-bedrock-agentcore-samples：03-model-governance-and-routing](https://github.com/awslabs/amazon-bedrock-agentcore-samples)（`01-attach-targets/llm-inference/`）
- [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
- [LiteLLM](https://github.com/BerriAI/litellm)
