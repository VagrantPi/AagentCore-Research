# WP2 能力邊界：自家 MCP server 依技能授權

> 回答：「使用者只能用買到的技能」能不能由**自家的 MCP server** 強制執行，而且 agent 繞不過？Browser 這類需要 AWS 權限的內建工具，包進自家 MCP server 之後還能不能正常運作（含使用者接手登入）？Gateway 還需不需要？
>
> 估點：8。優先序：1（風險高、價值高）。前置：WP0、自家 MCP server 的測試環境。分群：B。

## 設計變更背景

原本的設計是用 AgentCore Gateway + Policy 擋沒買的技能。後來確認：

- 公司**已經有自家的 MCP server**，技能和「誰買了什麼」的資料都在自家。
- Gateway 呼叫後端時用的是所有 target 共用的身分，自家 server 不能無條件信任來自 Gateway 的請求，**本來就要自己驗證使用者**。再加 Gateway 的 Policy，等於同一件事做兩次。
- MCP server 類型的 target **不支援直接轉傳使用者 token**，只能用 OBO 換發或 interceptor 注入身分（研究庫 [03 Gateway outbound 表](../03-gateway/README.md)）。
- **Browser、Code Interpreter 不經過 Gateway**：agent 是用 execution role 直接呼叫的。execution role 是所有使用者共用的，而且 VM 裡的程式讀得到它的憑證，IAM 沒辦法依使用者擋。

新設計：

```
Agent（Runtime VM；execution role 沒有 Browser 權限）
   │  帶著「這位使用者」的短效 token
   ▼
自家 MCP server（唯一的技能授權點）
   ├─ 驗證使用者 token → 查已購買的技能 → 過濾 tools/list、檢查 tools/call、限流、計量
   ├─ 一般技能（Todo…）：自己的業務邏輯
   └─ 需要瀏覽器的技能：server 用自己的 AWS 憑證開 AgentCore Browser
        （技能專屬的 Browser 資源有網域白名單）→ server 端的瀏覽子 agent 操作
        → 只回傳結構化結果；遇到登入頁時，Live View URL 由 server 直接推給 App
```

Gateway 降為**選配**：只有在需要 AWS connector（例如 Web Search）、聚合很多非自家後端、或要 Cedar 形式驗證與 Guardrails 時才加在前面。選配的檢核點放在本檔最後。

## 前提

| 前提 | 來源等級 | 出處 |
|---|---|---|
| 自家 MCP server 能依使用者身分過濾 `tools/list`、拒絕未購買工具的 `tools/call` | `[推測]`（要看自家 server 的現況，見步驟 0） | — |
| MCP 規格的授權機制是 OAuth：MCP server 當 resource server，驗證每個請求帶的 token | `[官方已寫]`（MCP 規格） | [MCP Authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization) |
| Runtime 裡自己寫的 agent（例如 Strands 的 MCP client）可以在連線時帶入每位使用者不同的 header | `[推測]` | — |
| Harness 的 `remote_mcp` header 可以引用 Identity token vault 的 ARN；**能不能每次呼叫帶入不同使用者的 token，沒有文件** | `[推測]` | [00 Harness vs Runtime](../00-overview/harness-vs-runtime.md) |
| `InvokeHarness` 可以在呼叫時覆寫 `allowedTools` | `[官方已寫]`，未實證 | 同上 |
| Browser 由 agent 用 IAM 直接呼叫，不經過 Gateway；任何有 IAM 憑證的程式都能開 Browser session（不限於 Runtime 內） | `[官方已寫]` / `[推測]`（後半句是依 API 呼叫方式推論） | [05 內建工具](../05-built-in-tools/README.md) |
| Browser 企業政策 MANAGED 的 `URLAllowlist` 無法被 session 覆寫 | `[官方已寫]` | [browser-reliability-security.md](../05-built-in-tools/browser-reliability-security.md) |
| Live View URL 等於瀏覽器的操作權限，最長 300 秒 | `[官方已寫]` / `[推測]` | 同上 |

## 步驟

0. **盤點自家 MCP server 的現況（先做，決定後面的工作量）：**
   - 目前有沒有驗證使用者身分（OAuth / JWT）？如果沒有，在測試環境先補上最小的 JWT 驗證（例如驗 Cognito 發的 token），這會是本 WP 最大的工作項目。
   - 「使用者買了哪些技能」存在哪裡、server 能不能在每次請求時查到。
   - 部署一份**測試用的 server 執行個體**，資源加 tag `wp=WP2`、`owner`、`project=hyfai`，不要直接用正式環境。
