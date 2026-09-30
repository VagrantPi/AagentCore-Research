# Payments

> 讓 agent 能自動付費使用收費的 API、MCP server 與內容（x402 / MPP 協定），並提供錢包整合與花費上限控管。

## 核心概念

（待補）

## 研究問題

- [ ] x402 與 MPP 協定是什麼（HTTP 402 → 付款 → 帶憑證重試的流程）
- [ ] 資源模型：Credential Provider → Manager → Connector → Instrument → Session
- [ ] 錢包供應商（Coinbase CDP、Stripe Privy）與支援的鏈（EVM、Solana）
- [ ] 預算上限（`maxSpendAmount`）如何在基礎設施層強制執行
- [ ] IAM 角色職責分離（建立 session 與簽署付款分開）

## 與其他元件的關係

（待補）

## 實驗

實作放在本資料夾的 `experiments/`（需要時再建立）。

## 參考資料

- [官方文件](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments.html)
