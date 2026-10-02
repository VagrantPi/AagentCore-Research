# 技術選型調研工作包

> 把「每位使用者一台對話 agent」的架構決策，切成可以各自領走、用真實 AWS 帳號驗證的工作包。每包附估點與風險排序，供評估時程。目的只有一個：**在正式開工前，把推測變成「已證實 / 已否定」，並拿到實際帳單數字。**
>
> 建立日期：2026-10-01。背景與架構討論見[決策背景](#決策背景)。

## 為什麼要做這件事

研究庫 00–09 的內容建立在官方文件上，但盤點後確認：

- **研究庫裡 14 個實驗，沒有任何一個在 AWS 上真正跑過**（都是本機、假 client 或合成資料）。
- 目標架構倚賴的幾項能力，官方文件**沒寫或前後矛盾**：Code Interpreter Sandbox 能否連外、Policy 能否讀陣列型 claim、瀏覽器接手後 agent 端的行為、Live View URL 過期後連線是否中斷、session storage 怎麼計費、V2 快照是否造成狀態重複。
- 定價只有單價，沒有「我們的使用情境」下的實際用量與費用。

接下來一個月時程滿檔、容錯小，所以每個關鍵假設都要在開工前驗過。

## 設計原則（每包都遵守）

1. **一包只回答 3–10 個是非題**，每題都能用「跑一次、看一個數字或一個 API 回應」判定。不做開放式調研。
2. **每個檢核點標示來源等級：**
   - `[官方已寫]`：官方文件明載，只需跑一次確認版本沒變。
   - `[推測]`：研究庫或討論中的判斷。**必須實跑，沒跑就視為未通過。**
   - `[矛盾]`：官方文件前後不一致。實跑並記錄哪一頁是對的。
3. **成本用「實際用量 × 官網單價」估算。** 公司 Organizations 的 SCP 禁止本帳號使用 Cost Explorer 與 Budgets，拿不到帳單（見 [WP0](WP0-cost-baseline.md#為什麼不用帳單2026-10-02-確認)）。用量一律來自 AgentCore 的 `USAGE_LOGS`、CloudWatch metric 或自己的呼叫計數，不用猜的；回填時寫出用量、單價、算式。每個資源都加 `wp=<編號>`、`owner=<人>`、`project=hyfai` 三個 tag。
4. **失敗也是結果。** 功能不存在或行為不符，回填「否定」並寫替代方案，不要硬做。
5. **每包結束要清資源。** Runtime、Browser、Memory 都有閒置計費或配額。沒有預算警報，清理確認是唯一的兜底。
6. **回填用同一份模板：**[`_template.md`](_template.md)。寫在各 WP 檔案最下方的「回填」區。
7. **沒有 AWS 權限的同事**用受限的實驗身分，設定方式與範本見 [`iam/`](iam/)。

## 估點與排序原則

**估點**用費氏數列（1、2、3、5、8、13），反映的是**複雜度與不確定性**，不是時數。換算成時程由你依團隊的速度自行評估。

| 點數 | 意義 |
|---|---|
| 2 | 照步驟設定即可，幾乎沒有未知 |
| 3 | 有既有腳本可以直接跑，未知集中在一、兩個點 |
| 5 | 要串 2–3 個 AWS 服務，有數個 `[推測]` 或 `[矛盾]` 要實測 |
| 8 | 要自己寫可運作的 demo（前後端），或範圍很廣，未知多 |

**排序**依「風險等級 × 實際價值」：

| 風險等級 | 定義 |
|---|---|
| 高 | 結果是「否定」就推翻目前的架構方向，而且沒有簡單的替代方案 |
| 中 | 結果是「否定」要改設計，但有已知的替代方案 |
| 低 | 結果只影響方案比較或成本估算的精準度 |

| 價值 | 定義 |
|---|---|
| 高 | 直接決定產品核心承諾能不能兌現（只能用買到的技能、資料不外洩） |
| 中 | 決定使用者體驗或某個功能能不能做 |
| 低 | 提供對照數字，幫助選型但不單獨決定方向 |

## 工作包總覽（依優先序排列）

| 優先序 | 編號 | 題目 | 回答的選型問題 | 風險 | 價值 | 估點 | 前置 | 分群 | 負責人 | 狀態 |
|---|---|---|---|---|---|---|---|---|---|---|
| 前置 | [WP0](WP0-cost-baseline.md) | 成本量測基礎 | 之後每包的費用怎麼估算 | — | 前置 | 2 | — | A | Kais | ✅ 完成（2026-10-02） |
| 1 | [WP2](WP2-capability-boundary.md) | 能力邊界：自家 MCP server 依技能授權 | 「只能用買到的技能」能不能由自家 MCP server 強制、agent 繞不過；Browser 包成自家工具可不可行；還要不要 Gateway | 高 | 高 | 8 | WP0、自家 MCP server 測試執行個體 | B | RomanChen | ⬜ |
| 2 | [WP3](WP3-sandbox-egress.md) | 沙箱連外 | 「agent 能寫程式但不能上網」擋不擋得死；不能上網時仍連得到自家 MCP server | 高 | 高 | A 半 2、B 半 3 | A 半：WP0；B 半：WP0、WP2 的自家 MCP server 測試執行個體 | A、B 各半 | Kais、RomanChen | 🟡 A 半完成（2026-10-02），B 半未開始 |
| 3 | [WP5](WP5-user-state-isolation.md) | 使用者狀態與隔離、每使用者成本 | 資料不外洩、每人成本算得出來 | 高 | 高 | 5 | WP0、一個最小的 Runtime（WP1 步驟 1） | A | Kais | ⬜ |
| 4 | [WP1](WP1-runtime-session.md) | Runtime 冷啟動與「一人一實體」 | microVM 撐不撐得住對話體驗？V2 值不值得？ | 中 | 高 | 5 | WP0 | A | Kais | ⬜ |
| ~~5~~ | ~~[WP4](WP4-browser-takeover.md)~~ | ~~Browser 接手登入~~ | ~~Muse 式的接手流程能不能在 AgentCore 做出來~~ | ~~中~~ | ~~中~~ | ~~8~~ | ~~WP0~~ | — | 其他工程師 | ✅ 已由其他工程師完成 |
| 6 | [WP6](WP6-oss-alternatives.md) | 不用 AgentCore 的開源方案 | 自架的真實成本與缺口 | 低 | 中 | A 半 5、B 半 5 | — | A、B 各半 | Kais、RomanChen | ⬜ |
| 7 | [WP7](WP7-openclaw-on-agentcore.md) | OpenClaw on AgentCore 官方範例實跑 | 方案 A 的真實數字，當對照組 | 低 | 低 | 3 | WP0、WP3 的 VPC | B | RomanChen | ⬜ |

- **WP0 不參與排序**：它定義所有 WP 共用的費用估算方法與 tag 規則，所以要最先做。
- **前三名都是「高風險、高價值」**：分別對應產品的兩個核心承諾（只能用買到的技能、資料不外洩）。任何一個被否定，方案 B 就要大改。
- **WP1 排在 WP5 後面**：冷啟動慢或並行會卡，都有已知替代（預喚醒、V2、一個聊天室一個 session）；資料外洩沒有。
- ~~**WP4 是功能層級**：否定的結果是「這個功能改做法或延後」，不影響整體架構。~~ WP4 已由其他工程師完成，不列入本次分工；結果請回填到 [WP4 檔案](WP4-browser-takeover.md)的「回填」區。
- 每位同事都有 AI 輔助，各 WP 都標了既有的腳本和研究庫段落，可以直接餵給 AI 當起點。

## 兩人分工

依架構的兩條主軸分群。每人負責一條主軸的 AWS 實測，再做那條主軸對應的開源方案調研（WP6 拆半）。這樣調研開源方案時，比較的正是自己剛實測過的 AgentCore 元件。

| | A：執行環境、狀態、成本（Kais） | B：能力邊界、使用者互動、OpenClaw 對照（RomanChen） |
|---|---|---|
| 回答的問題 | 資料會不會外洩、「一人一實體」跑不跑得動、每人每月花多少 | 「只能用買到的技能」守不守得住、~~使用者能不能接手登入~~、OpenClaw 的對照數字與能否收緊 |
| 負責的 WP（依優先序） | WP0（前置）→ WP3 前半 → WP5 → WP1 → WP6 前半 | WP2 → WP3 後半 → ~~WP4~~ → WP6 後半 → WP7 |
| WP6 負責的層 | 第 1 層隔離執行環境、第 5 層記憶、第 6 層可觀測與成本 | 第 2 層 agent 框架與技能、第 3 層工具閘道與授權、第 4 層雲端瀏覽器 |
| WP3 負責的檢核點 | Code Interpreter 沙箱：#1 Sandbox、#2 Public、#4 憑證可讀性、#7 預先打包套件、#6 的沙箱 session 費用 | VPC 與連線：#3 VPC 無 NAT、#5 Runtime 在無 NAT 下啟動、#8 連得到自家 MCP server、#6 的 endpoint／PrivateLink／Network Firewall 月費 |
| 主要碰的服務 | Runtime、Memory、Code Interpreter、STS、CloudWatch | 自家 MCP server、Runtime、Harness、Browser（由自家 server 呼叫）、Code Interpreter、VPC、OpenClaw 官方範例；Gateway 與 Policy 只在選配時碰 |
| 估點合計 | 2 + 2 + 5 + 5 + 5 = 19 | 8 + 3 + ~~8~~ + 5 + 3 = 19 |

### 共用資源：只建一次

| 資源 | 誰建 | 誰用 |
|---|---|---|
| tag 規則與費用估算腳本（WP0） | A，最先做 | 兩人 |
| 測試身分：使用者 A、B 的 JWT（Cognito） | B，WP2 第一步 | A 在 WP5 用同一組身分測隔離 |
| 自家 MCP server 的測試執行個體（含 `todo`、包了 Browser 的 `flight` 技能） | B，WP2 步驟 0–2 | B 在 WP3 測連線；A 在 WP5 測使用者 token 被濫用的範圍 |
| 不開 NAT 的 VPC | B，WP3 | A 在 WP1 的 VPC 組沿用；B 在 WP7 的能力邊界測試沿用 |
| 最小的 Runtime：`wp0_min-HsBwOc6VWU`（東京，PUBLIC，image `wp-agentcore-coldstart:small`，execution role `/wp/wp0-runtime-exec`） | A，WP0 已部署 | WP0 驗證 `USAGE_LOGS`；WP5 測 VM 內的憑證；之後 WP1 繼續用 |
| 區域 | 已定：東京（`ap-northeast-1`） | 兩人。公司機器與自家 MCP server 都在東京；亞太區只有東京支援 V2 |

跨群要交接的數字：WP4 的 Browser 每次 session 費用改從其他工程師的結果取得，由 A 放進 WP5 的「每位使用者月費」；A 把 WP1 的冷啟動數字交給 B，當 WP6 比較開源方案、WP7 對照方案 A 的基準。

### 每個 WP 先做的檢核點

每個 WP 內也依風險排序：先做「結果是否定就會推翻架構」的阻斷級檢核點，其餘依序做。

| WP | 阻斷級（先做） | 其餘（依序） |
|---|---|---|
| WP2 | #0 自家 server 的身分驗證現況、#1 `tools/list` 過濾、#2 直接呼叫被拒、#3 身分從 Runtime 帶到 server、#6 VM 開不了 Browser、#7 Browser 包成自家工具 | #4、#8、#5、#9、#12、#10、#11；保留 Gateway 時再做 G1–G6 |
| WP3 | #1 Sandbox 連外（A）、#3 VPC 無 NAT（B）、#8 不能上網仍連得到自家 MCP server（B）、#4 憑證可讀性（A） | #5（B）、#7（A）、#2（A）、#6（各做自己的部分） |
| WP5 | #1 actorId 的 IAM、#3 範圍縮小的臨時憑證、#4 VM 自己 AssumeRole 能否繞過、#10 VM 裡的使用者 token 濫用範圍、#2 reflection 跨使用者 | #11、#8、#7、#6、#5、#9 |
| WP1 | #8 單 session 並行、#1 V1 冷啟動、#7 預喚醒 | #2、#3、#4、#5、#6a、#6b、#11、#9、#10 |
| ~~WP4~~ | ~~#1 Live View、#2 接手期間 agent 端行為、#4 交還後繼續、#5b profile 的 IAM 隔離~~ | ~~#5a、#3、#8、#6、#10、#7、#9~~（已由其他工程師完成） |
| WP6 | 每層「有 / 沒有 / 要自己做」，特別是 #6 框架外強制白名單、#7 接手登入 | #2、#3、#5、#4、#8 |
| WP7 | #5 預設能不能做範圍外的事、#6 VPC 無 NAT 能否運作 | #1、#2、#3、#4 |

成本檢核點（每個 WP 的最後一項）雖然排在後面，但**每個 WP 都要做**，決策矩陣需要它。

### 同步點（依事件，不依日期）

1. **A 完成 WP3 的 #1、WP1 的 #8 時：** 立刻告知 B。
   - Sandbox 擋不住外網 → B 的 WP3 後半必須走 VPC 無 NAT（#3、#5 不能失敗）；A 的 WP1 要補測 VPC 組。
   - 單一 session 並行會卡住 → B 的技能設計要改成「一個聊天室一個 session」。
   - B 完成 WP2 的 #0 時，也要立刻告知：自家 MCP server 若目前沒有依使用者驗證身分，補上驗證會是 WP2 最大的工作量，可能影響 WP3、WP5 何時能用到測試執行個體。
   - B 完成 WP2 的 #4 時：Harness 的 `remote_mcp` 若無法每次帶不同使用者的 token，主 agent 確定只能用 Runtime，A 的 WP1 結論直接適用。
2. **任何阻斷級檢核點出現「否定」時：** 當下通知對方與你，不要等全部做完。
3. **兩人的阻斷級檢核點都完成時：** 一起填[決策矩陣](#決策矩陣全部回填後匯整)的初版。
4. **全部完成後：** 由 A 用 WP0 的腳本統一估算兩人的費用，回填各 WP，WP6 兩半合成一張表。

## 決策矩陣（全部回填後匯整）

每格只填數字或「通過 / 否定」，附 WP 檔連結。

| 面向 | 方案 B：AgentCore Runtime（自寫 agent） | 方案 A：OpenClaw 跑在 AgentCore | 方案 C：自架開源 |
|---|---|---|---|
| 首句延遲（冷 / 暖） | WP1 | WP7 | WP6 |
| 能力邊界能否在 agent 外強制 | WP2 + WP3 | WP7 | WP6 |
| 接手登入 | WP4 | — | WP6 |
| 資料隔離 | WP5 | WP7 | WP6 |
| 每位使用者每月實際成本 | WP0 + WP5 | WP7 | WP6 |
| 要自己維運的元件 | 少 | 中 | WP6 |
| 關鍵否定項（阻斷） | | | |

## 決策背景

討論中形成、待這些 WP 驗證的目標架構：

```
聊天 App（一位使用者有多個聊天室）
  │  user token
  ▼
後端：驗證身分 → 查已購買的能力 → 查或分配 runtime session（對照表）→ 範圍外請求先擋
  │
  ▼
AgentCore Runtime（microVM；每位使用者一個主實體，重任務另開任務實體）
  ├─ 狀態：Memory（對話）／自家 DB（任務進度）／session storage（快取）
  ├─ 工具：自家 MCP server（唯一的技能授權點：過濾 tools/list、檢查 tools/call、限流、計量）
  │    └─ 需要瀏覽器的技能：server 用自己的 AWS 憑證開 Browser（技能專屬的網域白名單）、
  │       server 端的瀏覽子 agent 操作、Live View URL 由 server 直接推給 App
  └─ Code Interpreter（不能上網的沙箱）

execution role 不給 Browser 權限；Gateway + Policy 為選配，需要時才加在自家 MCP server 前面。
```

倚賴的關鍵假設，和對應的 WP：

| 假設 | 來源等級 | 驗證 |
|---|---|---|
| microVM 冷啟動可以用預喚醒藏起來，使用者感受不到 | `[推測]` | WP1 |
| 同一個 session ID 可以讓一位使用者的多個聊天室共用一台 microVM，並行請求不會卡住 `/ping` | `[推測]` | WP1 |
| 自家 MCP server 能依使用者身分過濾 `tools/list`、拒絕未購買工具的呼叫 | `[推測]` | WP2 |
| Runtime 的 agent 能把每位使用者的 token 帶到自家 MCP server；Harness 的 `remote_mcp` 能不能做到未知 | `[推測]` | WP2 |
| Browser 包成自家 MCP server 的工具後，依技能收費、網域白名單、接手登入都能運作；VM 開不了 Browser | `[推測]` | WP2 |
| Harness 呼叫時覆寫 `allowedTools` / `skills` 能限制模型看到的工具 | `[官方已寫]`，未實證 | WP2 |
| （選配）Gateway Policy 能依 JWT 內的「已購買能力」陣列過濾 `tools/list` | `[推測]` | WP2 選配 G3 |
| Code Interpreter 的 Sandbox 模式擋得住任意外網 | `[推測]` | WP3 |
| Runtime 的 VM 不能上網時仍連得到自家 MCP server | `[推測]` | WP3 |
| 使用者 token 進到 VM，被濫用時最多只能做該使用者本來能做的事 | `[推測]` | WP5 |
| Live View + `take_control` 能做出「使用者登入後交還給 agent」 | `[官方已寫]` 機制、`[推測]` 流程 | WP4（已完成）；改由 server 主導後由 WP2 #8 重新驗證 |
| Memory `actorId` 加 IAM 能擋住跨使用者讀取；episodic reflection 不會跨使用者 | `[矛盾]` / `[推測]` | WP5 |
| USAGE_LOGS 可以分攤每位使用者的成本 | `[官方已寫]`；WP0 已實證可依 session 分攤 | WP0、WP5 |

相關研究庫篇章：[01 Runtime](../01-runtime/)、[03 Gateway](../03-gateway/)、[05 內建工具](../05-built-in-tools/)、[08 Policy](../08-policy/)、[02 Memory](../02-memory/)、[06 Observability](../06-observability/)、[00 Harness vs Runtime](../00-overview/harness-vs-runtime.md)、[00 自建 vs 採用](../00-overview/build-vs-buy.md)。
