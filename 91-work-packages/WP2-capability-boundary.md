# WP2 能力邊界：Harness 覆寫 + Gateway Policy

> 回答：「使用者只能用買到的技能」做不做得到？靠哪一層強制？新技能上架要碰哪些東西？
>
> 估點：5。優先序：1（風險高、價值高）。前置：WP0。分群：B。

## 目標

用「Todo 技能」當例子，實際部署一套 Skill + Gateway 工具 + Policy，證明：
1. 沒買的技能，模型**看不到**對應的工具（不是看得到但被拒）。
2. 就算 agent 嘗試呼叫沒買的工具，Gateway 層會擋。
3. 「已購買的能力」能從 JWT 的 claim 判斷，不必每次呼叫都查資料庫。

## 前提

| 前提 | 來源等級 | 出處 |
|---|---|---|
| `InvokeHarness` 可以在呼叫時覆寫 `skills`、`allowedTools`、`tools`，不用重新部署 | `[官方已寫]`，研究庫寫成事實但未實證 | [00 Harness vs Runtime](../00-overview/harness-vs-runtime.md#harness-的心智模型建立時給預設值呼叫時可覆寫) |
| Gateway Policy 在 `ENFORCE` 模式下，被 forbid 的工具會從 `tools/list` 消失 | `[官方已寫]` | [08 Policy：tools/list 也會被過濾](../08-policy/README.md#toolslist-也會被過濾) |
| JWT 的 claim 會變成 principal 的 tag（`principal.getTag("role")`） | `[官方已寫]` | [08 Policy](../08-policy/README.md) |
| 陣列型 claim（例如 `purchased_skills: ["todo", "flight"]`）怎麼編碼成 tag，文件沒寫 | `[推測]` | [prompt-to-policy.md](../08-policy/prompt-to-policy.md) |
| Dogwood 的 `count` 可以限制時間窗內的呼叫次數；但 Gateway 會不會代為產生 session ID，文件與範例矛盾 | `[矛盾]` | [temporal-workflows.md](../08-policy/temporal-workflows.md) |
| 有 `UpdateGateway` / `UpdatePolicy` 權限的人能把 policy 切回 `LOG_ONLY` | `[官方已寫]` | [08 Policy](../08-policy/README.md) |
| 定價：Policy 每次授權檢查 $0.000025；Gateway InvokeTool / ListTools 每千次 $0.005 | `[官方已寫]` | [00 總覽定價表](../00-overview/README.md) |

## 步驟

1. **建 Gateway 與兩個工具：** `todo_crud`（Lambda target，讀寫 DynamoDB，表的 partition key 是 user_id）和 `flight_search`（任何回假資料的 Lambda 即可）。Inbound 用 JWT（Cognito 或任何能自訂 claim 的 IdP）。
2. **發兩種 JWT：** 使用者 A 的 claim `purchased_skills: ["todo"]`；使用者 B 的 `purchased_skills: ["todo", "flight"]`。
3. **Policy：** 用 [`08-policy/experiments/prompt-to-policy/policies.cedar`](../08-policy/experiments/prompt-to-policy/policies.cedar) 當起點，寫「只有 claim 裡有 `flight` 的人可以呼叫 `flight_search`」。先 `LOG_ONLY`，再切 `ENFORCE`。
   - 試三種寫法：陣列 claim 直接 `principal.getTag("purchased_skills").contains("flight")`；字串串接 `"todo,flight"` 用 `like`；每個技能一個布林 claim `skill_flight: true`。記錄哪一種能通過 schema 驗證、哪一種實際有效。
4. **Harness：** 建一個 Harness，掛上這個 Gateway。用 A 的身分呼叫 `InvokeHarness` 並覆寫 `allowedTools` 只放 todo，請模型「幫我查機票」，看模型回什麼。再**不覆寫** `allowedTools`、只靠 Policy，重做一次。
5. **Interceptor 備案：** 如果步驟 3 三種寫法都不行，寫一個 REQUEST interceptor（Lambda）依 `sub` 查表後決定放行與否，量測多出的延遲。
6. **Temporal policy：** 加一條「`flight_search` 每小時最多 30 次」，用 B 的身分連打 35 次，看第 31 次是否被擋，以及 Gateway 有沒有要求呼叫端帶 session ID。
7. **一致性：** 用 `UpdatePolicy` 把那條 policy 改成 `LOG_ONLY`，確認它真的失效（驗證研究庫的警告）。記錄 IAM 要怎麼鎖住這兩個 action。
8. **成本：** 呼叫 1,000 次 `tools/call`，隔天用 WP0 腳本拉 Gateway 和 Policy 的費用。

## 檢核點

| # | 檢核點 | 來源等級 | 判定 |
|---|---|---|---|
| 1 | Harness 覆寫 `allowedTools` 後，模型的回應顯示它不知道有 `flight_search` | `[官方已寫]`，未實證 | 是 / 否；貼模型回應 |
| 2 | `ENFORCE` 下，A 的 `tools/list` 沒有 `flight_search`；B 的有 | `[官方已寫]` | 是 / 否 |
| 3 | 陣列型 claim 三種寫法，哪一種能用 | `[推測]` | 記錄每種的結果 |
| 4 | 不覆寫 `allowedTools`、只靠 Policy 時，模型是否會嘗試呼叫並收到拒絕；拒絕訊息長什麼樣 | `[推測]` | 貼回應 |
| 5 | Interceptor 備案多出的延遲 p50（只在 3 失敗時做） | `[官方已寫]` | 毫秒 |
| 6 | Temporal `count` 限制生效；是否需要呼叫端帶 session ID | `[矛盾]` | 是 / 否 |
| 7 | `UpdatePolicy` 切 `LOG_ONLY` 後 policy 失效 | `[官方已寫]` | 是 / 否；附鎖住它的 IAM policy |
| 8 | 1,000 次呼叫的 Gateway + Policy 實際費用 | 成本 | USD，與單價估算比較 |
| 9 | 「新增一個技能」實際要碰的東西清單（Skill 檔、target、policy、claim） | — | 清單 |

## 判定對選型的影響

- 檢核點 1 + 2 都通過 → 雙重鎖成立，方案 B 的能力邊界可行。
- 檢核點 3 全部否定、5 的延遲超過 200 ms → 「已購買能力」改成每次呼叫由後端查表帶入 `allowedTools`，Policy 退為第二層。
- 檢核點 9 的清單就是之後技能上架的 SOP 草稿。

## 交付

- Todo 技能上架的完整設定檔（Cedar、Gateway target 定義、Harness 設定、Skill 檔）放在 `08-policy/experiments/skill-gating/`。
- 本檔案下方的回填區。

## 關聯

- 研究庫：[08 Policy](../08-policy/README.md)、[prompt-to-policy.md](../08-policy/prompt-to-policy.md)、[temporal-workflows.md](../08-policy/temporal-workflows.md)、[03 Gateway](../03-gateway/README.md)、[runtime-front-door.md](../03-gateway/runtime-front-door.md)、[00 Harness vs Runtime](../00-overview/harness-vs-runtime.md)
- 既有腳本：[`08-policy/experiments/prompt-to-policy/`](../08-policy/experiments/prompt-to-policy/)（`policies.cedar`、`schema.cedarschema`、`run.py`，本機 cedarpy 驗證過）

## 回填

（複製 [`_template.md`](_template.md) 的內容到這裡）
