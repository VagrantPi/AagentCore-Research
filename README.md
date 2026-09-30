# AgentCore 研究

研究 Amazon Bedrock AgentCore 的筆記與實驗。每個元件一個資料夾，可以各自展開研究。

## 架構速覽

```text
User Request → Runtime → Gateway → Policy (Cedar) → Backend / Tools
                  │         │
                  │         └─ Identity（inbound 驗證 / outbound 憑證）
                  ├─ Memory（短期 / 長期記憶）
                  ├─ Payments（x402 自動付費）
                  ├─ Built-in Tools（Code Interpreter / Browser / Web Search）
                  └─ Observability（OTel → CloudWatch） → Evaluations
```

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
| 09 | [Payments](09-payments/) | agent 自動付費（x402 / MPP）與預算控管 | 未開始 |
| 90 | [框架整合](90-integrations/) | Strands、LangGraph、Claude Agent SDK 等 | 未開始 |

## 目錄慣例

- 每個元件資料夾的 `README.md` 是研究主檔：核心概念、研究問題、與其他元件的關係、參考資料
- 內容多了再拆出子筆記（例如 `01-runtime/session-lifecycle.md`）
- 實作 / PoC 放在各元件底下的 `experiments/`
- 跨元件的參考資料放 `refs/`

## 參考資料

- [官方開發者指南](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)
- [awslabs/agentcore-samples](https://github.com/awslabs/agentcore-samples)
- [aws/bedrock-agentcore-sdk-python](https://github.com/aws/bedrock-agentcore-sdk-python)
- [aws/bedrock-agentcore-starter-toolkit](https://github.com/aws/bedrock-agentcore-starter-toolkit)