1. **兩位測試使用者：** 用 Cognito 發 JWT。使用者 A 只買 `todo`；使用者 B 買了 `todo` 和 `flight`。
2. **在自家 server 實作技能授權：** `tools/list` 只回傳該使用者買的技能所屬的工具；`tools/call` 再檢查一次。用 A、B 的 token 各自呼叫，記錄回應。
3. **繞過測試：** 用 A 的 token 直接呼叫 `flight` 技能的工具（假裝知道工具名稱），應該被拒。
4. **身分從 agent 帶到 server（Runtime）：** 在 Runtime 裡寫一個最小的 agent，後端把使用者的短效 token 放進呼叫內容，agent 連 MCP server 時帶上。分別用 A、B 呼叫，確認 server 收到的是正確的使用者。
5. **身分從 agent 帶到 server（Harness）：** 建一個 Harness，用 `remote_mcp` 接自家 server。試試看能不能在每次 `InvokeHarness` 時帶入不同使用者的 token（覆寫 `tools` 裡的 header，或其他方式）。做不到就記錄下來，這會是「必須用 Runtime」的理由。同時驗證 `allowedTools` 覆寫的效果。
6. **Execution role 沒有 Browser 權限：** Runtime 的 execution role 不給任何 `bedrock-agentcore` Browser 相關權限。在 VM 裡用程式直接呼叫 `StartBrowserSession`，應收到 `AccessDenied`。
7. **把 Browser 包成自家 server 的工具：**
   - 建一個 Browser 資源，企業政策用 MANAGED：`URLBlocklist: ["*"]` 加上測試站的 `URLAllowlist`。
   - 在自家 server 加一個工具（例如 `flight_search_on_web`）：server 用自己的 AWS 憑證開 Browser session，由 server 端的瀏覽子 agent（browser-use 或 Nova Act）操作測試站，只回傳結構化結果。
   - 用 B 呼叫成功；用 A 呼叫被拒。再讓子 agent 嘗試開白名單以外的網址，應被擋。
8. **使用者接手登入改由 server 主導：** 測試站需要登入時，server 端子 agent 先停止 → `take_control` → server 把 Live View URL **直接推給 App**（用一個簡單的推播端點模擬）→ 使用者登入、交還 → `release_control` → 繼續。檢查 agent 的對話內容和 trace 裡**沒有出現 Live View URL**。
   - 這一步可以沿用 [WP4](WP4-browser-takeover.md)（已由其他工程師完成）的程式，只是把呼叫位置從 agent 搬到 server。
9. **限流與計量：** 在自家 server 對 `flight` 技能設「每小時最多 30 次」，用 B 連打 35 次，確認第 31 次被擋，並有計量紀錄。
10. **延遲：** 量測 agent → 自家 server 一般工具的 p50；以及包了 Browser 的工具，從呼叫到拿到結果的端到端時間。
11. **成本：** 呼叫包了 Browser 的工具 20 次，隔天用 WP0 的腳本拉 Browser 費用；另外記錄測試用 server 的基礎設施費用。

## 檢核點

| # | 檢核點 | 來源等級 | 判定 |
|---|---|---|---|
| 0 | 自家 MCP server 目前有沒有依使用者驗證身分；沒有的話補上最小驗證的範圍 | — | 有 / 沒有；補上的內容 |
| 1 | A 的 `tools/list` 沒有 `flight` 的工具；B 的有 | `[推測]` | 是 / 否 |
| 2 | A 直接呼叫 `flight` 的工具被拒 | `[推測]` | 是 / 否；貼錯誤回應 |
| 3 | Runtime 的 agent 能把每位使用者的 token 帶到 server，server 收到的身分正確 | `[推測]` | 是 / 否 |
| 4 | Harness 的 `remote_mcp` 能不能每次呼叫帶不同使用者的 token | `[推測]` | 能 / 不能；不能就記錄為「必須用 Runtime」 |
| 5 | Harness 覆寫 `allowedTools` 後，模型不知道被排除的工具 | `[官方已寫]`，未實證 | 是 / 否；貼模型回應 |
| 6 | VM 裡直接呼叫 `StartBrowserSession` 收到 `AccessDenied` | `[官方已寫]`（IAM 行為） | 是 / 否 |
| 7 | 包成自家工具的 Browser：B 成功、A 被拒、白名單以外的網址被擋 | `[推測]` | 三個是 / 否 |
| 8 | 接手登入由 server 主導可以走完；agent 的對話與 trace 裡沒有 Live View URL | `[推測]` | 是 / 否 |
| 9 | 自家 server 的技能限流與計量生效 | 自家實作 | 是 / 否 |
| 10 | 一般工具呼叫的延遲 p50；包了 Browser 的工具端到端時間 | — | 毫秒 / 秒 |
| 11 | 20 次 Browser 工具呼叫的實際費用；測試 server 的費用 | 成本 | USD |
| 12 | 「新增一個技能」實際要碰的東西清單（Skill 檔、server 的工具與授權設定、Browser 資源） | — | 清單 |

