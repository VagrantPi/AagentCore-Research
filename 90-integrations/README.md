# 框架整合

> 搭配其他 agent 框架使用 AgentCore：哪些框架可以接哪些元件、接法是什麼、有什麼差異與坑。
>
> 資料查核日期：2026-09-30。本篇橫跨 00–09，著重「框架 × 元件」的對照；各元件本身的細節請看對應的篇章。

## TL;DR

- **AgentCore 本身不綁定框架。** 任何框架（或不用框架）要接上 AgentCore，有三種方式：
  1. **框架專用的 adapter**：例如 Strands 的 memory session manager、LangGraph 的 checkpointer 和 store、Payments 的 plugin 或 middleware。整合最深，要寫的程式碼最少。
  2. **透過 Gateway 走 MCP**：任何支援 MCP client 的框架，都能使用 Gateway 上的工具、Memory connector、Web Search 等。**這是最通用的接法。**
  3. **直接呼叫 AWS SDK 或 AgentCore SDK**：例如 Identity 的 `@requires_access_token` 裝飾器、Code Interpreter 的 client，任何 Python 框架都能用。
- **Strands 是「一等公民」：** Harness 的底層就是 Strands，export 出來的程式碼也是 Strands，Payments plugin、Memory 和評估的整合也都最完整。**LangGraph 次之。**
- **Claude Agent SDK：** 可以部署到 Runtime（官方在 Bedrock Agents Classic 的遷移指南裡也列為可選的框架）；評估透過 OpenInference instrumentation 支援；**Harness export 成 Claude Agent SDK 程式碼的功能官方標示為「即將推出」**；但**它不會產生獨立的模型呼叫 span**。
- **語言：** 以 Python 為主，**TypeScript 也有完整支援**（AgentCore CLI、Strands TS、Node 22 CodeZip、Vercel AI SDK、LangGraph JS 的評估）。其他語言可以用 container 加上 AWS SDK。

## 框架 × 元件對照

「✓」表示官方有專屬的整合或文件；「MCP / SDK」表示要透過 Gateway 或自己呼叫 API；「—」表示官方文件沒有提到。

| 框架 | Runtime 部署 | Memory 原生整合 | 評估 / 可觀測的 instrumentation | Payments | Harness |
|------|:---:|:---:|------|:---:|:---:|
| **Strands**（Py / TS） | ✓ | ✓ `AgentCoreMemorySessionManager` | ✓ 內建 OTel（TS 版需要 ≥ 1.5.0） | ✓ plugin | **底層框架**；export 的目標 |
| **LangGraph / LangChain**（Py / TS） | ✓ | ✓ `langgraph-checkpoint-aws`（`AgentCoreMemorySaver` / `Store`） | ✓ OTel 或 OpenInference（Py）；ADOT、Traceloop、OpenInference（TS） | ✓ middleware | — |
| **OpenAI Agents SDK**（Py / TS） | ✓ | MCP / SDK | ✓ OTel 或 OpenInference | — | — |
| **Google ADK** | ✓ | MCP / SDK | ✓ OpenInference | — | — |
| **LlamaIndex** | ✓ | ✓（官方列為 Memory 支援的框架） | ✓ OTel 或 OpenInference | — | — |
| **Claude Agent SDK** | ✓ | MCP / SDK | ✓ OpenInference（≥ 0.1.3）；⚠️ 只有 `AGENT` 和 `TOOL` span | — | export 功能「即將推出」 |
| **Vercel AI SDK**（TS） | ✓（Node 22） | MCP / SDK | ✓ ADOT-native | — | — |
| **CrewAI** | ✓（官方列在 Runtime 支援的框架中） | MCP / SDK | Observability 有提到 CrewAI；**評估的支援清單裡沒有**，只能走通用的 instrumentation | — | — |
| 自己寫的迴圈 | ✓（只要符合 HTTP 契約即可） | SDK | 自訂 OTel span，遵循 GenAI semantic conventions | 自己呼叫 `ProcessPayment` | — |

## 各元件的接法摘要

