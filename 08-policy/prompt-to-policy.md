# 延伸：把業務規則從 prompt 搬到 Policy

> 接續 [08-policy](README.md)。這篇討論：怎麼從現有 agent 的 system prompt 挑出「必須被強制執行」的規則，改寫成 Cedar；工具的參數 schema 要怎麼設計，policy 才引用得到；以及怎麼在本機先驗證 policy，不用每次都部署到 Gateway 才知道寫錯。
>
> 資料查核日期：2026-09-30。標示「推論」的部分是官方文件沒有明說、由我根據文件或開源實作推導出來的。
>
> 本機實驗：[experiments/prompt-to-policy](experiments/prompt-to-policy/)（已實跑，全部通過）。

## 結論先講

- **分類標準只有一條：「模型不照做時，後果能不能接受？」** 不能接受的，例如金額上限、資料歸屬、地區限制，就搬到 policy。能接受的，例如語氣、格式、回答風格，就留在 prompt。
- **Policy 只看得到工具呼叫的參數和呼叫者身分**，看不到對話內容。所以規則能不能搬過去，**取決於工具的參數有沒有帶到判斷所需的欄位**。很多規則搬不過去，原因不在 Cedar，而在工具設計。
- **工具 schema 要為 policy 設計：** 金額用整數（分），避免 `number` 被轉成小數；「是誰的資料」要是明確的欄位；會被 policy 引用的欄位盡量設成必填。
- **寫錯的 policy 在 AgentCore 上不一定會被擋下：** 例如引用了非必填欄位卻沒先用 `has` 檢查，可能照樣建立成功，到執行時才一律回 403。**在本機用 Cedar validator 就能先抓出來**，本篇的實驗已經驗證過。

## 第一步：盤點 prompt 裡的規則

以一個客服 agent 的 system prompt 為例，逐句分類：

| Prompt 裡的句子 | 類型 | 模型不照做的後果 | 處理方式 |
|---|---|---|---|
| 「單筆退款不能超過 500 美元，主管可以到 5,000」 | 業務約束 | 直接損失金錢 | **Cedar**（數值比較 + 角色 tag） |
| 「只能處理使用者本人的訂單」 | 安全約束 | 越權存取他人資料 | **Cedar**（`customerId` 跟 `principal.id` 比對） |
| 「只服務美國和加拿大」 | 業務約束 | 違反法規或合約 | **Cedar**（`contains`） |
| 「退款一定要記錄原因」 | 稽核要求 | 稽核缺漏 | **Cedar**（`has`）或直接在 schema 設成必填 |
| 「退款前先查詢訂單狀態」 | 流程約束 | 對已退款的訂單重複退款 | **Temporal policy**（見 [temporal 延伸](temporal-workflows.md)） |
| 「不要在回覆裡透露其他客戶的資料」 | 安全約束 | 個資外洩 | 部分可以靠 `suppressOutput`（見 [guardrails 延伸](guardrails-calibration.md)），但**根本做法是讓工具不要回傳別人的資料** |
| 「回答要禮貌，用繁體中文」 | 風格 | 體驗不佳 | **留在 prompt** |
| 「不確定時先反問使用者」 | 行為引導 | 體驗不佳 | **留在 prompt** |

**判斷：**

- 搬到 policy 之後，**prompt 裡的規則仍然可以保留**。保留的目的不同：prompt 讓模型「一開始就不會去做」，減少被拒絕後的重試與糟糕體驗；policy 則保證「真的做了也會被擋」。兩者並不衝突。
- **Policy 擋下的請求，模型會收到錯誤。** 如果 prompt 沒有說明規則，模型可能一直換參數重試。所以保留一句「超過 500 美元請轉主管」，體驗會好很多（推論）。

## 第二步：確認規則引用得到需要的欄位

### Policy 能讀到什麼

| 來源 | 寫法 | 說明 |
|---|---|---|
| 工具參數 | `context.input.<欄位>` | 由 Gateway 依工具的 `inputSchema` 自動產生型別 |
| 呼叫者（OAuth） | `principal.id`、`principal.getTag("<claim>")` | `principal` 的型別是 `AgentCore::OAuthUser`，`id` 就是 JWT 的 `sub`，其他 claim 都放在 **tag**。不能加自訂屬性，只能用 tag |
| 呼叫者（IAM） | `principal.id` | `AgentCore::IamEntity`，`id` 是 assumed-role 的 ARN，**沒有 tag** |
| 目前時間 | `context.system.now` | 用來寫時段限制 |
| 工具輸出 | `context.output.<欄位>` | **只能在 guardrail 條件和 temporal 的歷史事件裡用** |

⚠️ **文件矛盾：** schema 限制頁寫「Only available context is `context.input`」，時間規則頁卻有 `context.system.now`。以實際能用的為準，建議上線前在 `LOG_ONLY` 下確認。

- **Claim 一律是字串 tag：** Dogwood 的範本宣告為 `tags String`。陣列型的 claim（例如 `cognito:groups`）會怎麼編碼，文件沒寫；官方的 scope 範例用的是 `principal.getTag("scope") like "*refund:write*"`，也就是把空白分隔的字串當成整體比對（推論：陣列型 claim 也會被轉成字串，需要實測）。
- **所以「角色」或「負責哪些客戶」這類資訊，要嘛放進 JWT claim，要嘛放進工具參數。** Policy 沒辦法自己去查資料庫。