**阻斷級（先做）：** #0、#1、#2、#3、#6、#7。

## 判定對選型的影響

- #1、#2、#3 都通過 → 技能授權放在自家 MCP server 可行，**不需要 Gateway**。
- #4 是「不能」→ 主 agent 必須用 Runtime，不能用 Harness。
- #6、#7 都通過 → Browser 依技能收費可行，VM 碰不到 Browser。
- #7 的白名單沒有擋住 → 改用 VPC + Network Firewall 當硬邊界（研究庫 [browser-reliability-security.md](../05-built-in-tools/browser-reliability-security.md) 的建議）。
- #12 的清單就是之後技能上架的 SOP 草稿。

## 選配：保留 Gateway 時才做

只有在決定把 Gateway 放在自家 MCP server 前面時才做。

| # | 檢核點 | 來源等級 |
|---|---|---|
| G1 | Gateway 以「MCP server」類型的 target 接自家 server，工具清單同步正常；新增工具後要呼叫 `SynchronizeGatewayTargets` 才看得到 | `[官方已寫]` |
| G2 | 使用者身分怎麼帶到自家 server：OBO 換發（IdP 要支援 token exchange）或 REQUEST interceptor 注入，哪一種可行、各多出多少延遲 | `[推測]` |
| G3 | Policy `ENFORCE` 下依 JWT claim 過濾 `tools/list`；陣列型 claim 的三種寫法哪一種能用 | `[官方已寫]` / `[推測]` |
| G4 | Dogwood `count` 限制生效；是否需要呼叫端帶 session ID | `[矛盾]` |
| G5 | `UpdatePolicy` 切 `LOG_ONLY` 後 policy 失效，以及怎麼用 IAM 鎖住 | `[官方已寫]` |
| G6 | 1,000 次呼叫的 Gateway + Policy 實際費用 | 成本 |

Cedar 規則可以先用 [`08-policy/experiments/prompt-to-policy/`](../08-policy/experiments/prompt-to-policy/) 在本機驗證。

## 交付

- 測試用自家 MCP server 的授權實作、Browser 工具的實作、Runtime agent 的範例，放在 `08-policy/experiments/skill-gating/`（若含自家 server 的程式碼不便放進研究庫，只放設定與說明，並註明程式碼位置）。
- 本檔案下方的回填區。

## 關聯

- 研究庫：[03 Gateway](../03-gateway/README.md)（outbound 表、MCP server target）、[05 內建工具](../05-built-in-tools/README.md)、[browser-reliability-security.md](../05-built-in-tools/browser-reliability-security.md)、[00 Harness vs Runtime](../00-overview/harness-vs-runtime.md)、[01 Runtime：安全要點](../01-runtime/README.md#安全要點)、[08 Policy](../08-policy/README.md)
- 相關 WP：[WP3](WP3-sandbox-egress.md)（VM 不能上網時連得到自家 server 嗎）、[WP4](WP4-browser-takeover.md)（接手登入的既有實作）、[WP5](WP5-user-state-isolation.md)（使用者 token 在 VM 裡被濫用的影響範圍）
- 既有腳本：[`05-built-in-tools/experiments/url-guard/`](../05-built-in-tools/experiments/url-guard/)（導覽白名單檢查）

## 回填

（複製 [`_template.md`](_template.md) 的內容到這裡）
