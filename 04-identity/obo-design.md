# 延伸：OBO 的端到端設計

> 接續 [04-identity](README.md#三種-outbound-模式)。這篇設計「使用者 → Runtime → Gateway → 內部 API」每一層的 token 要給誰（audience）、能做什麼（scope），讓下游能同時確認「是哪個使用者」和「是哪個 agent」；比較 Entra ID、Okta、Cognito 的支援程度；並分析直接轉傳使用者 token 的風險。
>
> 資料查核日期：2026-09-30。標示「推論」的部分是官方文件沒有明說、由我推導的。**沒有實際部署驗證過**。

## 結論先講

- **OBO 的目的：** 每一層拿到的 token，**audience 都只寫著自己**。就算某一層外洩了 token，也只能拿來呼叫那一個服務，不能拿去冒充使用者呼叫其他服務。
- **IdP 的支援程度差很多：**
  - **Entra ID**：AgentCore 內建支援，也有完整的官方範例，**最成熟**。
  - **Okta**：支援 token exchange，要多帶 `audience` 參數。
  - **Cognito**：**本身不支援 token exchange**（token 端點沒有這種 grant type），要用 AWS 範例的變通做法（兩個 user pool + 自訂驗證流程）。
- **下游看到「agent 是誰」的方式由 IdP 決定**，不是 RFC 8693 的標準 `act` claim。例如 Entra 把使用者放在 `sub`、中間層放在 `xms_act.sub`。下游的驗證邏輯要依 IdP 而寫。
- **目前的限制：** Gateway 的 OBO 只支援 MCP server 和 OpenAPI target。Runtime target 文件寫不支援，但官方範例用了（見 [03 延伸](../03-gateway/runtime-front-door.md#outbound-能用哪些方式)）。

## 為什麼不直接轉傳使用者的 token

| | 直接轉傳（passthrough） | OBO |
|---|---|---|
| 下游收到的 token | 使用者登入前端時拿到的那張 | IdP 新簽發的一張 |
| Audience | **前端的 app**（下游其實不應該接受） | **下游自己** |
| Scope | 前端需要的所有權限 | 只有下游需要的 |
| 下游知不知道是 agent 在操作 | 不知道 | 知道（依 IdP 的 claim） |
| 外洩的影響 | 可以冒充使用者呼叫**所有接受這張 token 的服務** | 只能呼叫那一個下游 |
| 撤銷 | 只能撤銷使用者的整個登入 | 可以只撤銷 agent 的權限（依 IdP） |

直接轉傳能運作，通常是因為**下游沒有認真檢查 audience**。這本身就是一個安全問題：任何拿到使用者 token 的服務，都能拿它去呼叫你的內部 API。官方 Entra 範例對直接轉傳的評語是「技術上可以，但 `aud` 是錯的」。

## 每一層的 audience 與 scope

以「客服 agent 代表使用者查訂單」為例：

```
使用者 ──(1)──► Runtime（agent） ──(2)──► Gateway ──(3)──► 內部訂單 API
```

| 階段 | Token | `aud` | `scope` | 誰驗證 | 驗證什麼 |
|---|---|---|---|---|---|
| (1) 使用者 → Runtime | 使用者登入時的 token | **Agent 的 app ID** | `agent.invoke` | Runtime 的 JWT authorizer | `allowedAudience`、`allowedScopes` |
| (2) Runtime → Gateway | 第一次 OBO 換發 | **Gateway 的 app ID** | `tools.invoke` | Gateway 的 inbound JWT 驗證 | audience、scope，以及 agent 的身分 claim |
| (3) Gateway → 訂單 API | 第二次 OBO 換發（Gateway 的 outbound） | **訂單 API 的 app ID** | `orders.read` | 訂單 API 自己 | audience、scope、使用者（`sub`）、agent（依 IdP 的 claim） |

**設計原則（判斷）：**

- **每一層都要在 IdP 裡註冊成一個獨立的 app（resource server）**，有自己的 app ID 當 audience。沒有註冊的服務，就沒辦法成為換發的對象。
- **Scope 要一路縮小：** 使用者登入時的 scope 最大，越往下游越小。第 (3) 段只需要 `orders.read`，就不應該有 `orders.write`。
- **最後一段最重要：** 內部 API 是真正存取資料的地方，**它一定要同時驗證使用者和 agent**。只驗證使用者，就沒辦法做到「使用者本人可以改訂單，但透過 agent 只能查」這種規則。

### 2 段就夠了嗎？

如果 Runtime 不透過 Gateway、直接呼叫內部 API，就只有一次換發（使用者 token → 內部 API 的 token）。多一層 Gateway 的好處是集中的授權規則、限流、稽核（見 [03](../03-gateway/README.md#治理手段)），代價是多一次換發的延遲和一個要註冊的 app。

## 各 IdP 的做法

### AgentCore 的設定

Credential provider 的 `onBehalfOfTokenExchangeConfig`（放在 `customOauth2ProviderConfig` 裡，vendor 為 `CustomOauth2`）：

```json
"onBehalfOfTokenExchangeConfig": {
  "grantType": "TOKEN_EXCHANGE",
  "tokenExchangeGrantTypeConfig": {
    "actorTokenContent": "M2M",
    "actorTokenScopes": ["scope1", "scope2"]
  }
}
```

或 `{"grantType": "JWT_AUTHORIZATION_GRANT"}`。

| Grant type | 標準 | 送給 IdP 的內容 |
|---|---|---|
| `TOKEN_EXCHANGE` | RFC 8693 | `subject_token` = 使用者的 token；`actor_token` 依 `actorTokenContent` 而定 |
| `JWT_AUTHORIZATION_GRANT` | RFC 7523 | `assertion` = 使用者的 token |

`actorTokenContent`（證明「agent 是誰」的那張 token）：

| 值 | 來源 | 說明 |
|---|---|---|
| `M2M` | Client credentials 取得的 token | 最常見 |
| `AWS_IAM_ID_TOKEN_JWT` | `sts:GetWebIdentityToken`，audience 是 IdP 的 token 端點 | **不需要在 IdP 保存 client secret**；需要 `iam:EnableOutboundWebIdentityFederation` |
| `NONE` | 不帶 | 只有使用者身分 |

Client 驗證方式：`CLIENT_SECRET_BASIC`、`CLIENT_SECRET_POST`、`AWS_IAM_ID_TOKEN_JWT`、`PRIVATE_KEY_JWT`（用 KMS 的金鑰簽章，適用於 M2M、OBO、3LO）。**能用 `PRIVATE_KEY_JWT` 或 `AWS_IAM_ID_TOKEN_JWT` 就不要用 client secret**，少一個要輪替的機密（判斷）。

### Entra ID（最成熟）

- AgentCore 內建 `MicrosoftOauth2` provider，走 `JWT_AUTHORIZATION_GRANT`，**會自動加上 `requested_token_use=on_behalf_of`**。
- 官方範例（`04-entra-obo-mcp-runtime`）用了三張 token：

| Token | `aud` | 用途 |
|---|---|---|
| 使用者的 JWT | Agent app 的 client ID | 呼叫 Runtime |
| M2M token | MCP app | 呼叫 MCP server（在那一端用 `customClaims` 驗 `mcp_invoke`） |
| Graph 的 OBO token | `https://graph.microsoft.com` | 呼叫 Microsoft Graph，放在自訂 header 傳遞（header 要加進 `requestHeaderAllowlist`） |

- **Entra 在換發後的 token 裡，使用者放在 `sub`，中間層放在 `xms_act.sub`**，不是標準的 `act` claim。
- **常見錯誤 `AADSTS500131`：** 使用者 token 的 `aud` 不是 Agent app。登入時 scope 要用 `<AGENT_CLIENT_ID>/.default`。
- Entra 的 inbound 驗證：v1 和 v2 token 都支援，但**不能有自訂 claim**。

### Okta

- 用 `TOKEN_EXCHANGE`，**要在 `customParameters` 多帶 `audience`**（除了 `subject_token_type`）。
- Okta 預設**不會發 `client_id` claim**，要用 inbound 的 `allowedClients` 驗證的話，得先在 Okta 加上這個 claim。

### Cognito（不支援，要變通）

- Cognito 的 token 端點**沒有 token exchange 或 jwt-bearer 這兩種 grant type**（依 Cognito 自己的文件判斷；AgentCore 文件沒有明說）。
- AWS 有一個變通範例 `aws-samples/sample-cognito-oauth2-token-exchange`：兩個 user pool，加上自訂的驗證流程（CUSTOM_AUTH）模擬換發。**這等於自己維護一套換發邏輯**。
- Cognito 也不支援 Dynamic Client Registration（RFC 7591）。

**判斷：** 如果 OBO 是核心需求，而目前的 IdP 是 Cognito，**比較實際的做法是讓 Gateway 用 service role 或 M2M 呼叫下游，使用者身分用 header 或 claim 傳遞**，並靠「只有 Gateway 能呼叫下游」這個前提保證 header 可信（見 [03 延伸](../03-gateway/runtime-front-door.md#正式環境的建議組合判斷)）。這不是真正的 OBO，但在 Cognito 上比較容易維護。

## Inbound 驗證的設定

Runtime 和 Gateway 的 `customJWTAuthorizer` 結構相同：

| 欄位 | 用途 |
|---|---|
| `discoveryUrl` | IdP 的 OIDC discovery URL（必填） |
| `allowedAudience` | 允許的 `aud` |
| `allowedClients` | 允許的 `client_id` |
| `allowedScopes` | 必須包含的 scope |
| `customClaims` | 自訂 claim 的比對（EQUALS、CONTAINS、CONTAINS_ANY） |
| `allowedWorkloadConfiguration` | 只接受經由指定 Gateway 的請求 |

- **audience、clients、scopes、claims 至少要設一個**，設了的全部都要通過。
- **做 OBO 時，第 (1) 段 token 的 `aud` 必須是 IdP 認定的「OBO client」**（Entra 就是 Agent app 的 ID），否則換發會失敗。

## 下游 API 要驗證什麼

```python
# 內部訂單 API 收到的 token（以 Entra 為例；其他 IdP 的 claim 名稱不同）
claims = verify_jwt(token, issuer=ISSUER, audience="api://orders")  # 簽章、到期、aud
user = claims["sub"]                                  # 使用者
agent = claims.get("xms_act", {}).get("sub")          # 經手的 agent；沒有就是使用者本人直接呼叫
if "orders.read" not in claims["scp"].split():
    deny()
if agent is not None and request.method != "GET":
    deny()   # 業務規則：透過 agent 只能查，不能改
```

- **`aud` 一定要驗**：這是 OBO 的安全性來源。
- **依「是否經過 agent」套用不同的規則**：這是直接轉傳做不到的。
- **agent 的 claim 名稱依 IdP 而定**，換 IdP 時要改（推論：AgentCore 文件只說換發後的 token「同時帶有 agent 和使用者的身分」，沒有規定 claim 名稱）。

## 參考資料

- [On-behalf-of token exchange](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-behalf-of-token-exchange.html)
- [Gateway outbound authorization](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-building-adding-targets-authorization.html)
- [Runtime OAuth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)
- IdP 設定：[Microsoft](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-idp-microsoft.html)、[Okta](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-idp-okta.html)
- [awslabs/amazon-bedrock-agentcore-samples：04-entra-obo-mcp-runtime](https://github.com/awslabs/amazon-bedrock-agentcore-samples)
- [aws-samples/sample-cognito-oauth2-token-exchange](https://github.com/aws-samples/sample-cognito-oauth2-token-exchange)
- [RFC 8693 Token Exchange](https://www.rfc-editor.org/rfc/rfc8693)、[RFC 7523 JWT Bearer](https://www.rfc-editor.org/rfc/rfc7523)
