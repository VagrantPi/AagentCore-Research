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
| 4. 雲端瀏覽器與接手 | Browser + Live View | Browserbase、Steel、自架 Chromium 加 noVNC 或 DCV（本機瀏覽器 ego (lite) 已評估、不採用，見 [README](README.md#評估過不採用)） | Live View 與接手是否內建；profile 保存；每小時價格（官網價）；手機瀏覽是否支援 |
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

### A 半：第 1、5、6 層（文件調研階段）

- 負責人：Kais
- 執行日期：2026-10-02（文件與價格調研；實測未做）
- 區域：ap-northeast-1（東京）
- 資源 tag：`wp=WP6`、`owner=kais`、`project=hyfai`（本階段沒有建立 AWS 資源）
- 使用的 AWS 帳號：無（沒有碰 AWS）
- 價格截圖：[`evidence/WP6/`](evidence/WP6/)，檔名 `L{層}-<候選>-pricing-2026-10-02.png`
- AWS 價格出處：EC2、EBS、RDS、ElastiCache、S3 的價格頁是動態載入，截圖看不到東京價。東京單價取自 AWS 官方 Price List 公開檔 `https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/<服務>/current/ap-northeast-1/index.json`（EC2 版本 20260925174521）。截圖只當頁面證據，不是價格出處。
- 月時數用 730 h；「每天活躍 8 h」= 243.3 h/月，其餘 486.7 h 停機。

#### 結論（三句內）

1. 第 1 層「每人一台強隔離 VM」不一定要自己寫排程器：可以買 E2B 託管，或用 Kata on EKS（中）。純 Firecracker 自寫才是高難度。100 人 24h 常駐時，託管約 $12.2k/月，自架約 $9.0k/月。
2. 第 5 層：Mem0、Zep 有現成的萃取與檢索，但跨使用者隔離大多靠應用程式帶 `user_id`。只有自管 pgvector 加 RLS 能在資料層強制。100 人規模的 AgentCore Memory 約 $45/月，比 Mem0（$249）、Zep（$150–300）便宜。
3. 第 6 層：LLM 成本可以算到每位使用者（Langfuse、Phoenix 有內建價格表）。VM、瀏覽器、記憶這些非 LLM 成本沒有任何候選現成提供，要自己維護 session→user 對照再合併。

#### 第 1 層：隔離執行環境

| 能力 | Firecracker 直接用 | E2B 託管 | E2B 自架 | Daytona | Kata on EKS |
|---|---|---|---|---|---|
| 每人一台隔離 VM | 有，排程、網路、映像要自己做 | 有（每 sandbox 一台 Firecracker microVM） | 有，要自己部署 | **預設是 container，不是 VM**；VM sandbox 現行文件已不標 beta，但只能從既有 VM snapshot 建立 `[矛盾]` | 有，要 nested virtualization 或 bare metal |
| VM 回收與記憶體清除 | 要自己做；官方警告同一 snapshot 不能重複還原 | 官方沒寫；暫停時記憶體整份保存 | 要自己做 | 官方沒寫 | 隨 pod 刪除，細節官方沒寫 `[推測]` |
| 縮到 0 | 要自己做 | 有（按秒計費） | 要自己做 | 有：container 用 auto stop、archive；VM 用 stop／pause（預設 60 分鐘 auto-pause），VM 沒有 archive | 要自己設 autoscaler `[推測]` |
| 8 小時以上長任務 | 有，沒有上限 | Pro 單次 24h，可 pause/resume 接續 | 沒有平台上限 | 文件沒寫 | 有 `[推測]` |
| pause/resume | snapshot 有，管理層要自己做 | 有（暫停約 4 秒/GiB、還原約 1 秒） | 有（內建） | 只有 VM sandbox | 沒有，只能保存 PVC `[推測]` |
| 官方宣稱冷啟動 | ≤125 ms（只算 VMM 到 init、1 vCPU/128 MiB） | resume 約 1 秒；create 沒寫 | 同左 | 「sub 90ms」（行銷頁，應指 container） | 沒寫 |

- 來源：[Firecracker SPECIFICATION](https://github.com/firecracker-microvm/firecracker/blob/main/SPECIFICATION.md)、[E2B persistence](https://docs.e2b.dev/sandbox/persistence)、[e2b-dev/infra](https://github.com/e2b-dev/infra)、[Daytona VM sandboxes](https://www.daytona.io/docs/en/sandboxes/#vm-sandboxes)、[Daytona billing](https://www.daytona.io/docs/en/billing/)、[E2B 價格 FAQ](https://docs.e2b.dev/faq/calculate-sandbox-price)、[Kata install](https://github.com/kata-containers/kata-containers/blob/main/docs/install/README.md)、[EC2 nested virtualization](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/amazon-ec2-nested-virtualization.html) `[官方已寫]`
- AWS 上跑 Firecracker 或 Kata 要 nested virtualization：只支援 C7i/C8i、M7i/M8i、R7i/R8i 等 Intel 家族，**不支援 Graviton**，不另收費，AWS 建議延遲敏感的負載用 bare metal `[官方已寫]`。
- `[矛盾]` Daytona：VM sandbox 在 2026-10-02 的文件已不標 beta，列為正式 sandbox class（`daytona-vm-small/medium/large`），但官方也沒寫 GA。VM 啟動秒數官方沒寫。
- `[矛盾]` E2B infra README 有一段提到「AWS and GCP」，同頁又說 Terraform 只有 GCP，並寫「evaluation package, not a production deployment pattern」。以 Terraform 只有 GCP 為準：E2B 自架在 AWS 要自己移植。

**每人每小時成本**（基準 2 vCPU / 4 GB / 40 GB）

| 候選 | 運行中 | 閒置 |
|---|---|---|
| E2B 託管 | $0.1656/h（vCPU $0.1008 + RAM $0.0648），另加 Pro $150/月 | 暫停不收 vCPU／RAM 費 `[官方已寫]`（「Paused and killed sandboxes are not billed」）；暫停的 sandbox 無限期保留。儲存費官方沒寫（`[推測]` 不收，磁碟含在費率內）。Pro 寫「20+ GiB」，但沒有加購價、沒寫能否設 40 GB |
| Daytona | $0.16938/h（含 35 GiB 磁碟 $0.00378/h） | stopped／paused 只收磁碟 `[官方已寫]`；archived（只有 container）全部不收。**單一 sandbox 磁碟上限 10 GiB `[官方已寫]`**，40 GB 要寫信給 support（官方沒寫流程）；10 GiB 時閒置約 $0.00054/h |
| Firecracker 自架（nested `c8i.large`） | $0.11797/h + EBS $0.00526/h | host 停機只剩 EBS；host 常開時閒置仍全額 |
| Kata on EKS | 同上，再加 EKS 控制平面 $73/月 | 同上 |
| AgentCore Runtime（對照） | 上限 $0.2168/h（2 vCPU × $0.0895 + 4 GB × $0.00945，CPU 吃滿時）；只收實際用掉的 CPU | CPU 幾乎不收、記憶體照收（4 GB 時 $0.0378/h）；WP0 實測閒置成本約占 session 費用九成 |

- AgentCore 單價與閒置行為取自 [WP0 回填](WP0-cost-baseline.md#回填)（實測）。
- Code Interpreter 對照（[WP3 回填](WP3-sandbox-egress.md#回填)）：約 1 vCPU / 1 GB 吃滿時每小時約 $0.10；E2B 同規格約 $0.067/h（$0.0504 + $0.0162）。
- 冷啟動基準：WP0 從台灣呼叫，新 session 第一次約 0.85–0.95 秒，但 VM 在呼叫前已開好約 32 秒，不是真正的冷啟動；是否為預先開好的 VM 池由 WP1 確認。

#### 第 5 層：記憶

| 能力 | 自管 Postgres + pgvector | Mem0 雲端／自架 | Zep 雲端／Graphiti 自架 |
|---|---|---|---|
| 短期對話歷史 | 要自己做 | 沒有獨立功能，用 user_id／agent_id／run_id 分範圍 | Zep 有（thread）；Graphiti 要自己做 `[推測]` |
| 長期記憶與語意檢索 | 要自己做（HNSW／IVFFlat） | 有 | 有（graph 檢索） |
| LLM 萃取 | 要自己寫整條 pipeline | 內建，新版單次 LLM 呼叫、**只新增** | 內建；自訂萃取指令要 Flex Plus；Graphiti 每個 episode 觸發多次 LLM 呼叫 |
| 合併去重與衝突 | 要自己做 | 不去重、不覆寫，衝突靠檢索排序 `[推測]` | 有：舊事實標記失效、不刪除 |
| 跨使用者隔離 | `user_id` WHERE（應用層），或 **RLS（資料層強制）**；RLS 要加 `FORCE ROW LEVEL SECURITY`，否則表擁有者會繞過 | 應用層帶 `filters={"user_id": ...}`；Platform 的 API key 綁 project，角色只有 READER／OWNER，沒有 per-user key（官方文件沒寫此功能）。OSS 的 per-user key 綁 dashboard 使用者，不是記憶的 `user_id` | Zep：每位使用者獨立 user graph（服務內結構隔離）；Graphiti：`group_id`，靠應用層 `[推測]` |
| 官方宣稱延遲 | 沒有 | p50 0.88–1.09 秒、每次約 7K token（README，沒說是寫入還是寫入加檢索）；雲端 add 是非同步 | Graphiti「通常次秒級」；Zep 託管「sub-200ms」 |

- 來源：[PostgreSQL RLS](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)、[pgvector](https://github.com/pgvector/pgvector)、[mem0ai/mem0](https://github.com/mem0ai/mem0)、[Mem0 add](https://docs.mem0.ai/core-concepts/memory-operations/add)、[Zep concepts](https://help.getzep.com/concepts)、[getzep/graphiti](https://github.com/getzep/graphiti) `[官方已寫]`
- pgvector 的近似索引是先掃索引再套 WHERE，依使用者過濾後結果可能變少。建議 partition、獨立表，或開 iterative scan `[官方已寫]`。
- `[矛盾]` Mem0 舊論文（arXiv 2504.19413）描述萃取與整併，新版 README 寫只做 ADD。以新版 README 為準。

#### 第 6 層：可觀測與成本分攤

| 能力 | OTel + Tempo 自架／Grafana Cloud | Langfuse 雲端／自架 | Phoenix 自架／Arize AX |
|---|---|---|---|
| trace / span | 有 | 有，OTLP 只收 HTTP，**不收 gRPC** | 有（OpenInference） |
| token 計量與成本換算 | 沒有原生；Tempo 不能單獨當分攤方案 `[推測]` | 有，內建價格表，可自訂 model definition | 有，內建價格表，可自訂 |
| 依 user／session 彙總 | 要自己寫查詢 | UI 有；**Metrics API v2 不能用 userId／sessionId 當 group-by**，要自己 loop 或拉 Observations 彙總 | session 有；per user 沒查到 |
| 非 LLM 成本掛到使用者 | 要自己做 | 要自己做（只有 generation／embedding 計成本） | 要自己做 |
| 資料可查詢延遲 | 未查 | 官方寫 15–30 秒（Langfuse v4 宣稱 real-time，此數字可能過時） | 未查 |

- 來源：[Langfuse token & cost](https://langfuse.com/docs/observability/features/token-and-cost-tracking)、[Langfuse Metrics API](https://langfuse.com/docs/metrics/features/metrics-api)、[Langfuse OTel](https://langfuse.com/integrations/native/opentelemetry)、[Langfuse scaling](https://langfuse.com/self-hosting/configuration/scaling)、[Phoenix cost tracking](https://arize.com/docs/phoenix/tracing/how-to-tracing/cost-tracking) `[官方已寫]`
- Langfuse Cloud 的 JP 區在 AWS ap-northeast-1（東京），Hobby、Core 都能選，定價頁沒有區域加價 `[官方已寫]`。JP 區 Postgres 備份複製到大阪，ClickHouse（trace）與 S3 不跨區複製。來源：[Langfuse data regions](https://langfuse.com/security/data-regions)
- Langfuse 舊版 metrics 端點（可依 user 彙總）在 Cloud 只服務到 2026-11-16 `[官方已寫]`。
- AgentCore 的 `USAGE_LOGS` 只有 `session.id`，沒有使用者 ID（[WP0 回填](WP0-cost-baseline.md#回填)），所以 session→user 對照不論自架或 AgentCore 都要自己維護。
- 自架相對 AgentCore 要自己補的維度：`user.id`（AgentCore 也沒有自動帶，待實測）、`session.id`（用 baggage 帶）、Runtime 資源用量（自架時沒有 `USAGE_LOGS`，要改看 CloudWatch Agent 或 cAdvisor）。
- Langfuse 自架必須有 ClickHouse（沒有替代），共六個元件：Web、Worker、Postgres、Redis、ClickHouse、S3。Docker Compose 版官方定位是「單一 VM，無 HA、無擴展、無備份」`[官方已寫]`。

#### 檢核表（A 半負責的部分）

| # | 檢核點 | 來源等級 | 結果 | 證據 | 對選型的影響 |
|---|---|---|---|---|---|
| 1 | 第 1、5、6 層填完「有 / 沒有 / 要自己做」 | `[官方已寫]` / `[推測]` 逐格標 | 通過（A 半） | 上方三張表 | 等 B 半合成六層表 |
| 2 | 每層至少一個候選有實測數字 | — | 未做 | 見下方「待實測」 | 要碰 AWS 或部署，下一階段做 |
| 3 | 每人每月成本有官網價，標日期；閒置另列 | 成本 | 通過（A 半，估算） | 下方「實際費用」、`evidence/WP6/` | — |
| 4 | 自架要自己維運的元件與估點 | `[推測]` | 通過（A 半） | 下方「維運元件」 | — |
| 5 | 第 1 層：100 人每人一台常駐 VM 的月費 | 成本 | 24h：自架約 $9.0k、託管約 $12.2k；8h：自架約 $3.3k、託管約 $4.2k | 下方算式 | 自架 8h 情境的前提是全體同時段使用、host 能整台停機 |
| 8 | 方案 C 比方案 B 便宜的使用者規模門檻 | 成本 | 未判定 | — | 要等 WP1、WP5 的數字與 B 半 |

#### 實際費用（全部是官網單價加假設用量的估算，本階段沒有花費）

**檢核點 5：第 1 層 100 人月費**

| 候選 | 情境 A：24h 常駐 | 情境 B：每天活躍 8h |
|---|---|---|
| E2B 託管 | 0.1656 × 730 × 100 + 150 = **$12,239**（不含磁碟超額） | 0.1656 × 243.3 × 100 + 150 = **$4,179**（暫停不收運算費，`[官方已寫]`） |
| Daytona | 0.16938 × 730 × 100 = **$12,365**（前提是 40 GB 獲准，預設上限 10 GiB） | 4,121 + 0.00378 × 486.7 × 100 = **$4,305**（停機只收磁碟，`[官方已寫]`） |
| Firecracker 自架 | 0.11797 × 730 × 100 + 3.84 × 100 = **$8,996** | 0.11797 × 243.3 × 100 + 384 = **$3,255** |
| Kata on EKS | 8,996 + 73 = **$9,069** | 3,255 + 73 = **$3,327** |
| AgentCore Runtime（對照，上限） | 0.2168 × 730 × 100 = **$15,826**（CPU 全時吃滿） | 0.2168 × 243.3 × 100 = **$5,275**（只算活躍時段且 CPU 吃滿；未計閒置記憶體） |

不含維運人力、host 行程開銷（約 10–15% `[推測]`）。AgentCore 那列是上限：它只收實際用掉的 CPU，真實月費要用 WP1、WP5 的實際用量重算，不能直接拿來判定檢核點 8。

**第 5 層：100 人月費**（假設 `[推測]`：每人每月 30 session × 10 輪 = 共 3 萬輪，每輪 1 次寫入加 1 次檢索，共 2 萬筆長期記憶、20 GB）

| 候選 | 月費 | 算式 |
|---|---|---|
| AgentCore Memory（對照） | 約 $45 | 6 萬 event × $0.25/千 + 2 萬筆 × $0.75/千 + 3 萬次檢索 × $0.50/千（單價見 [`read-write-cost.md`](../02-memory/read-write-cost.md)） |
| Mem0 雲端 | $249 | 3 萬次檢索超過 Starter 的 5 千次，要 Pro |
| Zep 雲端 | $150–300 | 每則訊息 1–2 credit，6–12 萬 credits，Flex $125 加超量 |
| 自管 pgvector（RDS 東京） | 單 AZ 約 $76.5；Multi-AZ 約 $153 | `db.t4g.medium` $0.101/h × 730 + 20 GB × $0.138；不含萃取 LLM 費。運行中閒置照收；停止時不收實例時數，仍收儲存、備份、public IPv4，連續停滿 7 天自動啟動 `[官方已寫]`（[RDS 停止實例](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_StopInstance.html)） |
| Mem0 自架 | 約 $110（單 AZ）；Multi-AZ 約 $186；compose 內建 Postgres 單機約 $33.5 | server 主機 `t4g.medium` $0.0432/h × 730 + 20 GB gp3 = $33.46（官方沒寫建議規格，`[推測]`）+ RDS 單 AZ $76.49；單機版無 HA、無備份。不含萃取 LLM 費 |
| Graphiti 自架（Neo4j） | 約 $16.7–33.5 | Neo4j 5.26 官方最低 2 vCPU／2 GB／10 GB → `t4g.small` $0.0216/h × 730 + 10 GB gp3 = $16.73；實務 `t4g.medium` $33.46 `[推測]`。Graphiti 是函式庫，跑在應用程式裡；不含 LLM 費 |

**萃取用 LLM 月費**（自建三個候選都要加；AgentCore 內建策略已含在上表）

假設 `[推測]`：每月 3 萬次寫入，每次 6.5K 輸入 + 0.5K 輸出 token；embedding 寫入與檢索各 1 次、每次 200 token（共 12M token）。7K token 取自 Mem0 README 的基準表，那是 managed 平台、top_200 檢索預算下的數字，不是單次寫入 `[矛盾]`，所以下表可能高估，要實測。

| 模型（東京） | 每百萬 token 輸入／輸出 | 月費 |
|---|---|---|
| Claude Haiku 4.5（`jp.` Geo profile） | $1.10／$5.50 | 214.5 + 82.5 + Titan V2 0.35 ≈ **$297**（Global profile 約 $270） |
| Amazon Nova Lite | $0.072／$0.288 | 14.04 + 4.32 + 0.35 ≈ **$18.7** |
| Amazon Nova Micro | $0.042／$0.168 | 8.19 + 2.52 + 0.35 ≈ **$11.1** |
| gpt-5-mini（Mem0 自架預設） | $0.25／$2.00 | 48.75 + 30 + text-embedding-3-small 0.24 ≈ **$79**（推理 token 算進輸出，可能偏低） |

- 東京單價取自 Bedrock Price List 東京檔（2026-09-30）`[官方已寫]`；OpenAI 取自[各模型頁](https://developers.openai.com/api/docs/models/gpt-5-mini) `[官方已寫]`。Titan Text Embeddings V2 東京 $0.029、Cohere Embed 4 $0.12 每百萬 token。
- 東京沒有 In-Region 的 Haiku 4.5、Nova Micro，只能走 cross-region profile；Haiku 4.5 的 Geo 價比 Global 貴 10%。Nova Lite、Titan V2、Cohere Embed 4 東京可直接 on-demand `[官方已寫]`（各模型的 [model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-4-5.html)）。
- `[矛盾]` Nova Micro 的 Price List 有東京 SKU，文件卻寫東京沒有 In-Region。單價以 Price List 為準。
- 汰換風險：Haiku 4.5 的 model card 寫「EOL no sooner than Oct 16, 2026」；gpt-5-mini 在 OpenAI 已標 Deprecated。

**第 6 層：100 人月費**（假設 `[推測]`：每人每天 10 則對話，每則 35 units、135 KB）

| 候選 | 月費 | 算式 |
|---|---|---|
| AgentCore 內建觀測（對照） | 約 $1.55 | span 攝入 4.05 GB × $0.35 + 儲存 4.05 × $0.033（東京 CloudWatch Price List，2026-09-22）；只算 span，不含 `APPLICATION_LOGS`（vended logs 東京 $0.76/GB 起，量要實測） |
| Langfuse Cloud Core | 約 $105 | 105 萬 units：$29 + 90 萬 × $8/10 萬 + 5 萬 × $7/10 萬 |
| Grafana Cloud Traces | $19 | 4.05 GB 低於含的 50 GB；沒有成本換算 |
| Langfuse 自架（拆開部署） | 約 $340 | `t4g.xlarge` + RDS + Valkey + ClickHouse（`r7g.large`）+ EBS + S3；不含 ALB、備份、Multi-AZ |
| Langfuse 自架（單 VM Compose） | 約 $137 | 只適合實驗；撐不撐得住待實測 |
| Phoenix 自架（Postgres） | 約 $113 | `t4g.medium` + RDS `db.t4g.medium` |

觀測後端要 24h 收資料，沒有閒置折扣。

#### 自架要自己維運的元件與估點（`[推測]`，費氏數列）

| 層 | 路線 | 主要元件 | 估點合計 |
|---|---|---|---|
| 1 | 純 Firecracker | VM 排程與生命週期 API（21）、host fleet、映像、網路、記憶體清除、pause/resume、計量 | 約 68 |
| 1 | Kata on EKS | 節點群組與 Karpenter、映像、狀態保存（只有 PVC） | 約 36 |
| 1 | E2B 自架 | 移植到 AWS（13）、host fleet、映像 | 約 50 |
| 5 | 自管 pgvector | 萃取 pipeline（8）、去重與衝突（8）、索引、RLS、對話表 | 約 28 |
| 5 | Mem0 自架 | 去重策略、server 部署、RLS | 約 19 |
| 5 | Graphiti 自架 | 圖資料庫維運（5）、限流 | 約 23 |
| 6 | Langfuse 自架 | 六元件部署（8）、升級、擴展、session→user 合併報表（5）、隱私 | 約 34；改用 Cloud 省約 18–21 |

#### 待實測（下一階段，要碰 AWS 或部署）

1. 第 1 層冷啟動：E2B 託管的首次建立和 resume，從送出請求到能執行第一個指令；Firecracker 或 Kata 擇一補測。
2. 第 5 層一次寫入加檢索延遲：pgvector、Mem0、Zep 三者同訊息、同區域各量一次。
3. 第 6 層：一次 trace 寫入到可查詢的延遲；Bedrock 東京模型 ID 能否比對到 Langfuse 內建價格表；AgentCore span 有沒有自動帶 `user.id`。
4. 文件沒寫、要寫信問或要試的：E2B 暫停期間的儲存費與 Pro 磁碟加購、E2B／Daytona 能否開 40 GB 磁碟、Daytona VM sandbox 的啟動秒數與開放的 tier。

#### 要更正研究庫的段落（實測後再改 `build-vs-buy.md`）

| 檔案:行號 | 原本寫的 | 調研結果 |
|---|---|---|
| `00-overview/build-vs-buy.md:21` | session 強隔離要自己寫一整套排程器，難度高 | 拆三級：買 E2B 託管＝低；Kata on EKS＝中；純 Firecracker＝高。AWS 上要 Intel nested virtualization。Daytona 預設是 container；VM sandbox 雖已不標 beta，但磁碟上限 10 GiB、只能從 VM snapshot 建立 |
| `00-overview/build-vs-buy.md:22` | 短期記憶用 Redis／Postgres，低 | 自建低成立；Mem0 沒有獨立對話歷史，Zep thread 才是對應物 |
| `00-overview/build-vs-buy.md:23` | 合併、去重、衝突、隔離全部要自己設計 | Mem0 只新增不去重；Zep／Graphiti 有失效機制；只有 pgvector 加 RLS 能在資料層強制隔離 |
| `06-observability/README.md:104` | log 大約每 GB $0.50 | $0.50 是美東價；東京標準 Logs 攝入 $0.76/GB。span 的 $0.35/GB 東京相同 |
| `00-overview/build-vs-buy.md:30` | 觀測低–中，標準成熟 | 改成中：trace 與 LLM 成本換算成熟，每位使用者全成本分攤不成熟；Langfuse 自架六元件；只收 HTTP OTLP |

### B 半：第 2、3、4 層

（RomanChen 回填）
