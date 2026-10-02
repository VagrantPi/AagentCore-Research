# 實驗用的受限 IAM 身分

> 給沒有 AWS 權限的同事一個只能做實驗的身分。分四層，越上層越是硬邊界。
>
> ⚠️ **這三份範本沒有在 AWS 上實際套用過。** 套用前先做完下方的[驗證](#套用前必須驗證)。

| 檔案 | 掛在哪裡 | 作用 |
|---|---|---|
| [`scp.json`](scp.json) | AWS Organizations，套在實驗帳號上 | 只能用選定的區域、禁止開 EC2、禁止建 IAM user 與長期 key。連帳號管理員都無法越過 |
| [`permission-set.json`](permission-set.json) | IAM Identity Center 的 permission set | 同事實際拿到的權限；最後一段 Deny 保護 boundary 不被拆掉 |
| [`wp-boundary.json`](wp-boundary.json) | 建成名為 `wp-boundary` 的 managed policy | 同事建的每個角色都必須掛上它，權限上限就是它允許的範圍，防止「自己建大權限角色再 assume」 |

## 四層設計

1. **獨立實驗帳號 + SCP**（最重要）：有 AWS Organizations 就另開一個帳號，套上 `scp.json`。區域預設 `us-west-2`，改成你們選好、有支援 Runtime V2 的區域。
   - 沒有 Organizations、只能用現有帳號時，跳過這層，只靠第 3、4 層與預算警報。**同帳號的正式資源只靠名稱與 tag 隔開，風險明顯較高。**
2. **IAM Identity Center 發短效憑證**：建 permission set（例如 `AgentCoreExperimenter`），session 時長 4 小時、強制 MFA，只指派到實驗帳號。同事用 `aws sso login --profile wp-lab` 登入。
   - 不建 IAM user、不發長期 access key。同事用 AI 輔助開發，憑證不放 `.env` 或 repo，AI 工具才不容易讀到或貼進對話與 log；過期後外流也無效。
3. **權限政策**：`permission-set.json`。只開實驗會用到的服務；自建資源用 `wp-` 前綴命名；角色只能建在 `/wp/` 路徑下。
4. **Permission boundary**：先用 `wp-boundary.json` 建好 `wp-boundary` policy，再把 `permission-set.json` 裡的 `<ACCOUNT_ID>` 換成實驗帳號 ID。

## 權限與 WP 的對應

| 權限 | 用途 |
|---|---|
| `bedrock-agentcore:*` | Runtime、Gateway、Policy、Memory、Code Interpreter、Harness 的控制面與資料面（WP1、WP2、WP3、WP5、WP7） |
| 模型呼叫、Guardrail | agent 呼叫模型；WP2 的 Guardrail |
| Lambda、DynamoDB、S3、ECR（`wp-*`） | WP2 的工具 Lambda 與 Todo 資料表、WP5 的 S3 路徑、Runtime 的 container image |
| Cognito | WP2、WP5 發使用者 A、B 的 JWT |
| VPC 相關 | WP3 建「不開 NAT」的 VPC 與 endpoint |
| `/wp/` 角色、PassRole、AssumeRole | Runtime 的 execution role；WP5 的測試角色 |

**Browser 權限的歸屬（設計變更後）：** Browser 改由自家 MCP server 呼叫（見 [WP2](../WP2-capability-boundary.md#設計變更背景)）。所以 Runtime 的 **execution role 不給任何 Browser 權限**；Browser 相關權限只給自家 server 使用的角色（server 在 AWS 上就用它的 IAM role，不在 AWS 上用 IAM Roles Anywhere 這類短效憑證）。`wp-boundary.json` 目前允許 `bedrock-agentcore:*`，做 WP2 #6 時要另建一個**不含** Browser 動作的 execution role 來驗證。

**刻意不給的：** Cost Explorer 與 Billing。[WP0](../WP0-cost-baseline.md) 和帳單由帳號負責人處理。

## 兜底

- **AWS Budgets：** 每日預算警報（WP0）。可加 Budget Action：超過預算時自動對這個 permission set 套上全面 Deny。
- **CloudTrail：** 保持開啟，事後可查操作紀錄。
- **結束後：** 撤銷 permission set 的指派；依 `wp` tag 或 `wp-` 前綴清掉資源。

## 套用前必須驗證

| # | 要確認的事 | 為什麼 |
|---|---|---|
| 1 | AgentCore 的 service principal 是不是 `bedrock-agentcore.amazonaws.com` | `iam:PassedToService` 寫錯，建 Runtime 會失敗 |
| 2 | 哪些 AgentCore 的 Create 動作支援 `aws:RequestTag` | 範本**沒有**強制建立時帶 `wp` tag：不支援的動作加了條件會全部失敗。查 [Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonbedrockagentcore.html) 後再補 |
| 3 | `bedrock-agentcore:*` 的範圍 | 包含 Identity 的 token vault、`InvokeAgentRuntimeCommand` 這類可直接下指令的 API。獨立帳號可接受；和正式資源同帳號時，要改成逐條列 action，並把 `Resource` 限定在實驗資源 |

**最快的驗證方式：** 用這個身分照 [WP1](../WP1-runtime-session.md) 的步驟 1 部署一個最小的 Runtime，哪一步 `AccessDenied` 就補哪一條，並記錄在本檔。

## 不需要 IAM 也能交給同事的東西

有些檢核點不必給 IAM 身分，由有權限的人建好資源後交出：

| 交出的東西 | 能做的事 |
|---|---|
| Cognito 發的 JWT（使用者 A、B） | 呼叫設成 JWT 驗證的 Runtime、Gateway：量延遲、查 `tools/list`、呼叫工具 |
| Bedrock API key | 呼叫模型 |
| WP5 測試角色的短效憑證 | 用 A 的身分讀 B 的資料，看是否被擋 |
| 已部署的 OpenClaw 聊天機器人 | WP7 直接對話測試 |

「改設定看行為」的檢核點（例如 WP3 全部、WP2 換 policy 寫法、WP1 改逾時與部署新版本）還是需要 IAM 身分。
