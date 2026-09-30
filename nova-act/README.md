# Amazon Nova Act 研究

研究 Amazon Nova Act：AWS 的瀏覽器 UI 自動化 agent 服務。它包含自家訓練的模型、Python SDK / CLI / IDE 擴充，以及部署到 AWS 後的 workflow 管理與監控。

> 目前只開放 **us-east-1**（2026-09-30 查核）。可以跑在 AgentCore 的 [Runtime](../01-runtime/) 與 [Browser](../05-built-in-tools/) 上，詳見 [04](04-agentcore/)。

## 架構速覽

```text
Playground（試玩）→ SDK / IDE 擴充（本機開發）→ CLI 部署到 AWS → Console 檢視 workflow run
                         │
                         ├─ act()：用自然語言交代一件事，模型看畫面、一步一步操作瀏覽器
                         ├─ Human-in-the-loop：卡住或需要核准時轉給真人
                         └─ Tool use（Preview）：API、remote MCP、Strands
```

## 篇章索引

| # | 主題 | 一句話定位 | 狀態 |
|---|------|-----------|------|
| 00 | 總覽 | 定位、名詞、模型版本、介面、計費、跟其他瀏覽器自動化方案的比較 | ⏳ 待研究 |
| 01 | SDK | `act()` 與 agent loop、結構化輸出、prompt 寫法、平行 session | ⏳ 待研究 |
| 02 | 部署與維運 | 部署 workflow、檢視 run、監控、CloudTrail、配額 | ⏳ 待研究 |
| 03 | HITL 與工具 | 真人接手、API / MCP 工具、Strands | ⏳ 待研究 |
| 04 | 跟 AgentCore 整合 | 在 AgentCore Runtime / Browser 上跑 Nova Act | ⏳ 待研究 |
| 05 | 安全 | IAM、資料保護、prompt injection、負責任使用 | ⏳ 待研究 |

每篇最後的「延伸調研方向」，範圍限於 Nova Act 已研究的篇章（可引用已完成的 AgentCore 00–09、90）。

## 參考資料

- [Amazon Nova Act 使用者指南](https://docs.aws.amazon.com/nova-act/latest/userguide/what-is-nova-act.html)
- [Nova Act Playground](https://nova.amazon.com/act)
- [Amazon Nova 計費](https://aws.amazon.com/nova/pricing/)
