# WP7 OpenClaw on AgentCore 官方範例實跑

> 回答：方案 A（OpenClaw 跑在 AgentCore Runtime）的真實延遲和成本是多少？拿來當 WP1（方案 B）和 WP6（方案 C）的對照組。
>
> 估點：3。優先序：7（風險低、價值低）。前置：WP0、WP3 建好的不開 NAT VPC（能力邊界測試用）。分群：A。

## 目標

部署 AWS 官方範例，拿到四個數字，並確認它的能力邊界能不能收緊。

## 前提

| 前提 | 來源等級 | 出處 |
|---|---|---|
| 官方範例：每位使用者一個 session；輕量替身 agent 約 23 秒先回、完整 OpenClaw 回覆約 70 秒；工作區 `~/.openclaw/` 鏡像到 session storage 並備份到 S3；cron 用 EventBridge 叫醒；預設 idle 30 分鐘、最長 8 小時 | 外部資料（範例 README 自述，未經本團隊實測） | [aws-samples/sample-host-openclaw-on-amazon-bedrock-agentcore](https://github.com/aws-samples/sample-host-openclaw-on-amazon-bedrock-agentcore) |
| 範例停用了 `read` 工具、channel 工具；`exec` 保留；Bedrock proxy 綁在 loopback | 外部資料 | 同上 |
| 大工作區（約 1,000 個檔案）還原要 80–115 秒 | 外部資料 | 同上 |

## 步驟

1. 照範例 README 部署（Telegram 或 Slack 任選一個 channel），資源加 tag `wp=WP7`。
2. 新使用者第一次發訊：記錄首則回覆、完整回覆的時間。
3. 等 idle 逾時後再發訊：記錄工作區還原時間（先在工作區塞 500 個小檔案）。
4. 模擬 10 位使用者各聊 10 輪，隔天拉帳單。
5. **能力邊界測試：** 以使用者身分要求「查今天的新聞」「幫我寫一支爬蟲抓某網站」，看 OpenClaw 會不會做（預期會，因為範例保留 `exec` 和上網）。再嘗試把 Runtime 改成 VPC 無 NAT（可借用 WP3 的 VPC），看 OpenClaw 還能不能啟動和回話。

## 檢核點

| # | 檢核點 | 來源等級 | 判定 |
|---|---|---|---|
| 1 | 首則回覆延遲（冷啟動） | 外部資料 | 秒 |
| 2 | 完整 OpenClaw 回覆延遲 | 外部資料 | 秒 |
| 3 | 500 個檔案的工作區還原時間 | 外部資料 | 秒 |
| 4 | 10 位使用者各 10 輪的實際費用，換算每位使用者月費 | 成本 | USD |
| 5 | 預設設定下，使用者能不能叫它做範圍外的事（上網、寫爬蟲） | `[推測]` | 是 / 否 |
| 6 | VPC 無 NAT 下 OpenClaw 能否啟動與回話 | `[推測]` | 是 / 否 |

## 判定對選型的影響

- 檢核點 1、2 和 WP1 的數字並列：方案 A 的首句延遲是方案 B 的幾倍。
- 檢核點 5 是「是」、6 是「否」→ 方案 A 的能力邊界無法在不拆 OpenClaw 的前提下收緊，列為阻斷項。

## 交付

- 本檔案下方的回填區。

## 關聯

- 研究庫：[01 Runtime](../01-runtime/README.md)（session storage、idle）、[90 框架整合](../90-integrations/README.md)
- 外部：[aws-samples/sample-host-openclaw-on-amazon-bedrock-agentcore](https://github.com/aws-samples/sample-host-openclaw-on-amazon-bedrock-agentcore)

## 回填

（複製 [`_template.md`](_template.md) 的內容到這裡）
