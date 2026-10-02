# WP6 不用 AgentCore 的開源方案

> 回答：如果不用 AgentCore，自架要用哪些元件拼出同樣的東西？每一層缺什麼？真實價格是多少？要多養幾個元件？
>
> 估點：A 半 5、B 半 5。優先序：6（風險低、價值中）。前置：無（可以和其他 WP 平行）。分群：A 負責第 1、5、6 層，B 負責第 2、3、4 層。

## 目標

給「自架」一個和方案 B 同尺度的對照。**不是做完整 PoC**，而是每一層選 2 個以上候選，填完「有 / 沒有 / 要自己做」，每層至少實測一個真實數字，價格一律用官網價或報價單。

## 前提

| 前提 | 來源等級 | 出處 |
|---|---|---|
| 自建每個元件的難度評估（低 / 中 / 高）是研究庫的工程判斷，沒有實際數據 | `[推測]` | [00 自建 vs 採用](../00-overview/build-vs-buy.md) |
| 自建比較便宜的情境是判斷，沒有數據 | `[推測]` | 同上 |
| OpenClaw 自架的建議規格是 2 vCPU / 4 GB / 40 GB；一個主程序服務一個人 | 外部資料 | 討論中引用的 OpenClaw 文件 |
| Harness 匯出的 Strands 程式碼可以部署到任何能跑 Python 3.12+ 的地方 | `[官方已寫]` | [00 Harness vs Runtime](../00-overview/harness-vs-runtime.md) |

## 要比較的層與候選

每層至少 2 個候選；同事可以增補，但增補的也要填滿同一張表。

| 層 | 對應的 AgentCore 元件 | 候選（起點） | 要回答的問題 |
|---|---|---|---|
| 1. 隔離執行環境（每人一台） | Runtime microVM | Firecracker 直接用（含 firecracker-containerd）、E2B（可自架）、Daytona、Kata Containers on EKS | 冷啟動秒數（實測一次）；每人每小時成本，**閒置時另列**；VM 回收與記憶體清除由誰負責；8 小時以上的長任務怎麼辦 |
| 2. Agent 框架與技能 | Harness / Strands、Skills | OpenClaw 自架（Lightsail 或 EC2 一人一台）、Strands、LangGraph、Claude Agent SDK | 技能格式（是否相容 SKILL.md）；工具白名單能否在框架**外**強制；一個程序能否同時服務一位使用者的多個聊天室 |
| 3. 工具閘道與授權 | Gateway + Policy（設計變更後改由自家 MCP server 負責，見 [WP2](WP2-capability-boundary.md#設計變更背景)） | 自家 MCP server 內嵌授權函式庫：OPA、Cedar（開源）、Casbin；或自架 MCP gateway 類專案 | 在自家 server 裡依使用者過濾 `tools/list`、檢查 `tools/call`、限流與計量，用哪個函式庫最省事；規則能不能做形式驗證 |
| 4. 雲端瀏覽器與接手 | Browser + Live View | Browserbase、Steel、自架 Chromium 加 noVNC 或 DCV | Live View 與接手是否內建；profile 保存；每小時價格（官網價）；手機瀏覽是否支援 |
| 5. 記憶 | Memory | 自管 Postgres + pgvector、Mem0、Zep | 跨使用者隔離靠什麼（schema、row-level security、各自的 collection）；萃取策略要不要自己寫 |
| 6. 可觀測與成本分攤 | Observability + USAGE_LOGS | OpenTelemetry + 任一後端、Langfuse | 每位使用者的成本能不能算出來 |

## 步驟

1. 每層先做 1 小時的文件調研，填「有 / 沒有 / 要自己做」。
2. 每層挑一個候選實測一個數字：第 1 層的冷啟動、第 2 層的「一個程序兩個聊天室同時發訊」、第 3 層的「依使用者過濾工具」要寫幾行、第 4 層的 Live View 開啟時間、第 5 層的一次寫入加檢索延遲。
3. 價格：到各候選的官網 Pricing 頁截圖，標日期；沒有公開價格的寫信要報價，沒拿到就填「無公開價格」。自架的用 AWS Pricing Calculator 算 EC2 加 EBS，**閒置時段另列**。
4. 列出自架相比 AgentCore **要自己維運的元件清單**（VM 排程、映像更新、瀏覽器更新、授權引擎、記憶萃取、監控），每項估點（費氏數列，定義見 [README](README.md#估點與排序原則)）。這一項允許標「估算」。
5. 把 [`00-overview/build-vs-buy.md`](../00-overview/build-vs-buy.md) 的「元件對照」表更正成實測後的版本。

## 檢核點

| # | 檢核點 | 來源等級 | 判定 |
|---|---|---|---|
| 1 | 六層都填完「有 / 沒有 / 要自己做」 | — | 表格完整 |
| 2 | 每層至少一個候選有實測數字 | — | 六個數字 |
| 3 | 每人每月成本有官網價或報價單，標日期；閒置時段另列 | 成本 | USD |
| 4 | 自架要自己維運的元件清單與估點 | `[推測]`（允許） | 清單 |
| 5 | 第 1 層：每人一台常駐 VM 時，100 位使用者的月費（含閒置） | 成本 | USD |
| 6 | 第 2 層：OpenClaw 自架時，能否在框架外強制工具白名單（不是靠 prompt） | `[推測]` | 是 / 否 |
| 7 | 第 4 層：有沒有候選能做到「使用者接手登入、交還後 agent 繼續」 | `[推測]` | 候選名稱 |
| 8 | 和 WP1、WP5 的數字並列後，方案 C 比方案 B 便宜的使用者規模門檻（如果有） | 成本 | 人數，或「無」 |

## 判定對選型的影響

- 檢核點 6、7 任一否定 → 方案 C 在能力邊界或接手登入有缺口，要加進決策矩陣的阻斷項。
- 檢核點 8 的門檻和產品預估的使用者數比較，決定方案 C 是否值得再投入。

## 交付

- 本檔案下方的回填區，包含六層的比較表、價格截圖路徑。
- 更正後的 [`00-overview/build-vs-buy.md`](../00-overview/build-vs-buy.md)。

## 關聯

- 研究庫：[00 自建 vs 採用](../00-overview/build-vs-buy.md)、[00 Harness vs Runtime](../00-overview/harness-vs-runtime.md)、[90 框架整合](../90-integrations/README.md)、[Nova Act 00 總覽](../nova-act/00-overview/README.md)（有和其他瀏覽器自動化方案的比較）

## 回填

（複製 [`_template.md`](_template.md) 的內容到這裡）
