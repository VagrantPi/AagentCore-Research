# 延伸：把既有的內部 API 接成 agent 工具

> 接續 [03-gateway](README.md#三種-target)。這篇討論：現有的內部 API 要用哪一種 target 接進 Gateway；工具的名稱和說明怎麼寫，模型才會選對工具、又不會浪費 token；以及工具很多時，怎麼搭配語意搜尋分組。
>
> 資料查核日期：2026-09-30。標示「推論」的部分是官方文件沒有明說、由我推導的。
>
> 本機工具：[experiments/openapi-lint](experiments/openapi-lint/)（接入前檢查 OpenAPI 規格，已實跑）。

## 結論先講

- **選 target 的順序：** API 已經掛在 API Gateway（REST）上 → 用 **API Gateway stage target**，最省事；有 OpenAPI 規格 → **OpenAPI target**；需要把好幾個 API 組合成一個工具，或需要自訂邏輯 → **Lambda target**；已經有 MCP server → **MCP server target**。
- **Smithy target 實際上只能用來呼叫 AWS 服務：** 官方原文「doesn't support custom Smithy models for non-AWS services」。03 本文把它列成通用選項，**這裡更正**。
- **工具的說明是寫給模型看的 API 文件。** 模型只能靠名稱、說明和參數 schema 決定要不要呼叫、怎麼填參數。說明寫不好，模型就會選錯工具或捏造參數。
- **工具越多，每一輪對話的 token 成本越高、選錯的機率也越高。** 所有工具的定義每一輪都會送進模型。工具超過幾十個時，要開**語意搜尋**，讓模型先搜尋、只載入相關的工具。
- **把 API 直接轉成工具通常不是最好的設計（判斷）：** REST API 是為程式設計的（細粒度、多次往返），agent 工具應該是為「任務」設計的（粗粒度、一次完成一件事）。

## 選哪一種 target

| Target | 什麼時候用 | 工具名稱來源 | Outbound 驗證 | 限制 |
|---|---|---|---|---|
| **API Gateway stage** | API 已經在 API Gateway（REST API）上 | `operationId`；沒有的話用 `toolOverrides.name` | 不驗證、service role（IAM）、API key | **只支援 REST API**（不支援 HTTP API、WebSocket）；同帳號、同區域、公開端點；`{proxy+}` 資源會被排除 |
| **OpenAPI** | 有 OpenAPI 規格的任何 HTTPS API | `operationId` | 不驗證、service role（SigV4）、OAuth（2LO / 3LO / 換發）、API key | 見下方限制清單 |
| **Lambda** | 需要組合多個 API、做資料轉換、或呼叫內部系統 | 你在 `toolSchema` 裡定義 | service role | **既有的 Lambda 要改程式**：輸入格式不同 |
| **MCP server** | 已經有 MCP server | 由 server 提供 | 不驗證、service role、OAuth、API key | 工具變更後要手動同步（DEFAULT 模式） |
| **Smithy** | **呼叫 AWS 服務的 API** | Smithy model 的 operation | service role、OAuth 2LO | **不支援非 AWS 服務的自訂 model**；只支援 RestJson；不支援串流 |

### OpenAPI 的限制清單

- **每個要曝露的 operation 都要有 `operationId`**，它就是工具名稱。沒有的就不會變成工具。
- **不支援：** `oneOf` / `anyOf` / `allOf`、參數的序列化設定、規格裡的 `securitySchemes`（驗證要在 Gateway 的 outbound 設定）、callbacks、webhooks、links、binary 與自訂的 media type。
- **伺服器 URL 不要用 host 變數**；多租戶的變數要用 `enum` 列舉。Gateway 會擋掉私有 IP 範圍（要連 VPC 內的服務，用 target 的 `privateEndpoint`）。
- **SigV4 只在後端是 API Gateway、Lambda Function URL 或另一個 AgentCore Gateway 時有效**，放在 ALB 或 EC2 後面的服務不能用。
- ⚠️ **文件矛盾：**
  - 版本：同一頁開頭寫「supports OpenAPI 3.0」，限制清單寫「3.0 和 3.1 都支援」。
  - Content type：一處寫「只有 `application/json` 完整支援」，功能表卻列出 XML、multipart、form-urlencoded 都支援。**保守起見，只用 JSON。**
- 每個 target 最多 1,000 個工具；inline 規格 1 MB、S3 規格 10 MB（都可以調整）。

### Lambda target 的輸入格式

- `event` 就是**參數本身**（一個 dict），沒有 API Gateway 那種 HTTP 包裝。
- 其他資訊在 `context.client_context.custom` 裡：`bedrockAgentCoreToolName`（完整名稱 `target___tool`，**要自己去掉前綴**）、`bedrockAgentCoreGatewayId`、`bedrockAgentCoreTargetId`、MCP 的 message ID 等。
- 一個 Lambda 可以處理多個工具，依工具名稱分派：

```python
def handler(event, context):
    full = context.client_context.custom["bedrockAgentCoreToolName"]
    tool = full.split("___", 1)[1]          # OrderTools___get_order → get_order
    return {"get_order": get_order, "refund": refund}[tool](**event)
```

- ⚠️ 官方範例有 bug：先把名稱存進 `toolName`，後面卻用 `tool_name` 判斷。
- `toolSchema` 的型別只有 string、number、integer、boolean、array、object，**schema 定義裡沒有 enum 欄位**。

### 事前檢查（openapi-lint）

把 OpenAPI 規格接進 Gateway 之前，先在本機檢查一次，比部署後才發現某個 operation 沒有變成工具快得多。本篇附的 `lint.py` 會檢查官方限制，外加兩個經驗規則。對一份刻意放了問題的範例規格執行的結果：

```
工具數：2；tools/list 約 744 字元（以 4 字元 ≈ 1 token 粗估約 186 token；中文比例更高）
ERROR   不支援 oneOf：$.paths./orders/{orderId}/refunds.post.requestBody...
ERROR   DELETE /orders/{orderId}：缺少 operationId，不會變成工具
WARN    securitySchemes 會被忽略：驗證要改在 Gateway 的 outbound 設定
WARN    POST /orders/{orderId}/refunds：工具名稱 OrderApi___createRefundFor...（72 字元）可能超出模型的工具名稱限制
WARN    POST /orders/{orderId}/refunds：沒有 description / summary，模型只能靠名稱猜用途
```

- 有 ERROR 時結束碼為 1，可以直接放進 CI。
- **「缺少 operationId」其實有時是好事**：`DELETE` 沒有 operationId，就不會變成工具，等於用 operationId 當作曝露的白名單。但這應該是**刻意的決定**，而不是意外。

## 工具的名稱與說明怎麼寫

### 名稱

- 完整名稱是 `<target 名稱>___<工具名稱>`，**target 名稱也會算進去**。
- Gateway 允許最長 256 字元，但**許多模型的工具名稱限制在 64 字元左右**，只能用英數、`_`、`-`（推論：這是各家模型 API 的常見限制，官方只籠統地提醒「屬性名稱違反下游模型的規則時，呼叫會在執行時失敗」）。**Target 名稱要短**，例如 `Order` 而不是 `InternalOrderManagementServiceV2`。
- **名稱用「動詞 + 名詞」**：`get_order`、`create_refund`。模型對這種名稱的理解最穩定。

### 說明：寫給模型的 API 文件

官方的建議只有幾條：schema 保持簡單、用正確的型別、**參數要有清楚的說明**、必填欄位要標示、開啟語意搜尋。以下是我整理的寫法（判斷）：

| 要寫的 | 例子 | 為什麼 |
|---|---|---|
| **做什麼、回傳什麼** | 「用訂單編號查詢訂單狀態、金額與出貨資訊」 | 模型靠這句決定要不要呼叫 |
| **什麼時候該用、什麼時候不該用** | 「使用者詢問退款進度時，請用 `get_refund`，不要用這個工具」 | 相似的工具最容易選錯，要明確區分 |
| **參數的格式與來源** | 「訂單編號，格式 ORD-12345，從使用者的訊息或 `list_orders` 的結果取得」 | 減少模型捏造參數 |
| **限制與副作用** | 「會實際退款且無法撤銷；金額超過 500 美元會被拒絕」 | 讓模型在呼叫前確認 |
| **不要寫的** | 內部實作細節、HTTP 狀態碼、歷史沿革 | 浪費 token，還可能誤導模型 |

- **說明要簡潔：** 所有工具的定義每一輪都會送進模型。100 個工具、每個說明 200 字，每一輪就多了數千個 token。
- **可以在不改後端的情況下調整說明：**
  - API Gateway target 的 `toolOverrides.description`。
  - Gateway 層級的 MCP `instructions` 欄位（最多 2,048 字元），適合寫「這組工具的整體使用方式」。
  - AgentCore 也有用正式流量的 trace 自動改寫工具說明的功能（tool description recommendation），屬於 Optimization 的範圍，這裡不展開。

### 從 API 設計轉成工具設計

REST API 是為程式設計的，直接一對一轉成工具，常常會遇到這些問題（判斷）：

| API 的樣子 | 對 agent 的問題 | 改成 |
|---|---|---|
| 細粒度：先 `GET /customers?email=` 拿 ID，再 `GET /orders?customerId=` | 模型要多呼叫一次，每次都可能出錯，也多一輪 token | Lambda 包成一個 `find_orders_by_email` |
| 回傳整個物件，幾十個欄位 | 回傳內容也會進 context，浪費 token；可能含有不該給模型看的資料 | 只回傳模型需要的欄位 |
| 萬用端點：`POST /orders/{id}/actions`，`action` 決定要做什麼 | 模型容易填錯 `action`；後續也很難對不同動作做不同的授權 | 拆成 `cancel_order`、`refund_order` |
| 用錯誤碼表達業務狀態（404 = 沒有訂單） | 模型看到錯誤可能一直重試 | 回傳可讀的訊息：「查無此訂單，請確認編號」 |
| 分頁：一次回 20 筆，要傳 cursor | 模型不一定會記得翻頁 | 提供篩選參數，讓一次查詢就夠用 |

**判斷：** 如果內部 API 已經設計得不錯，直接用 OpenAPI 或 API Gateway target 接；如果 API 很細碎，**用一個 Lambda target 做「agent 專用的 facade」**，比讓模型自己組合十個 API 可靠得多。

## 工具很多時：語意搜尋與分組

### 語意搜尋怎麼運作

- 建立 gateway 時設定 `protocolConfiguration.mcp.searchType: "SEMANTIC"`（AgentCore CLI 預設開啟）。
- Gateway 會多一個工具 `x_amz_bedrock_agentcore_search`，參數是 `{"query": "..."}`，回傳相關的工具。開啟時它會排在 `tools/list` 的第一個。
- **模型的使用方式：** 先用自然語言搜尋「我需要查訂單的工具」，拿到相關的工具後再呼叫。這樣每一輪只需要載入少數工具，而不是全部。
- 官方有 Strands 的 `AgentCoreToolSearchPlugin` 範例：每一輪依照最近幾則訊息推斷意圖，搜尋後只載入相符的工具。

| 限制 | 內容 |
|---|---|
| 適用範圍 | **只有 MCP target**；HTTP、Runtime target 不適用；DYNAMIC 模式的 MCP server 不適用 |
| 索引 | 預先計算；DEFAULT 模式的 MCP server 工具變更後，要呼叫 `SynchronizeGatewayTargets` 才會更新 |
| 速率 | **每分鐘 25 次**（可以調整）。每一輪對話都搜尋的話，很快就會撞到上限 |
| 建立後能不能切換 | UpdateGateway 有 `searchType` 欄位，但文件只描述建立時開啟，**需要實測** |
| 費用 | 搜尋每千次 $0.025；索引每月每 100 個工具 $0.02 |

⚠️ **每分鐘 25 次的搜尋上限非常低。** 以每輪對話搜尋一次計算，大約只能支撐每分鐘 25 輪的對話量，正式上線前一定要申請調高，或是改成「只在需要時才搜尋」（判斷）。

### 什麼時候需要語意搜尋

| 工具數量 | 建議（判斷） |
|---|---|
| < 20 | 不需要。直接全部列出，模型選得很準 |
| 20–50 | 看工具之間的相似程度。相似的工具很多時就開啟 |
| > 50 | 開啟，或拆成多個 gateway 給不同的 agent |

### 分組策略

- **Target 就是分組的單位：** 工具名稱帶有 target 前綴，後續的授權規則也可以用 target 整批控制。所以**同一個業務領域、同一個信任等級的工具，放在同一個 target**。
- **不同的 agent 用不同的 gateway：** 客服 agent 不需要看到財務工具。拆 gateway 比依賴搜尋過濾更可靠，也符合 03 本文提到的「不同信任等級拆成不同 gateway」原則。
- **搜尋的品質取決於說明：** 語意搜尋是用工具的名稱和說明做比對，說明寫得模糊，搜尋也會找錯。
- ⚠️ 用設定檔（configuration bundle）覆寫的工具說明**只套用在 `tools/list`，不套用在搜尋**，所以搜尋結果看到的還是原本的說明。

## 配額

| 項目 | 值 |
|---|---|
| 每個 target 的工具數 | 1,000（可調整） |
| 每個 gateway 的 target 數 | 100 |
| 工具名稱長度 | 256 字元（可調整） |
| 語意搜尋 | 每分鐘 25 次（可調整） |
| 工具呼叫與 `tools/list` | 每個 gateway、每個帳號 200 TPS |
| 同一個 gateway 同時進行的 target 操作 | 5 個 |

## 參考資料

- [Target configuration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-api-target-config.html)
- [OpenAPI schema](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-schema-openapi.html)、[Lambda](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html)、[API Gateway stage](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-api-gateway.html)、[Smithy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-building-smithy-targets.html)、[MCP servers](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-MCPservers.html)
- [Tool naming](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html)、[Performance](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-advanced-performance.html)
- [Semantic search](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using-mcp-semantic-search.html)
- [agentcore-tool-search-plugin 範例](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/03-integrations/gateway/agentcore-tool-search-plugin)
- [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)、[Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)