| 元件 | 通用接法 | 框架專用的接法 |
|------|---------|--------------|
| **Runtime（01）** | 包一層 `BedrockAgentCoreApp` 的 `@app.entrypoint`，或自己實作 `/invocations` 和 `/ping` | 官方範例：Strands、LangGraph、ADK、OpenAI Agents |
| **Memory（02）** | `MemoryClient` 或 AWS SDK 的 `CreateEvent` / `RetrieveMemoryRecords`；或透過 Gateway 的 Memory connector 走 MCP | Strands：session manager（`batch_size > 1` 時**一定要 `close()` 或用 `with`**，否則還沒送出的訊息會遺失）；LangGraph：`AgentCoreMemorySaver` 對應短期記憶和 checkpoint，`AgentCoreMemoryStore` 對應長期記憶（`thread_id` 對應 session、`actor_id` 對應 actor） |
| **Gateway（03）** | 任何 MCP client（streamable HTTP） | 各框架的 MCP adapter，例如 Strands 的 `MCPClient`、`langchain-mcp-adapters` |
| **Identity（04）** | `@requires_access_token`、`@requires_api_key` 裝飾器（Python），或 AWS SDK | — |
| **內建工具（05）** | SDK 的 `code_session`、browser client；Browser 可以接 Playwright、browser-use、[Nova Act](../nova-act/04-agentcore/) | Strands 有內建的工具包裝 |
| **Observability（06）** | ADOT 加上 `opentelemetry-instrument` | 依框架選擇 instrumentation 套件（見上表） |
| **Evaluations / Optimization（07）** | 只要 span 符合支援的 scope name 就能評估；讀取 configuration bundle 用 `BedrockAgentCoreContext.get_config_bundle()` | 官方有 Strands（hook）、LangGraph、ADK、OpenAI SDK 讀取 bundle 的範例 |
| **Policy（08）** | 在 Gateway 上生效，**跟框架無關** | — |
| **Payments（09）** | `PaymentManager.generate_payment_header()`，或直接呼叫 `ProcessPayment` | Strands：`AgentCorePaymentsPlugin`；LangGraph：`AgentCorePaymentsMiddleware` |

**判斷：** 能走 MCP 的就走 MCP（例如工具、Memory connector），**框架之間的差異就能降到最低**，以後要換框架也比較容易。只有在需要「深入框架內部生命週期」的功能時，才使用框架專用的 adapter，例如 checkpoint、每次呼叫模型前的 hook、自動攔截 402。

## Claude Agent SDK 的重點

- **什麼是 Claude Agent SDK：** 就是 Claude Code 背後的 agent 框架。內建檔案操作、shell、MCP 等工具，特別擅長 coding 和處理檔案類的任務（見 [01 coding agent 架構](../01-runtime/coding-agent-architecture.md)）。
- **在 AgentCore 上的位置：**
  - **Runtime：** 屬於「程式碼定義的 agent」這條路線，官方在 Bedrock Agents Classic 的遷移指南中也把它列為可選的框架之一。
  - **工具：** 把 Gateway 當成遠端的 MCP server 接上，就能同時取得 Policy、Identity 等治理能力。
  - **模型：** 可以透過 Bedrock 使用 Claude。
  - **評估：** 使用 `openinference-instrumentation-claude-agent-sdk`（≥ 0.1.3）；在 Runtime 上由 ADOT 自動啟用，只要把套件加進相依清單就好。
- **⚠️ 評估上的差異：** 這個 instrumentation **只會產生 `AGENT` 和 `TOOL` 兩種 span，沒有獨立的模型呼叫 span**。模型名稱和 token 用量記錄在 `AGENT` span 上。所以**依賴「模型呼叫 span」的分析或評估方式**要另外調整（判斷）。
- **Harness 的關係：** Harness 目前只能 export 成 Strands，Claude Agent SDK 的版本官方標示為「即將推出」。

## 延伸：Bedrock Managed Agents（with OpenAI，預覽中）

00 當時標註「未經官方確認」的這項產品，**現在已經有官方文件**：

- 由 AWS 執行 **OpenAI Codex 的 harness**（agent 迴圈），模型是 `openai.gpt-5.6-luna`。
- 需要執行指令或處理檔案時，才把工作交給「**環境**」。這個環境可以是你本機的 `codex exec-server`，或是**你帳號裡的 AgentCore Runtime**（每個 session 一台 microVM，可以接 VPC，也可以用 Instances）。
- **模型呼叫留在 Bedrock Managed Agents 那一側**，你的 container 只負責執行 agent 送過來的指令。
- 呼叫端使用 OpenAI SDK 的 `client.beta.agents`，端點是 `bedrock-mantle`。
- **定位：** 跟 AgentCore Harness（底層是 Strands）是**平行的「代管 harness」選項**，差別在 agent 迴圈的實作與模型供應商。