### 工具 schema 怎麼轉成 Cedar 型別

官方的對照表：

| JSON Schema | Cedar | 要注意的地方 |
|---|---|---|
| `string` | `String` | |
| `integer` | `Long` | **比較、加總都用得到，最推薦** |
| `number` | `Decimal` | 會被截斷到 Cedar 的精度（小數點後 4 位）；temporal 的 `sum` 只能加 `Long`（推論：`number` 欄位沒辦法累加） |
| `boolean` | `Bool` | |
| `object` | `Record` | `required` 決定哪些欄位是必填 |
| `array` | `Set` | **順序會消失**，重複值也會合併 |
| `null` | `Entity` | 很難在 policy 裡使用 |

開源的 schema generator（`cedar-for-agents`）還有幾條規則，**AgentCore 沒有明說是否相同**（推論，需要實測）：

- **`enum` 會變成列舉的 entity 型別，而不是字串。** 官方範例只用普通字串比對，例如 `context.input.claimType == "health"`。保險起見，**會被 policy 引用的欄位先不要用 `enum`**，改用字串，再在 policy 裡用 `["a","b"].contains(...)` 限制。
- `format: date-time` 會變成 `datetime`，`ipv4` 會變成 `ipaddr`，其他 format 都當成字串。
- `anyOf` / `oneOf` 會變成一堆可選的 `typeChoiceN` 欄位，policy 幾乎沒辦法寫。
- `$ref` 只支援 `#/$defs/...`。

### 為 policy 設計工具 schema 的原則

1. **金額用整數的「分」**（`amountCents: integer`），不要用 `amount: number`。
2. **資料歸屬要是明確的欄位**，例如 `customerId`。policy 才能比對「這筆資料是不是呼叫者的」。更好的做法是**後端 API 自己也驗一次**，policy 只是多一道防線。
3. **會被 policy 引用的欄位設成必填。** 非必填的欄位，每條 policy 都要先寫 `context.input has x`，漏寫就會出事（見下一節）。
4. **不要用 `anyOf` / `oneOf`、自由格式的 object**，policy 沒辦法可靠地引用。
5. **一個工具只做一件事。** 一個 `manage_order(action: "refund" | "cancel" | "query")` 的萬用工具，所有規則都要先判斷 `action`；拆成三個工具，policy 可以直接用 action 名稱區分，也能用 target 分組。

## 第三步：改寫成 Cedar

### Action 名稱與寫法限制

| Target 類型 | Action 名稱 | 例子 |
|---|---|---|
| MCP 工具 | `<Target>___<Tool>` | `OrderTarget___process_refund` |
| Runtime（HTTP） | `<Target>___<METHOD>:/invocations` | |
| HTTP proxy | `<Target>___<METHOD>:<uri>` | `MyAPI___POST:/inference/v1/chat/completions` |

- **不能用萬用字元比對 action。** 要一次涵蓋多個工具，就把它們放在同一個 target，然後用 `action in AgentCore::Action::"<Target>"`。所以**target 的切分，本身就是 policy 的分組設計**。
- **指定了 action 的 policy，resource 必須是特定的 gateway ARN。** 這代表要先建立 gateway 拿到 ARN，才能寫 policy。官方的入門教學因此需要部署兩次。

### 實際改寫

以上面盤點出的四條規則為例（完整檔案見[實驗](experiments/prompt-to-policy/policies.cedar)）：

```cedar
// 一般使用者：上限 500 美元、只限美加、一定要有原因
permit (
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"OrderTarget___process_refund",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:...:gateway/demo"
) when {
  context.input.amountCents <= 50000 &&
  ["US", "CA"].contains(context.input.country) &&
  context.input has reason
};

// 只能退自己的訂單，主管例外；forbid 優先於任何 permit
forbid (
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"OrderTarget___process_refund",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:...:gateway/demo"
) when {
  context.input.customerId != principal.id
} unless {
  principal.hasTag("role") && principal.getTag("role") == "supervisor"
};
```

寫法上的原則：

- **「允許什麼」用 `permit`，「絕對不行」用 `forbid`。** Cedar 預設拒絕，而且 `forbid` 永遠優先。所以「只能退自己的訂單」這種不論角色、額度都必須成立的規則，寫成 `forbid` 最安全：之後就算有人新增了一條過寬的 `permit`，也繞不過它。
- **讀取 tag 前一定要先 `hasTag`**，讀取非必填欄位前一定要先 `has`。
- **每個工具都要有 `permit`。** Cedar 預設拒絕，漏寫的工具會全部被擋。

## 第四步：在本機先驗證

AgentCore 在建立 policy 時會做 schema 檢查和自動推理（例如標出「永遠允許」的 policy），但有兩個問題：

