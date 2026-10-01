# Policy

> 用 Cedar（以及相容 Cedar 的 Dogwood）在 Gateway 上，對每一次工具呼叫做**確定性**的允許或拒絕判斷；還能依 session 的歷史紀錄（temporal）或 Guardrails 的分數下決策。
>
> 資料查核日期：2026-09-30。Gateway 端的驗證與治理手段見 [03](../03-gateway/)；Memory 的 FGAC 範例見 [02](../02-memory/README.md#權限控制的三道防線)。

## TL;DR

- **為什麼需要：** 在 system prompt 裡寫「退款不能超過 $500」**不是安全控制**，因為模型可能不遵守，也可能被 prompt injection 騙過。Policy 把這類規則**移到模型外面**，在 Gateway 上用程式規則判斷，**模型說什麼都繞不過去**。
- **評估的模型：**
  - principal（誰）＝ JWT 的 `sub` 加上 claim（`AgentCore::OAuthUser`），或 IAM ARN（`AgentCore::IamEntity`）。
  - action（做什麼）＝ 工具名稱，例如 `RefundTool___process_refund`。
  - resource（在哪裡）＝ gateway 的 ARN。
  - context ＝ **工具的參數**（`context.input.amount`）。
  - **預設拒絕，forbid 優先於 permit。**
- **Cedar 的 schema 會從 gateway 的工具定義自動產生：** 建立 policy 時就會先驗證，如果引用了不存在的工具或欄位會直接擋下；另外還用**自動推理**找出「永遠允許」或「永遠拒絕」這類有問題的 policy。
- **三個超越傳統存取控制的能力：**
  - **Temporal**（Dogwood）：「必須先驗證身分才能退款」「一小時內最多 N 次」這類**有狀態**的規則。
  - **Guardrails in policy**：用 Bedrock Guardrails 的分數擋下 prompt injection 或個資外洩；還有新的 **`suppressOutput`** 效果，工具輸出違規時**整個拿掉**（不是只遮掉部分內容，見[延伸](guardrails-calibration.md#suppressoutput-實際上做什麼)）。
  - **用自然語言撰寫**（NL2Cedar）：用一般的語言描述規則，由服務轉成 Cedar。
- **上線流程：** 先用 `LOG_ONLY` 模式觀察，再切換到 `ENFORCE`。⚠️ **有 `UpdateGateway` 權限的人，就能把模式切回 `LOG_ONLY`，甚至直接拔掉整個 policy engine**，沒有其他 condition key 可以另外保護。每條 policy 也有自己的 `enforcementMode`，所以 **`UpdatePolicy` 權限同樣能讓單條 policy 失效**（見[延伸](prompt-to-policy.md#更正與補充對-08-本文)）。

## 為什麼不能只靠 prompt？

| 做法 | 問題 |
|------|------|
| 在 system prompt 寫規則 | 模型是機率性的，**不保證遵守**；惡意輸入可以誘導它違反規則 |
| 在每個工具的後端程式裡檢查 | 可行，但規則散落在各個服務，**難以一致、難以稽核**；而且後端不一定知道「是哪個使用者透過哪個 agent 在呼叫」 |
| **在 Gateway 上用 Policy** | 所有工具呼叫都經過同一個檢查點；規則是宣告式的，可以驗證、可以版本控管；**跟模型的行為完全無關** |

可以類比成：**IAM policy 之於 AWS API**，就是 **AgentCore Policy 之於 agent 的工具呼叫**。

## 核心概念

### 一次授權請求長什麼樣子

```
JWT（sub = 1234…, role = admin, department = finance）
  + MCP tools/call { name: "RefundTool___process_refund", arguments: { amount: 450, orderId: "12345" } }
        │
        ▼  Gateway 組成 Cedar 的授權請求
principal = AgentCore::OAuthUser::"1234…"      （JWT 的 claim 會成為 tag：principal.getTag("role")）
action    = AgentCore::Action::"RefundTool___process_refund"
resource  = AgentCore::Gateway::"arn:…:gateway/refund-gateway"
context   = { input: { amount: 450, orderId: "12345" } }
        │
        ▼  policy engine：預設拒絕、forbid 優先
ALLOW → 呼叫後端 ／ DENY → 回傳 isError: true，並附上 "AuthorizeActionException – Tool Execution Denied…"
```

### 範例

```cedar
// 只有 finance 部門的 admin 能退款，而且金額要小於 500
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"RefundTool___process_refund",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-west-2:123456789012:gateway/refund-gateway"
) when {
  principal.hasTag("role") && principal.getTag("role") == "admin" &&
  principal.hasTag("department") && principal.getTag("department") == "finance" &&
  context.input.amount < 500
};

// 緊急停用某個工具（forbid 會壓過所有 permit）
forbid(principal, action == AgentCore::Action::"RefundTool___process_refund", resource);
```

其他常見的模式：用 `forbid(principal, action, resource);` 一次停用整個 gateway；依使用者或帳號封鎖；限定國家或地區的白名單；要求參數一定要存在（`context.input has shippingAddress`）；依時間限制（`context.system.now`）。

### `tools/list` 也會被過濾

- 列出工具被視為一種「**meta action**」。**只要在任何情況下有可能被允許**，這個工具就會出現在清單裡。
- 所以**出現在清單上，不代表呼叫一定會成功**。例如：有權限使用退款工具，但金額超過上限時，呼叫仍然會被拒絕。
- 好處是：agent 看不到自己完全不能用的工具，**可以省下 token，也少了被誘導去嘗試的機會**。
- Policy **只作用在 MCP 的 tools**，prompts 和 resources 永遠放行。

## 進階能力

### 1. Temporal policy（Dogwood）：有狀態的規則

**Cedar 只看當下這次請求。** 但 agent 的安全規則常常跟「**之前做過什麼**」有關，例如：

- 退款之前一定要先呼叫過 `verify_identity`。
- 賣股票之前，一小時內一定要有對應的核准紀錄。
- 同一個 session 內，轉帳總額不能超過 $10,000。

Dogwood 是**相容 Cedar** 的開源語言，加上了 temporal 運算子：`formerly within`（在時間窗內曾經發生過）、`since within`（從某個事件之後一直成立）、`count`、`sum`。

```
permit (principal, action == AgentCore::Action::"TradingTarget___SellShares", resource == …)
when temporal {
  formerly within 1h AgentCore::Action::"TradingTarget___ApproveSale"::response{
    eventResource: resource,
    input.stock:   context.input.stock,
    input.shares:  context.input.shares,
    output.approved: true
  }
};
```

| 重點 | 內容 |
|------|------|
| Session 的識別 | **由呼叫端自己產生**，放在 `x-amzn-bedrock-agentcore-policy-session-id` header；**Gateway 不會代為產生**；engine 裡有 temporal policy 時，**沒帶這個 header 會直接回錯誤** |
| 被拒絕的動作不算「做過」 | 被拒絕的動作會被記錄成 `error` 事件，只比對 `response` 的條件永遠不會匹配到它 |
| 修改 policy 會讓進行中的 session 失效 | 新增或修改 temporal policy 後，進行中的 session 會收到 **409**，要開一個新的 session |
| 呼叫鏈 | 必須在**同一個帳號、同一個區域**；Workload Access Token 要隨著請求一路傳遞（Gateway 和 Runtime 之間會自動處理）；gateway 的 role 需要 `GetWorkloadAccessToken` 權限 |
| 配額 | 每個 engine 最多 20 個 temporal policy；每個 policy 最多 3 個 temporal 運算子；時間窗最長 24 小時 |
| ⚠️ 安全限制 | **Session ID 是呼叫端提供的**，所以「每個 session 最多 N 次」這種限制，**只要換一個 session ID 就重新計算**，不能當作跨 session 的限流。不過 session 的 key 包含呼叫者身分，**不同的呼叫者就算用同一個 ID，也不會共用歷史**（inbound 驗證為 `NONE` 時例外，見[延伸](temporal-workflows.md#session-的識別重新檢視弱點)） |
| 區域 | 東京、新加坡、雪梨、首爾、孟買等都支援 |

### 2. Guardrails in policy

把 Bedrock Guardrails 當成「**資訊提供者**」，在 policy 裡依它給的分數做決定：

| 類型 | 類別 | 預設門檻（只在用自然語言產生 policy 時套用） |
|------|------|---------|
| `ContentFilter` | 暴力、仇恨、色情、不當行為、侮辱 | 0.2 |
| `PromptAttack` | JAILBREAK、**PROMPT_INJECTION**、PROMPT_LEAKAGE | 0.4 |
| `SensitiveInformation` | 信用卡號、Email、電話、地址、AWS key、密碼…（20 多種） | 0.2 |

```
// 工具的輸入疑似 prompt injection 就拒絕
forbid (principal, action == …, resource) when guardrails {
  BedrockGuardrails::PromptAttack(["PROMPT_INJECTION"], [context.input.prompt])["PROMPT_INJECTION"]
    .confidenceScore.greaterThan(decimal("0.6"))
};

// 工具的輸出含有美國社會安全號碼，就把整個輸出拿掉（新的 suppressOutput 效果）
suppressOutput (principal, action == …, resource) when guardrails {
  BedrockGuardrails::SensitiveInformation(["US_SOCIAL_SECURITY_NUMBER"], [context.output.text])["US_SOCIAL_SECURITY_NUMBER"]
    .confidenceScore.greaterThan(decimal("0.5"))
};
```

- **Policy 本身是確定性的，但 guardrail 的分數不是：** 同樣的輸入，分數可能不同。
- **門檻的校準方式：** 先用 `LOG_ONLY` 收集分數，搭配人工或 LLM 標註，畫出混淆矩陣，再依照你對誤擋和漏擋的容忍度選擇門檻。
- **限制：**
  - `when guardrails {…}` 裡不能混用一般的 Cedar 條件。
  - `suppressOutput` 只能搭配 guardrail 條件使用。
  - 分數目前只有 0、0.2、0.4、0.6、0.8、1.0 幾種離散值。
  - **支援的區域很少**：亞太只有東京和雪梨。
- 適用範圍：MCP 工具、HTTP runtime target、inference target 都可以使用。

### 3. 用自然語言撰寫（NL2Cedar）

- 輸入「允許 refund-agent 在金額小於 500 美元時處理退款」這類句子，服務會依照 gateway 的 schema 產生 Cedar，並驗證語法、執行自動推理檢查。
- **跨區域推論：** 推論會在同一個地理區內跨區域處理，例如 APAC 的請求留在 APAC。
- 計費：每千個 token $0.13。
- **判斷：** 產生出來的 policy 一定要經過人工審查，並放進版本控管；自然語言本身有歧義，官方也列出常見的錯誤，例如條件寫得太模糊、`and` 和 `or` 的優先順序沒講清楚。

## 驗證、測試與上線

1. **建立時驗證：** 用自動產生的 schema 檢查 action、欄位和型別；**自動推理**會標出「永遠允許」或「永遠拒絕」的 policy。
2. **`LOG_ONLY` 模式：** 只評估並記錄決策，不真的擋下請求。先觀察一段時間的正式流量，確認不會誤擋。
3. **切換到 `ENFORCE`。**
4. **保護 engine 的設定：** 把 `bedrock-agentcore:UpdateGateway` 和 `UpdatePolicy` 權限只給極少數人，並對 `policyEngineConfiguration` 的變更設 CloudTrail 警報。**這是整套機制最弱的一環。**

## 限制與配額

| 項目 | 值 |
|------|-----|
| Cedar 語言本身 | 沒有浮點數（decimal 最多 4 位小數）；沒有 regex，只有 `like` 搭配 `*` |
| 單一 policy 的大小 / 每個 resource 的 policy 總大小 | 10 KB / 200 KB |
| **Cedar schema 大小** | **400 KB**：由這個 engine 關聯的所有 gateway 的**所有工具**加總而成；工具多或參數結構複雜時容易超過，要拆成多個 engine |
| 每個 engine 的 policy 數 / 每個帳號的 engine 數 | 1,000 / 1,000 |
| 同一次呼叫不能同時引用 `context.input` 和 `context.output` | — |
| 控制面 API 的速率 | 很低，例如 `CreatePolicyEngine` 1 TPS、`CreatePolicy` 5 TPS，**不可調整** |
| 計費 | 每次授權檢查 $0.000025（每百萬次 $25）；NL2Cedar 每千個 token $0.13；Guardrails 另外依 Bedrock Guardrails 的價格計費 |

## 踩雷清單

1. **有 `UpdateGateway` 權限就能關掉或降級整個 Policy**，而且沒有額外的保護機制。
2. **`tools/list` 看得到不代表能呼叫**，實際呼叫時會依參數再判斷一次。
3. **Temporal 的 session ID 由呼叫端提供**，換一個 ID 就能重新計數，不能拿來做跨 session 的限流（要搭配 Gateway 的 rate limit 或後端額度）。
4. **修改 temporal policy 會讓進行中的 session 收到 409。**
5. **engine 裡有 temporal policy 時，沒帶 session header 的請求會直接失敗。**
6. **Guardrail 的分數是機率性的**，門檻要先用 `LOG_ONLY` 校準；而且亞太只有東京和雪梨支援。
7. **Cedar schema 的 400 KB 上限是所有 gateway 的工具加總**，工具一多就要拆 engine。
8. **Policy 只管 MCP tools**，prompts 和 resources 永遠放行。
9. **Memory FGAC 的 policy 如果引用了請求中沒有的欄位**，建立時不會報錯，但執行時會回 403（見 [02](../02-memory/README.md#權限控制的三道防線)）。

## 與其他元件的關係

- **Gateway（03）：** 唯一的執行點。Policy engine 掛在 gateway 上，Gateway 在呼叫後端之前先向 engine 詢問。**所以一定要確保流量不能繞過 Gateway**（見 [01 安全要點](../01-runtime/README.md#安全要點)）。
- **Identity（04）：** principal 和 tag 來自 inbound 的 JWT claim；temporal policy 依賴 Workload Access Token 的傳遞。
- **Memory（02）：** 透過 Gateway 的 Memory connector，用 Cedar 做 per-user 的 FGAC。
- **Observability（06）：** 有 `TemporalLatency` 等 metric，以及 policy 決策的 span 屬性；`LOG_ONLY` 模式的決策紀錄也在這裡。
- **Evaluations（07）：** 兩者互補。Policy 是**事前阻擋**，Evaluations 是**事後評分**。

## 研究問題

- [x] Cedar 語法基礎（principal / action / resource / context、permit / forbid、常見模式）
- [x] Policy engine 在 Gateway 的評估點（`tools/list` 過濾、`tools/call` 授權）
- [x] 如何用 JWT claim（例如 `cognito:groups`）做授權（claim 會變成 principal 的 tag）
- [x] Policy 的測試與版本管理（schema 驗證、自動推理、`LOG_ONLY`、NL2Cedar 的審查）
- [x] （補充）Temporal policy 與 Guardrails in policy

## 延伸調研

- [把業務規則從 prompt 搬到 Policy](prompt-to-policy.md)：規則盤點、為 policy 設計工具 schema、Cedar 改寫、本機驗證
- [用 temporal policy 控管業務流程](temporal-workflows.md)：順序、核准、總額上限的寫法與陷阱；session 弱點的補強；409 的處理
- [Guardrails in policy 的門檻校準與縱深防禦](guardrails-calibration.md)：用成本選門檻、`suppressOutput` 的實際行為、各層分工

## 實驗

- [Prompt 規則改寫成 Cedar](experiments/prompt-to-policy/)：用開源 Cedar 在本機驗證 schema 與 10 個授權案例，**已實跑、全部通過**
- [Guardrail 門檻校準工具](experiments/guardrail-threshold/)：輸入分數與標註，算出各門檻的混淆矩陣與成本；**目前只用合成資料驗證過**
- 依已購買能力過濾工具（`experiments/skill-gating/`，尚未建立）：將由 [WP2](../91-work-packages/WP2-capability-boundary.md) 以上面的 Cedar 案例為起點，在 AWS 上實測陣列型 claim 與 `tools/list` 過濾

## 參考資料

- [Core concepts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-core-concepts.html)、[Authorization flow](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-authorization-flow.html)
- [Common patterns](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-common-patterns.html)、[Limitations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-limitations-section.html)
- [Temporal policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html)、[Dogwood](https://dogwood-policy.github.io/dogwood/index.html)
- [Guardrails in policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-guardrails-in-policies.html)
- [Natural language policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-natural-language.html)
- [Use a gateway with policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/use-gateway-with-policy.html)、[Enforcement modes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-enforcement-modes.html)
- [Cedar](https://www.cedarpolicy.com/)

## 延伸調研方向

範圍在 00–08 之內，以 08 為主：

1. **把業務規則從 prompt 搬到 Policy 的設計方法：** 盤點現有 agent 的 system prompt 裡哪些是「安全或業務約束」，哪些是「風格或行為引導」；前者改寫成 Cedar 或 Dogwood；設計工具的參數 schema 時就考慮到 policy 要能引用哪些欄位。
2. **Temporal policy 的業務流程控管：** 「先驗證再操作」「核准後才能執行」「session 內的總額上限」等模式的實作；session ID 由呼叫端提供的弱點，要搭配 Runtime 的 session 綁定和 Gateway 的 rate limit 補強；以及修改 policy 時 409 的處理方式。
3. **Guardrails in policy 的門檻校準與縱深防禦：** 用 `LOG_ONLY` 收集分數、標註、畫混淆矩陣來選門檻；`suppressOutput` 在工具輸出遮罩個資的效果；以及它和 Runtime 的輸入驗證、Memory poisoning 防護、Evaluations 的安全評估器之間怎麼分工。