## 選框架的建議（判斷）

| 情境 | 建議 |
|------|------|
| 新專案，想用最多 AgentCore 功能、寫最少程式碼 | **先用 Harness**；需要自己掌控迴圈時再 export 成 Strands |
| 需要 graph 或 workflow 式的編排、狀態機 | LangGraph（Memory、Payments、評估的整合都很完整） |
| Coding agent、大量檔案與 shell 操作 | Claude Agent SDK，或 Harness（內建 shell 和檔案工具）；評估時要注意 span 結構的差異 |
| 團隊已經熟悉某個框架 | 沿用原本的框架，透過 MCP 或 SDK 接上 AgentCore，**不必為了 AgentCore 換框架** |
| TypeScript 為主的團隊 | Strands TS 或 Vercel AI SDK，搭配 Node 22 CodeZip 部署 |

## 踩雷清單

1. **Instrumentation 套件的版本有最低要求**，例如 LangGraph 的 OTel 需要 ≥ 0.55.0、Claude Agent SDK 需要 ≥ 0.1.3；版本不夠，評估服務會讀不懂 span。
2. **評估服務是依 span 的 scope name 判斷是哪個框架**，自己改寫或包裝 instrumentation 的話，可能會導致無法評估。
3. **Claude Agent SDK 沒有模型呼叫 span。**
4. **Strands Memory 的 `batch_size > 1` 時，一定要 `close()`**，否則最後一批訊息會遺失。
5. **LangGraph 的 `thread_id` 和 `actor_id` 是對應到 Memory 的 session 和 actor 的必填欄位**，要跟 Runtime 的 session 設計一致。
6. **Payments 的自動 402 處理只有 Strands 和 LangGraph 有**；其他框架要自己攔截 402 並呼叫 API。
7. **CrewAI 不在評估支援的框架清單裡。**
8. **Harness 只能 export 成 Strands**（Claude Agent SDK 版即將推出）。

## 研究問題

- [x] Strands Agents
- [x] LangGraph / LangChain
- [x] Claude Agent SDK
- [x] CrewAI、LlamaIndex 等其他框架（另外補充 OpenAI Agents、ADK、Vercel AI SDK）
- [x] 各框架接 Memory、Gateway、Observability 的方式

## 參考資料

- [Use any agent framework](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html)
- [Supported frameworks（評估）](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks.html)、[Claude Agent SDK](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-claude-agent-sdk.html)
- [Memory × LangChain / LangGraph](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-integrate-lang.html)、[Memory × Strands](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/strands-sdk-memory.html)
- [TypeScript get started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli-typescript.html)
- [Bedrock Managed Agents（with OpenAI）](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-bma.html)
- [Bedrock Agents Classic 遷移（程式碼定義 agent 的框架清單）](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-classic-maintenance-mode.html)
- [awslabs/agentcore-samples：03-integrations](https://github.com/awslabs/agentcore-samples)

## 延伸調研方向

範圍在 00–09 與 90 之內，以 90 為主：

1. **Claude Agent SDK on AgentCore 的完整參考架構：** 部署到 Runtime 的 container 設計、透過 Gateway 取得工具與 Policy、Memory 走 MCP connector、Identity 的 token 取得方式；評估時如何補上「模型呼叫 span」不足的部分；並跟 Harness 比較開發與維運成本。
2. **框架中立的整合策略：** 以 MCP 為核心的「換框架也不用重寫」架構，也就是工具、Memory、Web Search 都經過 Gateway。量化這種做法跟使用框架專用 adapter 在功能和延遲上的差距，以及遷移框架時需要改動的範圍。
3. **LangGraph 與 Strands 的 AgentCore 整合深度比較：** 用同一個情境（客服 agent）分別實作，比較 Memory（checkpoint 和 store vs session manager）、Payments（middleware vs plugin）、評估（span 結構）、configuration bundle 的讀取方式，以及從 Harness export 之後改用 LangGraph 的遷移成本。