1. **驗證是非同步的：** `CreatePolicy` 先回 202，之後狀態才變成 `CREATE_FAILED`，錯誤原因要另外查。
2. **有些錯誤在建立時抓不到：** [08](README.md) 已經提到，policy 引用了請求沒帶的欄位時，policy 可以照樣變成 `ACTIVE`，**到執行時才回 403**。執行時的型別不符會出現在 `PolicyMismatch` metric 和 `aws.agentcore.policy.mismatched_policies` span 屬性裡。

**本機驗證的做法：** 用開源的 Cedar（這裡用 Python 的 `cedarpy`，底層是 Cedar 4.x）加上一份仿照 AgentCore 結構的 schema，跑兩件事：

1. **Schema 驗證：** 確認 policy 引用的欄位、型別都正確，並抓出「非必填欄位沒先檢查」這類錯誤。
2. **授權案例測試：** 像寫單元測試一樣，列出「誰、用什麼參數、預期允許還是拒絕」。

實際跑出來的結果（`python run.py`）：

```
[validate] policies.cedar   -> PASS
[validate] bad-policy.cedar -> FAIL（預期會失敗）
    unable to guarantee safety of access to optional attribute `input.reason` in context ...

✓ alice 退自己的 $120           want=Allow got=Allow
✓ alice 退 $500.01              want=Deny  got=Deny
✓ alice 退 mallory 的訂單       want=Deny  got=Deny  by=forbid
✓ bob（主管）退別人 $3,000      want=Allow got=Allow
...（共 10 個案例）
ALL PASS
```

- **`bad-policy.cedar` 就是 08 提到的那個陷阱：** 直接寫 `context.input.reason != ""`，沒有先 `has`。Cedar 的 validator 在本機就能抓出來。
- **限制（推論）：** 本機的 schema 是手寫的近似版本。真正的 schema 由 Gateway 從工具的 `inputSchema` 產生，細節（例如 `enum`、巢狀物件）可能不同。建議做法是：**CI 跑本機測試，確認邏輯正確；部署後再用 `LOG_ONLY` 對照正式流量，確認跟 AgentCore 的實際 schema 一致。**
- **Temporal policy（Dogwood）和 guardrail 條件，本機的 Cedar 跑不了**，只能在 AgentCore 上用 `LOG_ONLY` 測試。

## 上線流程建議

```
盤點 prompt 規則 → 調整工具 schema → 寫 Cedar → 本機 validator + 案例測試（CI）
   → 部署 gateway → 建立 policy（validationMode 用預設的 FAIL_ON_ANY_FINDINGS）
   → engine 用 LOG_ONLY 觀察 LogOnlyDecisionFlips → 切到 ENFORCE
```

- **`validationMode` 保留預設的 `FAIL_ON_ANY_FINDINGS`。** 它除了檢查 schema，還會做整個 engine 的語意分析，標出「過寬」「過嚴」「無效」的 policy。只有在確定要接受這些警告時，才改成 `IGNORE_ALL_FINDINGS`。
- **工具 schema 改了之後，既有的 policy 會怎樣，文件沒寫。** 保險做法是：改工具 schema 的變更，一律重跑本機測試，部署後檢查 `PolicyMismatch` metric。

## 更正與補充（對 08 本文）

- **每條 policy 還有自己的 `enforcementMode`（`ACTIVE` 或 `LOG_ONLY`）**，跟 gateway 層級的 `ENFORCE` / `LOG_ONLY` 是兩件事，而且 gateway 層級優先。這代表**除了 `UpdateGateway`，有 `UpdatePolicy` 權限的人也能把單一條 policy 改成只記錄不攔截**。08 提到的「最弱的一環」要把這個權限也算進去。
- **Policy 沒有版本管理：** API 沒有 version 欄位，`UpdatePolicy` 直接覆蓋。**版本管理要靠你自己的 Git**，這也是為什麼本機測試值得做。

## 限制與配額

| 項目 | 值 |
|---|---|
| 單條 policy 大小 | 10 KB（約 10,000 字元） |
| 每個 engine 的 schema 大小 | 400 KB（所有 gateway 合計）；超過要拆 engine 或移除用不到的工具 |
| 每個 engine 的 policy 數 | 1,000 |
| Policy 名稱 | `[A-Za-z][A-Za-z0-9_]*`，最長 48 字元（**不能用 `-`**） |
| 控制面 API 速率 | Create/Update/Delete/Get/List Policy 5 TPS；engine 相關 1 TPS；**都不能調整** |

控制面速率很低，**用 IaC 一次建立上百條 policy 時要做好節流與重試**。

## 參考資料

- [Schema constraints](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-schema-constraints.html)、[Policy scope](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-scope.html)
- [Conditions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-conditions.html)、[Time-based policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-time-based.html)
- [Common patterns](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-common-patterns.html)、[Example policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/example-policies.html)
- [Authorization flow](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-authorization-flow.html)
- [Create/update validation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-create-update-validation.html)、[Test a policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-test-a-policy.html)
- [Policy metrics](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html)、[Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)
- [cedar-policy/cedar-for-agents](https://github.com/cedar-policy/cedar-for-agents)（開源的 MCP schema generator）
- [cedarpy](https://pypi.org/project/cedarpy/)（Cedar 的 Python 綁定，本篇實驗使用 4.12.1）
