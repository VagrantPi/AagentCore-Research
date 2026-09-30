# Nova Act 部署與維運

> 把本機的 workflow 腳本部署到 AWS、觸發執行、看紀錄、設告警。
>
> 資料查核日期：2026-09-30。來源為 [使用者指南](https://docs.aws.amazon.com/nova-act/latest/userguide/step-3-deploy.html)、[Nova Act CLI README](https://github.com/aws/nova-act/blob/main/src/nova_act/cli/README.md)、[nova-act-samples/cdk](https://github.com/amazon-agi-labs/nova-act-samples/tree/main/cdk)。SDK 與 `Workflow` 見 [01](../01-sdk/)。

## TL;DR

- **「部署」其實是兩件事：**
  1. 在 Nova Act 服務**註冊 workflow definition**（一個名字，加上選填的 S3 匯出設定）。
  2. 把你的 Python 程式**放到某個運算平台上跑**。
  Nova Act 服務本身不幫你跑程式。
- **三條部署路徑：**
  - IDE 擴充的一鍵部署或 `act workflow deploy`：自動包容器、推 ECR、建 IAM role 和 S3，**部署到 AgentCore Runtime**。
  - [CDK 範例](https://github.com/amazon-agi-labs/nova-act-samples/tree/main/cdk)：Lambda、Fargate、ECS、AgentCore 四選一。
  - 自己寫部署。
- **CLI 官方明說只是快速上手工具：** 「**SHOULD NOT** be used as a dependency in production code」。正式環境建議用 CDK 或自己的 IaC。
- **紀錄分三層：**
  - Nova Act Console：run → session → act → step 的逐步紀錄。
  - CloudWatch `AWS/NovaAct` namespace：API 層級的指標。
  - CloudTrail：控制面預設記錄；資料面要自己開，包括 `InvokeActStep`。
- **執行軌跡的保存：** 服務只**暫存** agent trajectory（prompt、截圖、模型回應）。要長期保存，就在 workflow definition 設 `exportConfig`，寫到**同帳號**的 S3。

## 部署的全貌

```text
          ┌────────────── Nova Act 服務（us-east-1）──────────────┐
          │  WorkflowDefinition ──▶ WorkflowRun ──▶ Session ──▶ Act │
          │  （控制面：建立 / 查詢）   （資料面：InvokeActStep = 模型推論）│
          └────────────────────────────▲──────────────────────────┘
                                       │ SDK 的 Workflow 自動呼叫
你的程式碼（main(payload)）───────────┘
   跑在：AgentCore Runtime ← CLI / IDE 預設
         Lambda / Fargate / ECS ← CDK 範例
   瀏覽器：容器內的 headless Chromium，或 AgentCore Browser（CDP）
   觸發：act workflow run / InvokeAgentRuntime / 你自己的 API、排程、佇列
```

> 推論：workflow definition 和運算平台是**鬆耦合**的。同一個 definition 可以從本機、Lambda、AgentCore 各自執行，Console 都會記錄到同一個 definition 底下。這很適合用來比較不同環境的行為。

## 路徑一：Nova Act CLI（部署到 AgentCore Runtime）

```bash
pip install "nova-act[cli]"

act workflow create --name my-workflow                          # 註冊 workflow definition
act workflow deploy --name my-workflow --source-dir ./project   # 建置並部署
act workflow run    --name my-workflow --payload '{"input": "data"}'
```

**入口的慣例：** 預設的入口檔是 `main.py`，裡面必須有 `def main(payload):`。可以用 `--entry-point` 指定其他檔案，`--skip-entrypoint-validation` 則會跳過檢查。

**CLI 會自動建立的資源：**

| 資源 | 名稱 | 備註 |
|------|------|------|
| ECR repository | `nova-act-cli-default` | 所有 workflow 共用 |
| IAM role | `nova-act-{workflow}-role` | 權限包括 AgentCore、ECR、CloudWatch Logs、X-Ray、`nova-act-*` bucket。可以用 `--execution-role-arn` 改用自己的 role |
| S3 bucket | `nova-act-{account}-{region}` | 也是 workflow definition 預設的匯出位置 |
| AgentCore Runtime | 一個 workflow 一個 | 容器化的執行環境（見 [AgentCore 01](../../01-runtime/)） |
| Workflow definition | 你指定的名字 | Nova Act 服務上的資源 |
| CloudWatch Log groups | `/aws/bedrock-agentcore/runtimes/{agent-id}-default`（以及 `/runtime-logs` 子群組存 OTel 紀錄） | |

**本機狀態：** CLI 把部署紀錄存在 `~/.act_cli/state/{account}/{region}/workflows.json`（有檔案鎖），建置產物在 `~/.act_cli/builds/{workflow}/`，**不會自動清除**。

> 判斷：狀態只存在個人電腦上，跟早期 Terraform 用本機 state 的問題一樣，換一台機器或換一個人就接不上。這也是它不適合當正式部署工具的原因之一。

**執行時傳入環境變數：** payload 裡的 `AC_HANDLER_ENV` 會在執行前被寫進 `os.environ`，官方範例拿它來傳 `NOVA_ACT_API_KEY`。

> ⚠️ 判斷：用 payload 傳遞密鑰，密鑰就會出現在呼叫端的程式、shell history 和可能的呼叫紀錄裡。正式環境應該改用 IAM 驗證（完全不需要 API key）。其他密鑰請用 Secrets Manager 或 [AgentCore Identity](../../04-identity/)。

**區域：** CLI 可以用 `--region` 把 Runtime 部署到其他區域，但 **Nova Act 服務只在 us-east-1**。部署在其他區域時，每一步的模型推論都要跨區呼叫 us-east-1。

## 路徑二：CDK 範例（選擇運算平台）

[nova-act-samples/cdk](https://github.com/amazon-agi-labs/nova-act-samples/tree/main/cdk) 提供四種部署範例，都用 IAM role 驗證，也都附有「部署 → 呼叫 → 拆除」的測試腳本：

| 平台 | 適合 | 架構重點 | 限制 |
|------|------|---------|------|
| Lambda | 事件驅動、短流程 | 容器映像檔預裝 Playwright | **最長 15 分鐘** |
| Fargate | 一般的長流程 | 私有子網路 + VPC endpoint + NAT | |
| ECS（EC2） | 大量、需要控制主機 | 自動擴展、加密的 EBS | 要自己管理容量 |
| AgentCore | 想接 AgentCore 其他元件 | ARM64 容器、內建 OpenTelemetry | 見 [04](../04-agentcore/) |

共同的瀏覽器參數：`--disable-gpu --disable-dev-shm-usage --no-sandbox --single-process`，全部使用 headless 模式。

> 判斷：選擇的關鍵是**流程會跑多久**和**要不要接 AgentCore 的其他元件**。
> - 5 分鐘內、由事件觸發：Lambda。
> - 長流程、要自己控制網路：Fargate。
> - 要用 AgentCore 的 Identity、Browser、Observability：AgentCore Runtime（microVM 最長 8 小時，Instances 模式最長 14 天，見 [AgentCore 01](../../01-runtime/)）。
>
> Nova Act 的 act timeout 是 24 小時，workflow run 最長 1 週，所以流程能跑多久，**上限通常卡在運算平台，而不是 Nova Act**。

### 文件中的小矛盾

CDK README 的「Prerequisites」要求準備 **Nova Act API key**（還要 `export NOVA_ACT_API_KEY`），但同一份文件的「Authentication」段落又說「All examples use IAM Role authentication — no API keys required」。從架構來看，正式部署應該走 IAM。API key 的前置步驟看起來是舊版本留下來的，需要實際部署才能確認。

## Workflow definition

```bash
aws nova-act create-workflow-definition \
  --name my-workflow \
  --export-config '{"s3BucketName": "my-bucket", "s3KeyPrefix": "nova-act-workflows"}' \
  --region us-east-1
```

- 也可以用 Console、boto3（`boto3.client('nova-act').create_workflow_definition(...)`）或 `act workflow create` 建立。
- **只需要建立一次。** 不要在執行時建立（官方特別提醒）。
- **`exportConfig`：** 把 agent trajectory（prompt、截圖、模型回應）永久寫到你的 S3。
  - 呼叫端需要對 `arn:aws:s3:::{bucket}/{prefix}/*` 有 `s3:PutObject` 權限。
  - **bucket 必須和呼叫端在同一個帳號**，不支援跨帳號。
  - 官方強烈建議這個 bucket 要加密，因為截圖裡可能有個資。
- 預設額度是每個帳號 10 萬個 definition。

> 後端類比：workflow definition 像 CI 系統裡的 pipeline 定義，workflow run 像 pipeline 的一次執行。definition 本身不含程式碼，程式碼在你的容器裡。

## 觸發與排程

官方文件沒有「排程」功能。觸發方式取決於運算平台：

- CLI：`act workflow run --name ... --payload '{...}'`
- AgentCore Runtime：`InvokeAgentRuntime` API（見 [AgentCore 01](../../01-runtime/)）
- Lambda / ECS：EventBridge Scheduler、SQS、API Gateway 等常見的觸發方式

> 推論：批次的情境（例如每天跑 1,000 筆資料）要自己設計扇出（fan-out）：用佇列控制併發數，讓 `InvokeActStep` 的總速率維持在配額內（預設 5 TPS，見 [00 配額](../00-overview/README.md#值得先知道的配額)）。

## 觀察：Console、CloudWatch、CloudTrail

### Nova Act Console

依層級查看：workflow definition 清單 → run 清單（狀態：succeeded / failed / in progress、起訖時間、下載 artifact）→ run 詳情（摘要、時間軸、**使用的 model ID**、artifact）→ Step view（深入某個 session、某個 act 的每一步）。

> 判斷：run 詳情會顯示 model ID，這對追查「模型升版後行為改變」很有用。建議搭配 [00](../00-overview/README.md#模型版本) 的版本固定策略一起使用。

### CloudWatch 指標（namespace `AWS/NovaAct`）

| 指標 | 單位 | 說明 |
|------|------|------|
| `Invocations` | Count | API 請求數 |
| `Latency` | ms | 端到端延遲，可以查 p50 / p90 / p99 |
| `UserErrors` | Count | 參數錯誤、ID 錯誤、IAM 權限不足 |
| `SystemErrors` | Count | 服務內部錯誤、相依服務失敗、逾時 |
| `Throttles` | Count | 被限流或超過配額 |

維度（dimension）只有 `Workflow` 和 `ApiName` 兩個。官方建議的告警：SystemErrors 超過門檻、Latency p90/p99 上升、Throttles 出現（表示該申請提高配額了）。

> ⚠️ 判斷：這些都是 **API 層級**的指標，**沒有「任務成功率」**。act 失敗（例如 `ActAgentFailed`）在服務看來可能是一次正常的 API 呼叫。業務層級的成功率要自己從程式裡發出自訂指標，或是從 run 的狀態統計。

### CloudTrail

| 類型 | 預設 | 包含的 API |
|------|------|-----------|
| 管理事件（控制面） | **有記錄** | `CreateWorkflowDefinition`、`Get/List/DeleteWorkflowDefinition`、`GetWorkflowRun`、`ListWorkflowRuns`、`ListSessions`、`ListActs`、`ListModels` |
| 資料事件（資料面） | **要自己開**（advanced event selectors） | `CreateSession`、`CreateAct`、`UpdateAct`、`InvokeActStep` |

- event source 是 `nova-act.amazonaws.com`。
- 資料事件可以用 ARN 過濾：`arn:aws:nova-act:{region}:{account}:workflow-definition/{name}`，或加上 `/workflow-run/{runId}`。
- 資料面的請求可能含有個資，所以部分欄位會被遮蔽。

> 推論：有一個怪地方。`CreateWorkflowRun` 和 `UpdateWorkflowRun` 出現在配額表的資料面 API 裡，但 CloudTrail 的兩張清單**都沒有列出**這兩個 API。想用 CloudTrail 稽核「誰觸發了哪次 run」之前，需要實測確認是否有記錄。

## 配額與容量

完整配額表見 [00](../00-overview/README.md#值得先知道的配額)。維運時最常碰到的三個：

1. `InvokeActStep` 5 TPS：平行度的天花板，要看 `Throttles` 指標。
2. 每個 act 最多 200 步：`max_steps` 設得再大也超不過這個上限。
3. 運算平台自己的上限：Lambda 15 分鐘、AgentCore Runtime microVM 8 小時（Instances 模式 14 天）。

## 研究問題

- [x] 部署路徑（CLI / IDE、CDK、自建）與自動建立的資源
- [x] Workflow definition 與 S3 匯出
- [x] Console、CloudWatch 指標、CloudTrail 的覆蓋範圍
- [x] 運算平台的選擇

## 參考資料

- [Step 3: Deploy to AWS](https://docs.aws.amazon.com/nova-act/latest/userguide/step-3-deploy.html)、[Step 4: Review workflow runs](https://docs.aws.amazon.com/nova-act/latest/userguide/step-4-review-workflow-runs.html)
- [Monitoring](https://docs.aws.amazon.com/nova-act/latest/userguide/monitoring-overview.html)、[CloudTrail](https://docs.aws.amazon.com/nova-act/latest/userguide/logging-using-cloudtrail.html)、[Quotas](https://docs.aws.amazon.com/nova-act/latest/userguide/load-balancer-limits.html)
- [Configure access to an S3 bucket](https://docs.aws.amazon.com/nova-act/latest/userguide/security-iam-s3-export-permissions.html)、[Glossary](https://docs.aws.amazon.com/nova-act/latest/userguide/glos-chap.html)
- [Nova Act CLI README](https://github.com/aws/nova-act/blob/main/src/nova_act/cli/README.md)、[nova-act-samples/cdk](https://github.com/amazon-agi-labs/nova-act-samples/tree/main/cdk)

## 延伸調研方向

範圍在 Nova Act 00–02 之內，以 02 為主：

1. **正式環境的部署樣板：** 用 CDK 把 workflow definition（含加密的 S3 匯出）、運算平台、IAM role 寫成一個可以重複使用的 stack，取代 CLI 的本機 state。另外實測確認 CDK README 裡 API key 前置步驟和 IAM 驗證說法的矛盾。
2. **業務層級的可觀測性：** 在 `AWS/NovaAct` 的 API 指標之外，補上「任務成功率、每次 run 的步數、agent hour」這些自訂指標與儀表板，並串起 run ID、CloudTrail 資料事件和 S3 trajectory，讓一次失敗可以從頭追到尾。
3. **批次執行的排程與流量控制：** 設計一個 SQS + worker 的扇出架構，把 `InvokeActStep` 的總速率控制在配額內。另外比較 Lambda（15 分鐘上限）和 Fargate、AgentCore 在長流程下的成本與失敗重跑策略。
