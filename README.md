# AgentCore + Nova Act 研究

研究 Amazon Bedrock AgentCore 與 Amazon Nova Act 的筆記與實驗。AgentCore 每個元件一個資料夾，可以各自展開研究；Nova Act 放在 [`nova-act/`](nova-act/) 區塊。

## 架構速覽

```text
User Request → Runtime → Gateway → Policy (Cedar) → Backend / Tools
                  │         │
                  │         └─ Identity（inbound 驗證 / outbound 憑證）
                  ├─ Memory（短期 / 長期記憶）
                  ├─ Payments（x402 自動付費）
                  ├─ Built-in Tools（Code Interpreter / Browser / Web Search）
                  │                                 ▲ CDP
                  │        Nova Act（瀏覽器 agent：看畫面 → 決定下一步；推論在 us-east-1 的 Nova Act 服務）
                  └─ Observability（OTel → CloudWatch） → Evaluations
```

Nova Act 不取代 AgentCore，而是疊在上面：workflow 程式跑在 Runtime，瀏覽器用 Browser，Identity / Observability / Gateway 照常接上（見 [nova-act/04](nova-act/04-agentcore/)）。

## 元件索引

| # | 元件 | 一句話定位 | 狀態 |
|---|------|-----------|------|
| 00 | [總覽](00-overview/) | 整體架構、計費、跟 Bedrock Agents 的差別 | ✅ 完成 |
| 01 | [Runtime](01-runtime/) | Serverless 的 agent / tool 執行環境 | ✅ 完成 |
| 02 | [Memory](02-memory/) | 代管的短期 / 長期記憶 | ✅ 完成 |
| 03 | [Gateway](03-gateway/) | agent 流量的統一入口：MCP 工具、HTTP 代理、LLM 代理（含 Registry） | ✅ 完成 |
| 04 | [Identity](04-identity/) | Agent 的身分與憑證管理 | ✅ 完成 |
| 05 | [Built-in Tools](05-built-in-tools/) | Code Interpreter、Browser、Web Search | ✅ 完成 |
| 06 | [Observability](06-observability/) | OTel 追蹤與監控 | ✅ 完成 |
| 07 | [Evaluations](07-evaluations/) | agent 品質評估與 Optimization（建議 + A/B test） | ✅ 完成 |
| 08 | [Policy](08-policy/) | 用 Cedar / Dogwood 做工具呼叫的確定性授權（含 temporal、Guardrails） | ✅ 完成 |
| 09 | [Payments](09-payments/) | agent 自動付費（x402 / MPP）與預算控管 | ✅ 完成 |
| 90 | [框架整合](90-integrations/) | 框架 × 元件對照：Strands、LangGraph、Claude Agent SDK 等 | ✅ 完成 |
| 91 | [技術選型調研工作包](91-work-packages/) | 把「每人一台對話 agent」的關鍵假設切成 8 個可發包的 AWS 實測工作包，每個檢核點標示來源等級、要求帳單數字 | 🔲 待領取 |

官方元件清單中的 Harness、Optimization、Registry 沒有獨立的資料夾，分別併入 [00 延伸](00-overview/harness-vs-runtime.md)、[07](07-evaluations/)、[03](03-gateway/)。

每篇文件的最後都有「延伸調研方向」，列出三個可以繼續深入的題目。

## Nova Act

AWS 的瀏覽器 UI 自動化 agent 服務：用自然語言 + Python 寫 workflow，由專門訓練的模型操作網頁，可以跑在 AgentCore Runtime / Browser 上。進度見 [nova-act/README.md](nova-act/)。

| # | 篇章 | 一句話定位 |
|---|------|-----------|
| 00 | [總覽](nova-act/00-overview/) | 定位、名詞、模型版本、計費（$4.75 / agent hour）、跟其他瀏覽器自動化方案的比較 |
| 01 | [SDK](nova-act/01-sdk/) | `act()` / `act_get()`、prompt 寫法、錯誤處理、平行執行、保存登入狀態 |
| 02 | [部署與維運](nova-act/02-deploy-operate/) | CLI / CDK 部署、Console、CloudWatch、CloudTrail |
| 03 | [HITL 與工具](nova-act/03-hitl-tools/) | 真人核准與接手、MCP 工具、當 Strands 的工具 |
| 04 | [跟 AgentCore 整合](nova-act/04-agentcore/) | Runtime、Browser、Identity、Observability、Gateway 的接法與成本 |
| 05 | [安全](nova-act/05-security/) | prompt injection、IAM 最小權限、資料保護、文件矛盾 |

## 目錄慣例

- 每個元件資料夾的 `README.md` 是研究主檔：核心概念、研究問題、與其他元件的關係、參考資料
- 內容多了再拆出子筆記（例如 `01-runtime/session-lifecycle.md`）
- 實作 / PoC 放在各元件底下的 `experiments/`
- 跨元件的參考資料放 `refs/`
- `nova-act/` 內部沿用同一套慣例（`00-overview/README.md` 這類編號資料夾）；它的延伸題範圍是「Nova Act 已研究的篇章」，可以引用 AgentCore 各篇

## 參考資料

AgentCore：

- [官方開發者指南](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [awslabs/agentcore-samples](https://github.com/awslabs/agentcore-samples)
- [aws/bedrock-agentcore-sdk-python](https://github.com/aws/bedrock-agentcore-sdk-python)
- [aws/bedrock-agentcore-starter-toolkit](https://github.com/aws/bedrock-agentcore-starter-toolkit)

Nova Act：

- [Nova Act 使用者指南](https://docs.aws.amazon.com/nova-act/latest/userguide/what-is-nova-act.html)
- [aws/nova-act](https://github.com/aws/nova-act)（SDK、CLI）
- [amazon-agi-labs/nova-act-samples](https://github.com/amazon-agi-labs/nova-act-samples)
- [AWS AI Service Card: Amazon Nova Act](https://docs.aws.amazon.com/ai/responsible-ai/nova-act/overview.html)
