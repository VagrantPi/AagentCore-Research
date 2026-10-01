# Observability

> 用 OpenTelemetry 追蹤、除錯、監控 agent：每一步呼叫了哪個模型、用了哪個工具、花了多少 token、在哪裡出錯。
>
> 資料查核日期：2026-09-30。Harness 的可觀測性（預設全開）見 [00 延伸](../00-overview/harness-vs-runtime.md)；Memory 萃取相關的 metric 見 [02](../02-memory/README.md#營運與可觀測)。

## TL;DR

- **Agent 的除錯比一般服務難：** 同樣的輸入，模型每次可能走不同的路徑，所以「重現問題」很困難，**trace 幾乎是唯一能事後還原「它當時為什麼這樣做」的依據**。
- **資料有三層：**
  - **Session**：一整段對話。
  - **Trace**：一次請求和回應。
  - **Span**：其中一個步驟，例如一次模型呼叫、一次工具呼叫。
  - 全部走 **OTel** 標準，並遵循 **GenAI semantic conventions**（OTel 為 LLM 定義的屬性名稱，例如 token 用量、模型名稱）。
- **服務本身自動提供的：** Runtime、Memory、Gateway、內建工具、Identity 的 metric，以及部分 span 和 log。**agent「內部」的 span**（呼叫模型、呼叫工具）**要在 agent 程式裡加上 ADOT 才會有**。Harness 則是預設全開。
- **一次性的前置作業：** 要先在帳號裡**開啟 CloudWatch Transaction Search**，否則看不到 span。
- **不跑在 AgentCore 上的 agent 也能用：** 在 EKS 或 Lambda 上的 agent，設定好 ADOT 和環境變數也能送進來。反過來，想送到 Datadog、Langfuse 等其他平台時，設 `DISABLE_ADOT_OBSERVABILITY=true`。
- ⚠️ **資料外洩風險：** application log 會記錄**完整的請求與回應 payload**，span 也可能包含 prompt 和工具的輸入輸出。**等於把使用者的對話內容全部寫進 CloudWatch**，要事先規劃存取權限、加密和保留期限。

## 為什麼 agent 需要專門的可觀測性

| 一般服務 | Agent |
|---------|-------|
| 同樣的輸入，走同樣的程式路徑 | 同樣的輸入，**模型每次可能選不同的工具、走不同的步數** |
| 錯誤通常是例外或 5xx | 很多「錯誤」是**語意上的**：回答錯了、選錯工具、陷入迴圈，但 HTTP 狀態碼是 200 |
| 延遲主要來自 I/O | 延遲主要來自**模型推論**，而且跟輸出的 token 數量成正比 |
| 成本大致與請求數成正比 | 成本**與 token 用量成正比**，差異可能到百倍，必須逐次追蹤 |

所以 agent 的 trace 除了時間之外，還要記下**模型的輸入輸出、選了哪個工具、工具的參數和結果、token 用量**。這也是 [07-evaluations](../07-evaluations/) 能自動評分的原始資料。

## 資料模型與存放位置

```
Session（session.id，透過 header 或 OTel baggage 傳遞）
└── Trace（一次 invoke）
      └── Span 樹
            ├── InvokeAgentRuntime（服務自動產生）
            ├── agent loop（框架產生，需要 ADOT）
            │     ├── chat / invoke_model（模型呼叫：模型名稱、token 數、可選的 prompt 與回應內容）
            │     ├── execute_tool（工具名稱、參數、結果）
            │     └── …
            └── Memory / Gateway / Identity 的呼叫（這些服務各自產生的 span）
```

| 資料 | 存放位置 |
|------|---------|
| **Span** | 新建立的 Runtime agent：`/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint>` 這個 log group 裡的 `spans` stream（**每個 agent 各自獨立**，需要 ADOT ≥ 0.18.0）。舊的 agent：共用的 `aws/spans` log group。可以用 `UNIFIED_TRACES_DESTINATION_ENABLED` 切換 |
| stdout / stderr | 同一個 log group 的 `runtime-logs` stream |
| OTel 結構化 log | `…/otel-rt-logs` |
| Agent 自訂的 metric | CloudWatch Metrics 的 `bedrock-agentcore` namespace（EMF 格式） |
| 服務提供的 metric | `AWS/Bedrock-AgentCore` namespace |
| Memory / Gateway / 內建工具的 log | 要自己設定 delivery（送到 CloudWatch Logs、S3 或 Firehose） |
| 瀏覽介面 | CloudWatch 的 **GenAI Observability** 頁面：agent → session → trace 逐層往下看，另外有 Transaction Search |

**把 span 放在每個 agent 自己的 log group 有什麼好處：** 可以**針對個別 agent 設定存取權限和 KMS 加密**，也比較方便匯出。這對多團隊或多租戶的情境很重要。

## 服務自動提供的資料

### Runtime 的 metric

| Metric | 用途 |
|--------|------|
| `Invocations`、`Latency`（端到端，到最後一個 token 為止） | 流量與延遲 |
| `Throttles`、`SystemErrors`、`UserErrors` | 錯誤分類：throttle 回 429；quota 回 **402**（見 [01](../01-runtime/)） |
| `SessionCount`（新建立的 session 數，**累計值**） | 使用趨勢 |
| **`ActiveSessionCount`**（**目前進行中的 session 數**，可以依 Runtime、CodeInterpreter、Browser 篩選） | **監控 session 配額的用量**，建議對它設警報 |
| `CPUUsed-vCPUHours`、`MemoryUsed-GBHours` | 資源用量，接近帳單上的數字，**但最多延遲 60 分鐘，而且不等於實際帳單** |
| WebSocket 相關：`ActiveStreamingConnections`、進出的 byte 數 | 雙向串流的容量規劃 |

### Log

| 類型 | 內容 | 注意事項 |
|------|------|---------|
| `APPLICATION_LOGS` | 每次呼叫的 trace/span ID，**加上 `request_payload` 和 `response_payload`** | **包含使用者的完整對話內容** |
| `USAGE_LOGS` | 每個 session 每秒的 vCPU-hours 和 GB-hours | 可以用來把成本分攤到個別 session 或使用者（官方文件的說法，尚未實測；由 [WP0](../91-work-packages/WP0-cost-baseline.md)、[WP5](../91-work-packages/WP5-user-state-isolation.md) 驗證） |

## 在 agent 程式裡加上 instrumentation

| 情境 | 做法 |
|------|------|
| **Runtime 上的 agent** | 加上 `aws-opentelemetry-distro>=0.18.0`，用 `opentelemetry-instrument python main.py` 啟動；框架本身要開啟 OTel（Strands 內建支援；LangChain、CrewAI 等可以用 OpenInference、OpenLLMetry、OpenLit、Traceloop 等 instrumentation 套件） |
| **跑在 AgentCore 之外的 agent**（EKS、EC2） | 同上，另外設定 `AGENT_OBSERVABILITY_ENABLED=true`、`OTEL_PYTHON_DISTRO=aws_distro`、`OTEL_RESOURCE_ATTRIBUTES=service.name=…,aws.log.group.names=…`、`OTEL_EXPORTER_OTLP_LOGS_HEADERS=x-aws-log-group=…`、`OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` 等環境變數；**session ID 要透過 OTel baggage 帶入**（`session.id`） |
| **Lambda 上的 agent** | 使用 AWS 的 OpenTelemetry Lambda Layer，並設定 `AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-instrument` |
| **送到其他可觀測性平台** | 在 Runtime 上設定 `DISABLE_ADOT_OBSERVABILITY=true`，取消預設的 ADOT 設定，再自行設定要送去的 exporter |
| **Harness** | 預設全開，不需要任何設定 |

- **不支援 ADOT Collector：** 只能直接用 ADOT SDK 或 Lambda Layer 送出。
- **跨服務串接 trace：** 呼叫時帶上 `X-Amzn-Trace-Id`（X-Ray 格式）或 `traceparent`（W3C 格式），以及 `baggage`。內建工具和 Identity 的 API 也接受這些 header，可以把整條 trace 串起來。
- **`AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT=true`：** 官方的說明是「讓模型的 payload 和工具的請求與回應**保留在 span 上**」。**這個變數名稱看起來像是「不要擷取內容」，實際效果卻相反**，上線前要實測確認 span 裡到底有沒有 prompt 內容。

## 隱私、成本、多帳號

### 隱私（判斷）

- **Log 和 span 裡都可能有個人資料：** application log 會記錄 payload；span 可能包含 prompt 和工具的結果；JWT 的 `sub` 會出現在 CloudTrail（見 [03](../03-gateway/)）。
- **建議做法：**
  - Log group 使用 **KMS CMK** 加密，依照法規設定保留天數。
  - 用 CloudWatch Logs 的**資料保護政策**（data protection policy）遮罩個資。這是 CloudWatch 的功能，會額外收費。
  - 不想讓 prompt 內容落地的話，確認 span 的內容擷取設定，並且不要開啟 `APPLICATION_LOGS`，或是在前面加一道遮罩。
  - 使用「每個 agent 獨立 log group」的做法，把存取權限限縮到負責該 agent 的團隊。

### 成本

- 費用全部依 CloudWatch 的價格計算：span 的 ingestion 大約每 GB $0.35、log 大約每 GB $0.50，另外還有儲存和查詢費用（見 [00](../00-overview/README.md#計費模型)）。
- **Agent 的 span 很大：** 內容包含 prompt 和回應，一輪對話就可能有數 KB 到數十 KB，工具的結果如果是長文件會更大。**流量大的時候，CloudWatch 的費用可能超過 Runtime 本身**（判斷）。
- **控制方式：**
  - Transaction Search 的**索引抽樣比例**（`UpdateIndexingRule`）。
  - 縮短 log 的保留期限。
  - 只在需要的環境開啟 payload 記錄。

### 多帳號

- 使用 CloudWatch 的 **cross-account observability**（OAM 的 sink 和 link），就能在一個監控帳號裡看到所有來源帳號的 agent。
- 需要分享 **Metrics 和 Logs** 兩種資料。
- **只能在同一個區域內使用。**
- 部分操作（例如跳到 Bedrock Console 查看資源細節）必須登入來源帳號才能做。

## 建議的警報（判斷）

| 警報 | 依據 |
|------|------|
| Session 配額快用完 | `ActiveSessionCount` 超過配額的 80% |
| Throttle 或 quota 錯誤增加 | `Throttles`、`UserErrors` 裡的 `ServiceQuota` |
| 延遲異常 | `Latency` 的 p90 |
| 記憶萃取失敗 | Memory 的 `FailedExtraction`（見 [02](../02-memory/)） |
| 成本異常 | `CPUUsed-vCPUHours` / `MemoryUsed-GBHours` 的日增量，搭配 Budgets |
| Agent 陷入迴圈 | 單一 trace 裡工具呼叫的次數或 token 數超過門檻（要從 span 算出來，例如用 Logs Insights 查詢） |

## 踩雷清單

1. **沒開 Transaction Search 就看不到 span**，這是帳號層級的一次性設定。
2. **Agent 內部的 span 需要 ADOT**，只有 Runtime 服務本身自動產生的 span 不夠用。Harness 例外，預設全開。
3. **ADOT 版本要 ≥ 0.18.0**，才能把 span 送到 agent 自己的 log group。
4. **`APPLICATION_LOGS` 會記錄完整的 payload。**
5. **`AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT` 的名稱和實際行為看起來相反**，要實測確認（列在 [WP5](../91-work-packages/WP5-user-state-isolation.md) 的檢核點）。
6. **資源用量的 metric 最多延遲 60 分鐘，而且不等於帳單。**
7. **不支援 ADOT Collector。**
8. **跨帳號監控只能在同一個區域內使用。**
9. **Memory、Gateway、內建工具的 log delivery 要自己設定**，預設不會送出。

## 與其他元件的關係

- **Runtime / Harness：** 產生最主要的 metric 和 span；Harness 預設全開。
- **Memory / Gateway / Identity / 內建工具：** 各自有服務提供的 metric、log 和 span，要分別開啟 tracing 和 log delivery。
- **Evaluations（07）：** 用這裡收集到的 trace 和 span 做評分，所以**沒有 observability 就沒辦法做線上評估**。
- **Nova Act：** 用 ADOT 加上 OTel baggage 帶入 Nova Act 的 session ID，把 trace 和 Nova Act Console 的逐步紀錄串起來（見 [Nova Act 04](../nova-act/04-agentcore/README.md#observability接上-cloudwatch-trace)）；Nova Act 自己另有 `AWS/NovaAct` 指標（見 [Nova Act 02](../nova-act/02-deploy-operate/README.md#觀察consolecloudwatchcloudtrail)）。

## 研究問題

- [x] OTel 整合方式（ADOT）
- [x] CloudWatch / X-Ray 上能看到哪些 trace 與 metric
- [x] 非 Runtime 部署的 agent 要怎麼接
- [x] 自訂 span 與屬性（框架的 instrumentation、GenAI semantic conventions、baggage）

## 參考資料

- [Observability concepts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-telemetry.html)
- [Add observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)
- [Runtime observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html)
- [View observability data](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-view.html)
- [Cross-account monitoring](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-cross-account.html)
- [OTel GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)

## 延伸調研方向

範圍在 00–06 之內，以 06 為主：

1. **可觀測資料的隱私治理：** 實測 `APPLICATION_LOGS`、span 內容擷取設定、`AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT` 實際記錄了什麼；搭配 CloudWatch 資料保護政策、KMS、每個 agent 獨立 log group 的最小權限設計。
2. **Agent 可觀測性的成本模型：** 估算每一輪對話的 span 和 log 大小，用抽樣、保留期限、只在部分環境記錄 payload 等方式控制 CloudWatch 費用，並跟 Runtime 本身的費用比較。
3. **用 trace 做 agent 行為分析與告警：** 用 Logs Insights 從 span 算出每個 trace 的工具呼叫次數、token 數、迴圈偵測、工具失敗率，做成 dashboard 和警報，並把 Memory、Gateway、Identity 的 span 串成完整的 trace。
