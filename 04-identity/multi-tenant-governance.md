# 延伸：多租戶的 credential 與身分治理

> 接續 [04-identity](README.md#安全重點)。這篇討論：credential provider 只有 50 個的情況下，provider、workload identity、IAM role 要怎麼切分；怎麼禁用 `ForUserId` 這條不做驗證的路徑；以及怎麼從 CloudTrail 和 span 回答「誰替誰拿了哪張 token」。
>
> 資料查核日期：2026-09-30。標示「推論」的部分是官方文件沒有明說、由我推導的。IAM policy 範例**沒有在 AWS 上驗證過**。

## 結論先講

- **Credential provider 不是租戶的單位：** 預設每個帳號、每個區域 50 個（可以調高）。正常的設計是**每個第三方服務一個 provider**（例如 `google`、`slack`），由 vault 依「agent + 使用者」分開保存每個人的 token。
- **租戶隔離要靠「使用者 ID 的命名」和 IAM 條件，而不是靠資源數量：** 每個帳號、每個區域只有一個 vault、一個 identity directory，**vault 的 KMS 金鑰也只能設一把**。需要租戶各自一把金鑰、或完全的資料隔離，就要**分帳號**。
- **禁用 `ForUserId` 要分兩處：** 呼叫端 Deny `InvokeAgentRuntimeForUser`，自建 agent 的 role Deny `GetWorkloadAccessTokenForUserId`。對 Runtime 上的 agent，**只 Deny execution role 可能沒有效果**，因為 Runtime 是透過 service-linked role 取 token 的（推論）。
- **CloudTrail 回答不了「替誰」：** 取 token 的事件裡，workload access token 被遮蔽成 `HIDDEN_DUE_TO_SECURITY_REASONS`，看不到終端使用者。要用 **span** 或串接其他事件才能還原。

## 切分方式

### 資源層級與配額

| 資源 | 每個帳號、每個區域 | 能不能依租戶切 |
|---|---|---|
| Workload identity | 11,000 | 可以，但 Runtime / Gateway 會自動建立，通常一個 agent 一個 |
| Credential provider（OAuth2 / API key / Payment） | 各 **50**（可調高） | 可以，但很快會用完 |
| Token vault | **1 個**（`token-vault/default`） | 不行 |
| Vault 的 KMS 金鑰 | **1 把**（`SetTokenVaultCMK`） | 不行 |
| Identity directory | 1 個（`default`） | 不行 |

（vault 和 directory 只有一個，是從 API 結構推論的：建立 provider 時沒有指定 vault 的參數。）

### 三種切分模型

| 模型 | 做法 | 適合 | 代價 |
|---|---|---|---|
| **共用 provider**（建議預設） | 每個第三方服務一個 provider；使用者 ID 帶租戶前綴，例如 `tenantA+user123` | 大多數 SaaS：所有租戶用你公司註冊的同一個 Google / Slack app | 租戶之間只靠「使用者 ID」區分，錯了就會拿到別人的 token |
| **租戶自帶 OAuth app** | 每個租戶一個 provider（租戶在自己的 Okta、Entra 裡註冊 app，把 client ID / secret 給你） | 企業客戶要求用他們自己的 IdP 或 SaaS 租戶 | **50 個很快用完**，要申請調高；provider 名稱要帶租戶，例如 `acme-okta` |
| **每個租戶一個帳號** | 完全隔離 | 法規要求、租戶各自的 KMS 金鑰、大型企業客戶 | 維運成本最高，要有 AWS Organizations 的自動化 |

**判斷：** 從共用 provider 開始；有企業客戶要求自帶 IdP 時，再為那些客戶建立專屬的 provider。租戶數量可能上百、又都要自帶 app 的話，就要考慮分帳號。

### IAM role 怎麼切

- **Provider 的存取可以用資源 ARN 限制：** 某個 agent 的 role 只能對特定 provider 呼叫 `GetResourceOauth2Token`。
- **可以用 `aws:ResourceTag` 做 ABAC：** provider 加上 `tenant=acme` 標籤，role 只能用同租戶的 provider。
- ⚠️ **文件中的 ARN 格式不一致：** 有一頁寫 `token-vault/default/oauth2-credential-provider/<名稱>`，但 IAM 的 service reference 和標籤說明頁都是 `oauth2credentialprovider`（沒有連字號）。**用錯格式的 policy 不會報錯，只是靜默地不符合**，所以一律用 service reference 的格式：

```
arn:aws:bedrock-agentcore:<region>:<account>:token-vault/default/oauth2credentialprovider/<名稱>
arn:aws:bedrock-agentcore:<region>:<account>:token-vault/default/apikeycredentialprovider/<名稱>
arn:aws:bedrock-agentcore:<region>:<account>:workload-identity-directory/default/workload-identity/<名稱>
```

- 標籤說明頁的 ABAC 範例用了 `bedrock-agentcore:ResourceTag/Owner`，這不是列出來的 condition key，**標準寫法是 `aws:ResourceTag/Owner`**。

## 禁用 `ForUserId`

### 可用的 IAM 控制

| Action | 可用的 condition key |
|---|---|
| `GetWorkloadAccessTokenForUserId` | **`bedrock-agentcore:userid`** |
| `GetWorkloadAccessTokenForJWT` | `bedrock-agentcore:InboundJwtClaim/iss`、`/sub`、`/client_id`、`/aud`、`/scope` |
| `CompleteResourceTokenAuth` | `InboundJwtClaim/*` 與 `userid` |
| `GetResourceOauth2Token`、`GetResourceApiKey` | **沒有**，只能限制資源 |
| `InvokeAgentRuntimeForUser` | 獨立的 action，可以單獨 Deny |

### 官方的 Deny 範例

```json
{"Sid": "DenyForUserIdAccess", "Effect": "Deny",
 "Action": "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
 "Resource": "arn:aws:bedrock-agentcore:REGION:ACCOUNT_ID:workload-identity-directory/default"}
```

```json
{"Sid": "DenyUserIdDelegation", "Effect": "Deny",
 "Action": "bedrock-agentcore:InvokeAgentRuntimeForUser",
 "Resource": "arn:aws:bedrock-agentcore:REGION:ACCOUNT_ID:runtime/*"}
```

### 要放在哪裡

| Agent 的部署方式 | `ForUserId` 是怎麼被觸發的 | 要 Deny 什麼、放在哪 |
|---|---|---|
| **在 Runtime 上** | 呼叫端用 `InvokeAgentRuntimeForUser` 帶 `X-Amzn-Bedrock-AgentCore-Runtime-User-Id` header；Runtime 自己去取 token | **在呼叫端的 role（或 SCP）Deny `InvokeAgentRuntimeForUser`** |
| **自己架設**（不在 Runtime 上） | Agent 的 role 直接呼叫 `GetWorkloadAccessTokenForUserId` | **在 agent 的 role Deny `GetWorkloadAccessTokenForUserId`** |

- **為什麼只 Deny execution role 可能沒用（推論）：** 2025-10-13 之後建立的 Runtime，取 workload token 的權限來自 service-linked role（`AWSServiceRoleForBedrockAgentCoreRuntimeIdentity`），不是你的 execution role。所以對 Runtime 上的 agent，有效的控制點是**呼叫端能不能用 `InvokeAgentRuntimeForUser`**。
- **最保險的做法是放在 SCP**：整個 OU 都 Deny 這兩個 action，只對確實需要的帳號開例外（判斷）。

### 一定要用 `ForUserId` 時

有合理的情境：例如 ALB 前面接 Entra 登入，後端拿到的是 ALB 簽章的 `x-amzn-oidc-data`，而不是能直接給 AgentCore 驗證的 JWT。這時要用 `ForUserId`，但：

- **使用者 ID 必須從已驗證的來源取得**（例如驗過 ALB 簽章之後的 `sub`）。
- **用 `bedrock-agentcore:userid` 限制格式**，強制租戶前綴（推論：這是 condition key 的延伸用法，不是官方記載的模式）：

```json
{"Effect": "Allow",
 "Action": "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
 "Resource": "*",
 "Condition": {"StringLike": {"bedrock-agentcore:userid": "tenantA+*"}}}
```

  這樣租戶 A 的服務就算程式有 bug，也拿不到租戶 B 使用者的 token。

- **ForJWT 也可以限制 issuer**：`InboundJwtClaim/iss` 只允許你信任的 IdP，避免有人拿其他 IdP 簽的 token 冒用同樣的 `sub`。

## 稽核：誰替誰拿了哪張 token

### CloudTrail 看得到什麼

以 `GetResourceOauth2Token` 為例（事件來源 `bedrock-agentcore.amazonaws.com`，AWS 部落格的範例）：

| 欄位 | 內容 | 能回答 |
|---|---|---|
| `userIdentity` | 呼叫的 IAM role（assumed role） | **哪個 agent / 服務** |
| `requestParameters.resourceCredentialProviderName` | provider 名稱 | **拿了哪個服務的 token** |
| `requestParameters.scopes`、`oauth2Flow` | 範圍與流程 | 拿了什麼權限 |
| `requestParameters.workloadIdentityToken` | **`HIDDEN_DUE_TO_SECURITY_REASONS`** | ❌ **看不到替誰拿** |
| `resources[].ARN` | `…/oauth2credentialprovider/<名稱>` | 同上 |

**「替誰」這一段在 CloudTrail 裡是斷的。** `ForUserId`、`ForJWT`、`CompleteResourceTokenAuth` 的事件裡有沒有使用者 ID，**文件沒寫，需要實測**。

⚠️ **這些是管理事件還是資料事件，文件互相矛盾：** CloudTrail 的資料事件表列出了 `WorkloadIdentity`、`TokenVault`、`OAuth2CredentialProvider` 等資源類型，但部落格範例裡 `GetResourceOauth2Token` 是管理事件（`"managementEvent": true`）。**如果是資料事件，預設不會被記錄，要另外開啟**。建議兩種都開，並實際確認。

### Span 看得到什麼

在 identity 資源開啟 observability 之後，span 會寫到 `aws/spans`：

| API | Span 屬性 |
|---|---|
| `GetWorkloadAccessTokenForJWT` | `issuer`、**`user_sub`** |
| `GetWorkloadAccessTokenForUserId` | ⚠️ **沒有使用者 ID 的屬性** |
| `GetResourceOAuth2Token` | `workload.identity.id`、`credential.provider.name`、`oauth2.flow` |

**所以用 ForJWT 的話，span 能還原「使用者 → agent → provider」；用 ForUserId 則還原不了。** 這是禁用 ForUserId 的另一個理由（判斷）。

### 查詢設計

把同一次請求的兩個 span 用 trace ID 串起來（CloudWatch Logs Insights 查 `aws/spans`；屬性的實際欄位路徑要依你的資料調整，**以下查詢沒有實跑過**）：

```
fields @timestamp, traceId, name, attributes.user_sub, attributes.issuer,
       attributes.`credential.provider.name`, attributes.`workload.identity.id`
| filter name like /GetWorkloadAccessTokenForJWT|GetResourceOAuth2Token/
| stats latest(attributes.user_sub) as user,
        latest(attributes.`workload.identity.id`) as agent,
        latest(attributes.`credential.provider.name`) as provider
  by traceId
| filter ispresent(provider)
| sort @timestamp desc
```

**要回答的稽核問題與資料來源：**

| 問題 | 資料來源 |
|---|---|
| 某個使用者的 Google token 被哪些 agent 拿過？ | Span：`user_sub` + `credential.provider.name` |
| 某個 agent 最近拿過哪些服務的 token？ | CloudTrail：`userIdentity` + `resourceCredentialProviderName` |
| 有沒有人用 `ForUserId`？ | CloudTrail：事件名稱 `GetWorkloadAccessTokenForUserId`；**設成告警** |
| 有沒有人修改 provider 的設定或 return URL？ | CloudTrail 管理事件：`UpdateOauth2CredentialProvider`、`UpdateWorkloadIdentity`；**設成告警** |

**判斷：** 在 agent 自己的應用程式 log 也記一筆「使用者、要呼叫的服務、trace ID」。CloudTrail 和 span 各缺一塊，自己的 log 是最可靠的補充。

## 配額

| 項目 | 值 |
|---|---|
| Credential provider | 每種 50（可調高） |
| Workload identity | 11,000 |
| `GetWorkloadAccessToken*` | 各 200 TPS |
| `GetResourceOauth2Token`、`GetResourceApiKey` | 各 200 TPS |
| `CompleteResourceTokenAuth` | 100 TPS |
| 控制面 CRUD | 20 TPS |

**每次工具呼叫都要先取 token**，所以 200 TPS 也是整個帳號工具呼叫量的上限之一。量大的話要提早申請調高（推論）。

## 參考資料

- [Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)
- [Get workload access token](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/get-workload-access-token.html)、[Runtime OAuth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)
- [Scope credential provider access](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/scope-credential-provider-access.html)、[Identity tagging](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-tagging.html)
- [Identity observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-identity-metrics.html)
- [IAM service reference：bedrock-agentcore](https://servicereference.us-east-1.amazonaws.com/v1/bedrock-agentcore/bedrock-agentcore.json)
- [CloudTrail data events](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html)
