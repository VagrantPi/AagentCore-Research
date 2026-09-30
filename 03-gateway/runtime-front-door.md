# 延伸：Gateway 當成 Runtime 唯一入口

> 接續 [03-gateway](README.md) 與 [01 安全要點](../01-runtime/README.md#安全要點)。這篇討論：怎麼把 Runtime 放在 Gateway 後面；inbound 和 outbound 驗證怎麼搭配；怎麼確保沒有人能繞過 Gateway 直接呼叫 Runtime；以及 interceptor、rate limit、rules 各自該放在哪一層。
>
> 資料查核日期：2026-09-30。標示「推論」的部分是官方文件沒有明說、由我推導的。**沒有實際部署驗證過**（撰寫時沒有 AWS 憑證）。

## 結論先講

- **為什麼要這樣做：** Gateway 上的控制（授權規則、限流、interceptor、guardrail）只對經過 Gateway 的流量有效。如果使用者能直接呼叫 Runtime，這些控制全部都能被繞過。
- **把 Runtime 接到 Gateway 後面，用 HTTP target**（`http.agentcoreRuntime`）。⚠️ **這種 target 只能加到「沒有設定 `protocolType`」的 gateway**，設成 MCP 型的 gateway 不能加。所以**要規劃兩個 gateway**，或一開始就不設定 protocol type。
- **鎖住 Runtime 的方法依 Runtime 的驗證方式而定：**
  - **IAM 型的 Runtime**：用 resource-based policy，只允許 Gateway 的 execution role 呼叫。
  - **JWT 型的 Runtime**：用 `allowedWorkloadConfiguration`，只接受「經由指定 Gateway 轉送」的請求。
- **Outbound 的選擇：** 試驗用 token 直通（passthrough）或呼叫者 IAM，正式環境用 service role 或 OAuth。⚠️ **文件說 Runtime target 不支援 OBO（token 換發），但官方範例用了**，要實測。

## 架構

```
使用者 / 前端
   │  JWT（inbound 驗證）
   ▼
Gateway（沒有設定 protocolType）
   ├─ inbound：JWT 驗證
   ├─ rate limit（依 $.context.jwt.sub）
   ├─ interceptor（REQUEST / RESPONSE）
   ├─ gateway rules（路由、A/B）
   └─ target：http.agentcoreRuntime ──► Runtime
                   │ outbound：service role（SigV4）或 OAuth
                   ▼
              Runtime（只接受這個 Gateway 的請求）
```

呼叫方式：`https://{gatewayId}.gateway.bedrock-agentcore.{region}.amazonaws.com/{targetName}/invocations`，支援 SSE 串流。也可以用 `aws bedrock-agentcore invoke-agent-runtime --endpoint-url <gateway>/<target>`，也就是**原本呼叫 Runtime 的 client 只要換 endpoint**。

Target 設定：

```json
{"http": {"agentcoreRuntime": {
  "arn": "arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/RUNTIME_ID",
  "qualifier": "DEFAULT",
  "schema": {"source": {"s3": {"uri": "s3://DOC-EXAMPLE-BUCKET/agent-schema.yaml"}}}}}}
```

- `qualifier` 可以指定 Runtime 的 endpoint（例如 `prod`），預設 `DEFAULT`。
- `schema` 只有 HTTP 協定的 agent 需要 guardrail 時才必填；MCP、A2A 的 agent 有預設的 schema。

## Inbound 與 Outbound 的搭配

### Outbound 能用哪些方式

| 方式 | 設定 | 下游看到的身分 | 適合 |
|---|---|---|---|
| **Service role（SigV4）** | Gateway 用自己的 execution role 簽章 | Gateway 的 role | **IAM 型 Runtime 的正式環境**；搭配 resource policy 鎖定最簡單 |
| **呼叫者的 IAM**（`CALLER_IAM_CREDENTIALS`） | 用呼叫者的憑證轉送 | 原本的呼叫者 | 內部服務呼叫；**只能搭配 inbound 為 IAM 或 `AUTHENTICATE_ONLY`** |
| **OAuth 2LO**（client credentials） | 從 Identity 取得 M2M token | Gateway 這個 client | JWT 型 Runtime、不需要使用者身分的情境 |
| **Token 直通**（`JWT_PASSTHROUGH`） | 把使用者的 JWT 原封不動轉給 Runtime | 原本的使用者 | **試驗用**。官方說不建議用在正式環境 |
| **OAuth 換發（OBO）** | 用使用者的 token 換一張新 token | 使用者 + Gateway | ⚠️ 文件的支援表寫「不支援」，但官方範例（Entra ID 的 A2A agent）用了 `grantType: TOKEN_EXCHANGE`，**要實測** |

官方建議的「快速導入」組合：

| Runtime 的驗證方式 | Inbound | Outbound |
|---|---|---|
| IAM | `AUTHENTICATE_ONLY` | 呼叫者的 IAM |
| OAuth（JWT） | `NONE` | Token 直通 |

**這兩個組合的 inbound 都不做授權**（03 本文的踩雷清單第 1 條）。它們的用意是「先把流量導進 Gateway，Runtime 自己的驗證照舊」，**只適合過渡期**。

⚠️ **文件矛盾：** outbound 驗證頁說 token 直通「需要 inbound 為 `AUTHENTICATE_ONLY`」；inbound 驗證頁卻說 token 直通「不能搭配 `AUTHENTICATE_ONLY`」（因為那個模式是 SigV4，請求裡根本沒有 bearer token），要搭配 JWT 或 NONE。**後者在邏輯上才對。**

### 正式環境的建議組合（判斷）

| 情境 | Inbound | Outbound | 理由 |
|---|---|---|---|
| 對外的應用（使用者用 JWT 登入） | **JWT**（驗 audience、scope） | **Service role** | Gateway 做完授權，Runtime 只需要信任 Gateway；使用者身分可以用 header 傳遞 |
| 對外的應用，而且 agent 要代表使用者呼叫下游 | JWT | 等 OBO 的支援確認後改用 OBO | Runtime 需要一張代表使用者的 token |
| 內部服務呼叫 agent | IAM | Service role 或呼叫者 IAM | 全程 IAM，最簡單 |

**使用者身分怎麼傳到 Runtime：** 用 service role 時，Runtime 看到的是 Gateway 的身分。需要使用者身分時，可以用 REQUEST interceptor 把 JWT 裡的 `sub` 放進 header，並把這個 header 加進 Runtime 的 header allowlist（推論：官方沒有這個情境的完整範例，header 的信任前提是「只有 Gateway 能呼叫 Runtime」，所以下一節的鎖定是必要的）。

## 防止繞過 Gateway

### IAM 型的 Runtime：resource-based policy

```json
{"Version": "2012-10-17", "Statement": [
  {"Sid": "AllowOnlyGatewayRole", "Effect": "Allow",
   "Principal": {"AWS": "arn:aws:iam::111122223333:role/MyGatewayExecutionRole"},
   "Action": "bedrock-agentcore:InvokeAgentRuntime",
   "Resource": "arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/RUNTIME_ID"},
  {"Sid": "DenyOtherPrincipals", "Effect": "Deny",
   "Principal": {"AWS": "*"},
   "Action": "bedrock-agentcore:InvokeAgentRuntime",
   "Resource": "arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/RUNTIME_ID",
   "Condition": {"ArnNotEquals": {"aws:PrincipalArn": "arn:aws:iam::111122223333:role/MyGatewayExecutionRole"}}}
]}
```

- **明確的 Deny 很重要：** 只有 Allow 的話，帳號內其他有 `InvokeAgentRuntime` 權限的 IAM principal 仍然可以直接呼叫。Deny 會蓋過它們的 identity-based policy。
- **Gateway role 的 trust policy 也要鎖住：** 用 `aws:SourceArn`（gateway 的 ARN）和 `aws:SourceAccount` 限制只有這個 gateway 能 assume。**能 assume 這個 role 的人，就能直接呼叫 Runtime。**
- Runtime 和 endpoint 的 policy 都會被評估（階層式）。
- **這個設計假設 outbound 是 service role。** 如果改用呼叫者 IAM，呼叫者的身分不是 gateway role，會被這條 Deny 擋下（推論）。

### JWT 型的 Runtime：`allowedWorkloadConfiguration`

在 Runtime 的 `customJWTAuthorizer` 裡加上：

```json
"allowedWorkloadConfiguration": {
  "hostingEnvironments": [{"arn": "arn:aws:bedrock-agentcore:us-east-1:111122223333:gateway/my-gateway-1-id"}],
  "workloadIdentities": ["my-gateway-2-workload-identity"]
}
```

- 意思是：**就算 JWT 本身有效，也只接受「身分鏈裡有指定 Gateway」的請求**。使用者拿同一張 JWT 直接打 Runtime，會被拒絕。
- 兩個欄位符合任一個就放行；各最多 10 筆。Workload identity 的名稱是 `GetGateway` 回傳的 `workloadIdentityArn` 的最後一段。
- 官方說明：「At launch, the only supported hosting environment is AgentCore Gateway」，而且只適用於 Runtime target。
- ⚠️ **兩個操作上的陷阱：**
  - **AgentCore CLI 不會設定這個欄位**，要用 API 自己加。
  - **`UpdateAgentRuntime` 會整個取代設定**，所以要先 `get_agent_runtime` 讀出現有設定，合併之後再寫回；否則其他設定會被清掉。官方範例 `04-advanced-concepts/gateway-enforced-access` 就是這樣做。
- **不確定的地方：** Runtime 以 MCP server target（而不是 HTTP target）接到 Gateway 時，這個欄位是否同樣有效，文件沒寫。

### 網路層（選用）

- Gateway 的 inbound 可以走 PrivateLink（`com.amazonaws.<region>.bedrock-agentcore.gateway`）。
- VPC endpoint policy **只能限制 IAM principal**；OAuth 的請求要寫成 `"Principal": "*"` 再加條件。
- **判斷：** 網路層的限制是補充，**主要的防線是上面兩種身分層的鎖定**。只靠網路限制，同一個 VPC 裡的其他服務仍然可以繞過。

## 各種控制該放在哪一層

| 控制 | 放在哪裡 | 用途 | 不該拿來做 |
|---|---|---|---|
| **Inbound 驗證** | Gateway | 誰可以呼叫 | — |
| **授權規則**（Cedar，細節在 08） | Gateway | **官方建議的授權位置** | — |
| **Interceptor** | Gateway | 格式轉換、補 header、客製化的驗證、遮罩 | 當作主要的授權機制（官方建議授權用 Policy） |
| **Rate limit** | Gateway | 流量管理、服務品質、防止單一使用者用光額度 | **安全控制**（它是 fail-open 的） |
| **Gateway rules** | Gateway | 路由、canary、A/B | — |
| **WAF** | Gateway | 一般的 web 攻擊防護 | — |
| **Payload 驗證** | **Runtime** | 確認 `prompt` 是字串（01 提到的 `toolUse` 注入） | — |

**處理順序：** rate limit 在 gateway rules **之前**評估。interceptor 和授權規則的先後順序，**文件沒寫**。

### Interceptor 的細節

- **每個 gateway 最多一個 REQUEST、一個 RESPONSE interceptor**，只能用 Lambda。
- **Lambda 可能被重試，所以要是冪等的。**
- **MCP 和 HTTP 的行為不同：**

| | MCP target | HTTP / Runtime / inference target |
|---|---|---|
| Payload | 解析過的 JSON | `http` 結構，body 是 base64 |
| REQUEST 直接回應（短路）後，RESPONSE interceptor 會不會執行 | **會** | **不會** |
| 串流 | 每個有 `id` 的 JSON-RPC 事件呼叫一次，只有第一個事件能改 header 和狀態碼 | **不支援串流模式**，只能 buffered |

- **Runtime 放在 Gateway 後面時，interceptor 不支援串流，這是個重要限制：** 如果 agent 的回應是 SSE 串流，就不能用 RESPONSE interceptor 加工內容（推論：REQUEST interceptor 是否也會迫使整個請求變成 buffered，文件沒寫，要實測）。
- Lambda 同步呼叫的 6 MB 上限也適用；回應可能很大時，用 `payloadFilter` 排除 response body。
- Client context 裡有 `GATEWAY_ARN`、`REQUEST_ID`，以及可能有的 `SOURCE_IP`。

### Rate limit 放在入口的設計（判斷）

- **以使用者為單位：** 維度用 `$.context.jwt.sub`，每個使用者每分鐘 N 次。這能防止單一使用者（或被操控的 agent）用光整個服務的容量。
- **以 target 為單位：** 保護特定的 Runtime 不被打爆。
- **維度建立後就不能改**，一開始就要想清楚。
- **Fail-open 的後果：** JWT 裡缺少用來當維度的 claim 時，整條限制會被**略過**。所以要搭配 inbound 驗證的 `customClaims`，確保該 claim 一定存在。

## 部署檢查清單

1. 建立（或確認）一個**沒有設定 `protocolType`** 的 gateway。
2. Inbound 設成 JWT，驗 audience 與 scope。
3. 加上 `http.agentcoreRuntime` target，outbound 用 service role。
4. 鎖住 Runtime：
   - IAM 型：resource policy（Allow + Deny），並鎖住 gateway role 的 trust policy。
   - JWT 型：`allowedWorkloadConfiguration`，用「讀取、合併、寫回」的方式更新。
5. 設定 rate limit（以 `sub` 為維度），確認 claim 一定存在。
6. **驗證繞不過去：** 用同一張 JWT（或同一個 IAM 身分）**直接呼叫 Runtime，必須被拒絕**；經過 Gateway 則成功。這一步最容易被跳過，但它才是整套設計的目的。
7. Client 的 endpoint 改成 gateway 的 URL。

## 參考資料

- [Runtime as a gateway target](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-http-runtime.html)、[Create a gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-create-api.html)
- [Outbound auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-outbound-auth.html)、[Inbound auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html)
- [Runtime OAuth（allowedWorkloadConfiguration）](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html)、[Resource-based policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html)
- [Runtime security best practices](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html)
- [Interceptors](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-interceptors.html)、[Rate limits](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-rate-limits.html)、[Gateway rules](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-rules.html)
- [VPC interface endpoints](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/vpc-interface-endpoints.html)
- [awslabs/amazon-bedrock-agentcore-samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples)：`04-advanced-concepts/gateway-enforced-access`、`01-features/07-centralize-and-govern-your-ai-infrastructure/01-gateway/01-attach-targets/http/agents/a2a-agents/agentcore-runtime`
