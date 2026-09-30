# 延伸：用 temporal policy 控管業務流程

> 接續 [08-policy](README.md#1-temporal-policydogwood有狀態的規則)。這篇整理「先查詢再操作」「核准後才能執行」「session 內的總額上限」等模式的寫法與陷阱；重新檢視 session ID 由呼叫端提供的弱點，以及可以用哪些機制補強；最後是修改 policy 時的 409 怎麼處理。
>
> 資料查核日期：2026-09-30。標示「推論」的部分是官方文件沒有明說、由我推導的。Temporal policy 使用 Dogwood 語法，本機的 Cedar 工具跑不了，**本篇的範例沒有實際在 AgentCore 上執行過**。

## 結論先講

- **Temporal policy 解決的是「單次呼叫看不出來、要看前後文才知道」的規則**，例如「轉帳前一定要先查過餘額」「5 分鐘內轉帳總額不能超過 3,000」。這類規則以前只能寫在 prompt 裡，或是由後端自己記狀態。
- **它的 session 比 08 本文寫的安全一點：** session 的 key 包含呼叫者的身分，**兩個不同的呼叫者就算用同一個 session ID，也是分開的 session**。但同一個呼叫者換一個 session ID，計數就會重來，這一點沒變。
- **所以 temporal policy 適合用來做「流程正確性」，不適合做「防濫用的總量控制」**。後者要用 Gateway 的 rate limit（以 JWT 的 `sub` 為維度）或後端自己的額度系統。
- **新增或修改 temporal policy，會讓 engine 上所有進行中的 session 失效**，下一個請求收到 409。Client 必須能「換一個新的 session ID 重送」，而且**歷史會歸零**，流程得從頭走。上線 policy 變更要挑離峰時段。

## Dogwood 的基本元素

| 元素 | 說明 |
|---|---|
| 事件種類 | `::request`（呼叫已被授權，只有 input）、`::response`（工具執行成功，有 input 和 output）、`::error`（被拒絕或工具出錯，只有 input） |
| 時間運算子 | `formerly within`（過去某個時間點發生過）、`since within`（從某事件之後一直成立）、`count`、`sum` |
| 時間窗 | `s`、`m`、`h`、`d`，**最長 24 小時** |
| 必要條件 | 每個事件比對都要帶 `eventResource: resource` |
| 寫在哪裡 | `CreatePolicy` 的 `definition.policy.statement`（一般 Cedar 則放在 `definition.cedar.statement`） |

## 常見模式

以下範例來自官方文件，resource 的 ARN 以 `…` 省略。

### 1. 先查詢再操作（順序）

「轉帳的目標帳戶，必須是 1 小時內查詢餘額時**真的回傳過**的帳戶」：

```
permit (principal, action == AgentCore::Action::"FundsTarget___transfer_funds", resource == …)
when temporal {
    formerly within 1h AgentCore::Action::"FundsTarget___get_account_balance"::response{
        eventResource: resource,
        output.accountId: context.input.toAccount
    }
};
```

- **這條比「先呼叫過查詢」更強：** 它比對的是**查詢工具的輸出**。模型就算捏造一個帳號，也不會出現在過去的 response 裡，所以會被擋下。這是 temporal policy 最有價值的用法之一：**用工具的真實輸出，驗證模型後續的輸入**。
- 只要求「呼叫過」就用 `::request`，要求「成功完成」就用 `::response`。

### 2. 核准一次、只能用一次

「查過餘額之後，只能轉帳一次；要再轉就得重新查」：

```
when temporal {
    !AgentCore::Action::"FundsTarget___transfer_funds"::response{ eventResource: resource }
    since within 1h AgentCore::Action::"FundsTarget___get_account_balance"::response{ eventResource: resource }
};
```

- 對應到業務上的「主管核准」：把核准做成一個工具（例如 `approve_refund`，只有主管的 JWT 才能呼叫，用一般 Cedar 控制），執行退款的 policy 再要求「核准之後還沒退過款」。
- ⚠️ **核准者和執行者是不同的 principal 時，這個模式行不通（推論）。** 因為 session 的 key 包含身分，主管的核准事件記在主管的 session，不會出現在客服的 session 裡。這種跨人的核准流程，要由後端的工作流系統處理，policy 只負責驗證「這筆請求帶有有效的核准單號」。

### 3. 總額上限

「5 分鐘內，轉帳總額達到 3,000 就拒絕」：

```
forbid (…transfer_funds…) when temporal {
    exists (total: Long).
        (sum amt for (amt: Long), (t: Timepoint).
            where (formerly within 5m (AgentCore::Action::"FundsTarget___transfer_funds"::request{
                eventResource: resource, input.amount: amt } && tp(t)))) == total
        && total >= 3000
};
```

- **`(t: Timepoint)` 和 `tp(t)` 不能省。** Dogwood 的聚合會把重複的值去重，少了時間點，兩筆相同金額的轉帳只會算一次。
- **`count` 和 `sum` 都包含目前這一筆請求。**
- **金額要用整數（`Long`）。** JSON 的 `number` 會被轉成 `Decimal`，而 `sum` 只能加 `Long`（推論，理由見 [prompt-to-policy](prompt-to-policy.md#工具-schema-怎麼轉成-cedar-型別)）。這又是一個「工具 schema 要為 policy 設計」的例子。

### 4. 次數上限、冷卻、互斥

- **次數上限：** 跟總額同樣的寫法，把 `sum` 換成 `count`。
- **冷卻時間：** 對同一個工具的 `::response` 寫 `formerly within 1m`，搭配 `forbid`。
- **互斥：** 兩條對稱的 `forbid`，例如「做過 A 就不能做 B」，反過來也一樣。
- **拒絕後封鎖：** 比對 `::error` 事件，例如「被拒絕過一次高風險操作，這個 session 之後都不准再試」。

## 最容易踩的陷阱

1. **前置步驟也要有 `permit`（官方範例稱為 dependency trap）。** 如果「查詢餘額」這個工具本身沒有被 permit，它的呼叫會被記成 `error`，`::response` 永遠比對不到，後面的轉帳也就永遠被擋。
2. **`response` 是在工具完成後「稍晚」才寫進歷史的。** 模型如果**平行**呼叫查詢和轉帳，或是一收到回應就立刻送出下一個呼叫，轉帳可能因為還看不到查詢紀錄而被錯誤拒絕。Agent 端要確保依賴的步驟是**依序**執行（推論：大多數框架預設會平行呼叫多個工具，需要在 prompt 或框架設定裡限制）。
3. **同一個 session 的 temporal 評估是序列化的：** 官方範例說每個 session ID 同一時間只做一個 temporal 評估。session 切得太粗（例如一整天共用一個 ID），並發請求就會互相等待（官方文件沒寫，出自範例說明）。
4. **Temporal 運算子不能巢狀超過一層**；每條 policy 最多 3 個 temporal 運算子；每個 engine 最多 20 條 temporal policy。
5. **不能引用過去的 guardrail 分數。**

## Session 的識別：重新檢視弱點

| 項目 | 內容 |
|---|---|
| 來源 | Header `x-amzn-bedrock-agentcore-policy-session-id`，**由呼叫端產生**（建議 UUIDv4） |
| 格式 | 1–128 個 `[A-Za-z0-9-]` 字元，其他格式回 400 |
| 生命週期 | 隱式建立；最後一次活動後閒置 24 小時就刪除；**不能主動關閉** |
| **Key 包含身分** | 官方原文：「Two different callers supplying the same session ID get isolated sessions — the identity is part of the session key」 |
| 例外 | Gateway 的 inbound 驗證設成 `NONE` 時，所有呼叫者共用同一個 session ID 的事件歷史（官方稱為「advisory only」） |
| 經過 Runtime 時 | session 資訊會放進 Workload Access Token（15 分鐘有效），**只要在第一個請求帶 header**；僅限同帳號、同區域 |

⚠️ **文件與範例矛盾：** 官方文件說 Gateway 不會代為產生 session ID，沒帶就回驗證錯誤；官方範例 repo 的 FAQ 卻說「省略 header 時 Gateway 會建立 session 並在回應 header 回傳 ID」。以文件為準，但**client 兩種情況都要能處理**。

### 弱點在哪裡、怎麼補

「每個 session 最多 N 次」的真正風險是：**同一個使用者換一個 session ID，計數就歸零。** 攻擊者（或被 prompt injection 操控的 agent）不需要冒用別人的身分，只要換 ID 就行。

| 補強方式 | 做法 | 能擋什麼 | 擋不住什麼 |
|---|---|---|---|
| **session ID 由後端產生** | 前端不能指定；後端（或你自己的 Runtime 程式）依照「使用者 + 業務流程」產生 ID，例如一張退款單對應一個 session | 前端或使用者自己換 ID | 後端或 agent 程式本身被操控 |
| **Gateway rate limit** | 以 `$.context.jwt.sub` 為維度設定每分鐘次數 | **跨 session 的總量**，這是真正的防濫用 | 金額加總（rate limit 只算次數和 token） |
| **後端額度系統** | 退款 API 自己檢查使用者當日累計 | 一切繞過 agent 的路徑 | —（最終防線） |
| **`::error` 封鎖** | 被拒絕過一次高風險操作，就封鎖該 session | 同一個 session 內反覆試探 | 換 session 之後 |

**判斷：** 把 temporal policy 定位成「**確保 agent 照著流程走**」，而不是額度控管。真正的金額上限，一定要在後端的業務系統裡再檢查一次。

- **Gateway rate limit 是 fail-open 的**（見 [03](../03-gateway/README.md)）：限流器逾時就放行，JWT 缺少對應的 claim 時整條限制會被略過。所以它是「品質保護」，也不能當成唯一的安全控制。

## 修改 policy 時的 409

### 發生什麼事

- **新增或修改 temporal policy**（包括新增或移除 temporal 運算子），會讓這個 engine 上**所有進行中的 session 失效**。之後用舊 session ID 送來的請求，會收到 **HTTP 409 ConflictException**。
- **用同一個 session ID 重試沒有用**，必須換一個新的 ID，而且**新 session 的歷史是空的**。
- 官方範例說**刪除** temporal policy 也會造成失效，AWS 文件沒提到刪除的情況。保險起見，視為會。

### Client 怎麼處理

```
送出請求（帶 session ID）
  └─ 收到 409 ConflictException
       ├─ 產生新的 session ID
       ├─ 判斷這個流程需不需要重走前置步驟
       │    （例如轉帳前的「查詢餘額」，在新 session 裡還沒發生過）
       └─ 從流程的起點重新執行，而不是只重送失敗的那一步
```

- **只重送失敗的那一步通常會被拒絕**：新 session 裡沒有前置步驟的紀錄，`formerly` 的條件不會成立。所以 409 的處理不能放在 HTTP client 的通用重試裡，要讓 **agent 知道「流程要重來」**（推論）。
- 實務上最簡單的做法：把 409 轉成一個給模型看的錯誤訊息，例如「授權狀態已重置，請重新查詢餘額後再試」，讓模型自己重走流程。

### 控制面的 409 是另一回事

| 情況 | 409 的原因 | 處理 |
|---|---|---|
| 資料面（呼叫工具） | 用了已失效的 session | 換新的 session ID、重走流程 |
| 控制面（`CreatePolicy`） | policy 名稱已存在 | 用 `clientToken` 做冪等，或先查是否已存在 |
| 控制面（policy 還在 `UPDATING` 時又改） | 文件沒有列出，**需實測** | 等 `policy_active` waiter（每 5 秒查一次，最多 24 次）後再改 |

### 上線 policy 變更的建議流程（判斷）

1. **避開尖峰時段。** 每次變更都會打斷所有進行中的流程。
2. **合併變更，減少部署次數。** 修改 10 條 policy 分 10 次部署，就會打斷 10 次。
3. **Policy 變更生效是最終一致的**，官方說「幾秒內」。變更後的幾秒內，不同的請求可能看到新舊不同的版本。
4. **沒有版本管理：** API 沒有版本欄位，更新就是直接覆蓋。要能回滾，就得在 Git 裡保留舊版，回滾時重新 `UpdatePolicy`，**而回滾本身又會再觸發一次 409**。

## 成本

- 授權請求每次 $0.000025。定價頁說**每個 engine 前 100 條 temporal policy 不另外收授權費**。
- ⚠️ **這跟配額矛盾：** 配額是每個 engine 最多 20 條 temporal policy，定價頁卻寫前 100 條免費。以配額為準，20 條以內都不會多收費。

## 參考資料

- [Temporal policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html)、[Authoring](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal-authoring.html)
- [Session-based temporal policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-session-based-temporal.html)
- [Errors](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-use-errors.html)、[Test a policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-test-a-policy.html)
- [Dogwood guide](https://dogwood-policy.github.io/dogwood/)
- [awslabs/amazon-bedrock-agentcore-samples：03-temporal-policies](https://github.com/awslabs/amazon-bedrock-agentcore-samples)（`01-features/07-centralize-and-govern-your-ai-infrastructure/02-policy/`）
- [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
