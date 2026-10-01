# 延伸：Web Search 的 grounding 品質與成本控制

> 接續 [05-built-in-tools](README.md#web-search-tool)。這篇討論：怎麼用網域和日期過濾提高回答的可信度；每千次 $7 的價格下，怎麼決定什麼時候該查、查幾筆；以及引用來源怎麼呈現才符合使用規定。
>
> 資料查核日期：2026-10-01。標示「推論」的部分是官方文件沒有明說、由我推導的。
>
> 本機工具：[experiments/web-search](experiments/web-search/)（月費估算與引用檢查，已實跑；**沒有實際呼叫過 Web Search**）。

## 結論先講

- **預設的 connector 版本還是 `1.1.0`，它沒有請求層級的過濾功能。** 網域和日期過濾要到 `1.2.0` 才有，**建立 target 時要明確指定 `"version": "1.2.0"`**，否則 agent 根本看不到 `filters` 參數。連官方的設定範例都是指定 `1.1.0`。
- **提高可信度最有效的是 target 層級的網域清單**：由管理者設定，agent 看不到也改不了，每個請求都會套用。請求層級的過濾只能在這個範圍內再縮小。
- **費用只跟「查詢次數」有關**，`maxResults` 不影響價格（依定價頁「per query」的寫法推論，未經官方確認）。省錢的關鍵是**減少查詢次數**：決定什麼時候不查、避免模型換關鍵字重查。`maxResults` 影響的是**塞進 prompt 的 token 數**。
- **使用規定不在 AWS Service Terms 裡，在開發者文件的「Acceptable use」段落**（更正 05 本文）：用到搜尋結果的輸出，必須保留並顯示來源連結。結果的 `url` 是**選填欄位**，沒有 URL 的結果不應該拿來當引用依據。

## 請求與回應

### 參數

| 參數 | 規則 | 版本 |
|---|---|---|
| `query` | 必填，**200 字元以內** | 全部 |
| `maxResults` | 1–25，預設 10 | 全部 |
| `filters.domainFilter.include` / `.exclude` | 各最多 100 個網域；**根網域會比對所有子網域** | **1.2.0 以上** |
| `filters.publishedDateFilter.from` / `.to` | ISO-8601 UTC，包含起訖；**只套用在網頁結果** | **1.2.0 以上** |

- **沒有語言、地區、國家、安全搜尋、分頁等參數。**
- 官方範例說「超過 200 字元的查詢可能不會回傳結果」，聽起來不是硬性的錯誤。**200 是字元還是位元組沒寫**，對中文查詢有影響（一個中文字在 UTF-8 是 3 個位元組）。
- 「日期過濾只套用在網頁結果」暗示還有非網頁的結果，推測是知識圖譜的答案，它們不受日期過濾影響（推論）。

### 回應

```json
{"isError": false, "content": [{"type": "text",
  "text": "{\"id\":\"824f89d0\",\"results\":[{\"text\":\"...\",\"url\":\"...\",\"title\":\"...\",\"publishedDate\":\"2024-10-07\"}]}"}]}
```

| 欄位 | 必填 | 說明 |
|---|---|---|
| `text` | ✓ | 經過語意擷取的相關段落 |
| `url` | **選填** | **可能沒有** |
| `title` | 選填 | |
| `publishedDate` | 選填 | 1.1.0 起才有 |

**沒有相關度分數。** 所以沒辦法用「分數低於多少就不採用」來過濾，只能靠網域和日期。

### 版本

| 版本 | 日期 | 變更 |
|---|---|---|
| 1.1.0（**預設**） | 2026-06-15 | 加入 `structuredContent`、`publishedDate`，改善段落擷取 |
| 1.2.0 | 2026-07-20 | 請求層級的網域與日期過濾 |

- ⚠️ **文件矛盾：** 版本頁說沒指定版本時用「目前的預設版本」（1.1.0），botocore 的說明卻寫「最新可用的版本」。**明確指定版本**就不用管這個矛盾。
- 版本是固定的：更新 target 時沒指定版本，**會維持原本的版本**，不會自動升級。
- 索引本身的改善（新鮮度、涵蓋範圍、段落品質）會自動生效，**但新的參數要升級版本才有**。

## 提高可信度：過濾的設計

### Target 層級（管理者）

```json
{"mcp": {"connector": {
   "source": {"connectorId": "web-search", "version": "1.2.0"},
   "configurations": [{"name": "WebSearch", "parameterValues": {
      "domainFilter": {"include": ["gov.tw", "who.int", "reuters.com"], "exclude": ["contentfarm.example"]}}}]}}}
```

官方的規則：

- 「Both lists are hidden from the calling agent and applied to every request.」
- 網域只要出現在 target 或請求的**任一個** exclude 清單，就會被排除。
- target 和請求都設了 include 時，**只回傳兩者都有的網域**；沒有交集就沒有結果。
- 「Request-level filters cannot override the target-level exclude list or expand results beyond the target-level include list.」

| 設定 | 版本 |
|---|---|
| Target 層級的 `exclude` | 全部版本 |
| Target 層級的 `include` | 1.2.0 以上 |

### 其他管理者能控制的地方

botocore 的 connector 設定還有兩個欄位，官方範例有用到：

- **`description`**：覆寫 agent 看到的工具說明（最多 2,000 字元）。可以在這裡寫「什麼時候該用、什麼時候不該用」（見下方的查詢策略）。
- **`parameterOverrides`**：`{path, description, visible}`，可以改某個參數的說明，或讓 agent **看不到**這個參數。
- **未確認：** 用 `parameterValues: {"maxResults": 5}` 搭配 `visible: false`，能不能把 `maxResults` 固定住。看起來可行，但 Web Search 的文件沒寫。

### 設計模式（判斷）

| 情境 | Target 層級 | 請求層級（讓 agent 決定） |
|---|---|---|
| **企業內部的事實查詢**（法規、政府公告） | `include` 官方網域 | 不需要 |
| **一般研究型 agent** | `exclude` 內容農場、已知的低品質站 | 依問題限定日期（例如「最近一年」） |
| **新聞、時事** | `exclude` 低品質站 | `publishedDateFilter.from` 設成最近幾天 |
| **競品分析** | 不限制 | `include` 競爭對手的網域 |
| **多個用途共用 gateway** | **拆成不同的 target**，各自設網域清單 | — |

- **最後一條很重要：** target 層級的清單套用在**每一個請求**，不同用途的 agent 需要不同的清單時，要建立多個 web-search target，用工具名稱區分（例如 `GovSearch___WebSearch`、`NewsSearch___WebSearch`）。
- **include 清單太嚴格，模型會一直查不到東西而換關鍵字重查**，反而增加查詢次數（推論）。

## 成本控制

### 計費

- **每千次查詢 $7**，「Billing is calculated per query submitted」。
- Gateway 的工具呼叫另外計費，每千次 $0.005，相對很小（官方範例：20 萬次查詢，Web Search $1,400、Gateway 只有 $3）。
- ⚠️ 不要跟 Gateway 的「Search API」（每千次 $0.025）搞混，那是 Gateway 工具的語意搜尋，不是網路搜尋。
- **沒寫的：** 零結果的查詢、被過濾到沒有結果的查詢、被限流或驗證失敗的查詢，**算不算費用都沒寫**。
- 配額：**10 TPS**（可以調整）。

### 估算

`cost.py` 的結果（每月 100 萬個使用者回合）：

| 情境 | 每月查詢次數 | 每月費用 | 每回合平均 |
|---|---|---|---|
| 60% 的回合會搜尋，每次平均查 2 次 | 120 萬 | **$8,400** | $0.0084 |
| 同上，加上 30% 的快取命中 | 84 萬 | $5,880 | $0.0059 |
| 只有 20% 的回合會搜尋，每次平均 1.5 次 | 30 萬 | **$2,100** | $0.0021 |

**「每次觸發平均查幾次」的影響跟「有多少回合會觸發」一樣大。** 模型查不到滿意的結果時，常會換個關鍵字再查，這是最容易被忽略的成本來源。

### 查詢策略（判斷）

| 策略 | 做法 | 效果 |
|---|---|---|
| **寫清楚什麼時候不查** | 在工具說明（`description` 覆寫）或 system prompt 寫明：「只有在問題涉及最近的事件、價格、或你不確定的事實時才搜尋；一般知識、程式寫法、計算不要搜尋」 | 減少觸發率，影響最大 |
| **限制重查次數** | 在 agent 程式裡計數，同一回合超過 2 次就不再提供這個工具，或回傳「已達查詢上限，請根據現有結果回答」 | 控制每次觸發的查詢數 |
| **在 agent 端擋重複查詢** | 同一個 session 內，相同的查詢字串直接回傳上次的結果 | 處理模型重複呼叫 |
| **`maxResults` 設小一點** | 3–5 筆通常就夠，預設 10 筆 | **不省搜尋費**，省的是模型的 token |
| **用日期和網域過濾提高命中率** | 讓第一次查詢就拿到好結果 | 減少重查 |

### 快取：灰色地帶

使用規定只禁止「**大量**（in bulk）擷取、儲存或重製搜尋結果內容」，以及建立競爭性的索引。**沒有明確允許或禁止短期的查詢快取，也沒有規定保留時間**。

**判斷：**

- **同一個 session 內的去重**（模型重複呼叫同樣的查詢）風險很低，也最常見，建議做。
- **跨使用者的共用快取**比較接近「儲存搜尋結果」，要先跟 AWS 確認。
- 不論哪一種，**從快取回傳的結果仍然必須顯示來源連結**。

## 引用來源的呈現

### 規定（原文）

「You must retain and display the source citations and links provided with each Search Result in any output you surface to your end users that uses the Search Result. You may not use Web Search Tool to (a) extract, store, or reproduce content from Search Results in bulk, or (b) build or populate a competing index or database.」

- 這段在開發者文件的「Acceptable use」段落，**AWS Service Terms（2026-09-15 版）沒有 Web Search 的章節**。05 本文寫「使用條款」，正確的出處是開發者文件。
- AgentCore 是 Bedrock 的一部分，Service Terms 的 Bedrock 一般條款仍然適用，例如不能把產生的內容專門拿來訓練 AI 模型。

### 不能只靠模型（判斷）

「請附上來源連結」寫在 prompt 裡，模型大多會照做，但**不保證**：可能漏掉、可能捏造 URL、可能引用了沒有 URL 的結果。這是一條**合規要求**，所以要在程式端保證。

`citations.py` 的做法：

1. 要求模型在回答裡用 `[n]` 標註引用的結果編號。
2. 程式端把 `[n]` 對應到搜尋結果的 URL，**由程式附在輸出最後**，而不是讓模型自己寫 URL。這樣 URL 一定是真的。
3. 檢查三種問題：引用了不存在的編號、引用了沒有 URL 的結果、整個回答沒有標註任何來源。

```
✓ 正常引用           problems=[]
   營收成長 12% [1]。
   來源：
   [1] A 公司財報（2026-09-01） https://example.com/a
✓ 引用沒有 URL 的結果 problems=['[2] 沒有 URL，無法顯示來源連結：不應作為引用依據']
✓ 引用不存在的編號    problems=['引用了不存在的來源 [3]']
✓ 沒有標註來源        problems=['回答沒有標註任何來源']
```

**發現問題時怎麼處理（判斷）：** 讓模型重寫一次，或移除沒有可用來源的句子。在對話型的介面，至少要確保「用了搜尋結果的回答」一定帶有來源清單。

官方範例的 system prompt 也可以參考：「Always cite your sources with URLs」「If search results are insufficient, say so rather than guessing」「Note the publication date of sources when available」。

## 還沒確認的事

| 問題 | 為什麼重要 |
|---|---|
| 中文查詢的品質 | 文件完全沒提語言支援，要實測 |
| 200 字元的限制是硬性的嗎？算字元還是位元組？ | 中文查詢會受影響 |
| 零結果或失敗的查詢收不收費 | 影響重查策略的成本 |
| `maxResults` 能不能由管理者固定 | 控制 token 成本 |
| 區域：開發者文件寫 us-east-1、愛爾蘭、東京三區，Harness 文件寫只有 us-east-1 | 東京能不能用 |

## 參考資料

- [Web Search Tool](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-connector-web-search-tool.html)、[Connector versions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-connector-versions.html)
- [Connector target 設定](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-api-target-config.html)
- [Harness tools](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-tools.html)
- [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)、[Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)
- [AWS Service Terms](https://aws.amazon.com/service-terms/)
- [awslabs/amazon-bedrock-agentcore-samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples)：`01-features/03-connect-your-agent-to-anything/03-web-search/`
