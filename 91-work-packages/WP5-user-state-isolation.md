# WP5 使用者狀態與隔離、每使用者成本

> 回答：使用者的對話記憶、任務進度、檔案放在 VM 外面之後，A 讀不讀得到 B 的？每位使用者每月實際花多少？
>
> 估點：5。優先序：3（風險高、價值高）。前置：WP0、一個最小的 Runtime（WP1 步驟 1）。分群：A。

## 目標

用兩個使用者（A、B）實際驗證每一層的隔離，並拿到「一位使用者一個月」的帳單。

## 前提

| 前提 | 來源等級 | 出處 |
|---|---|---|
| Memory 用 `actorId` 隔離；IAM 能否依 actorId 限制，文件互相矛盾 | `[矛盾]` | [multi-tenant-isolation.md](../02-memory/multi-tenant-isolation.md) |
| Episodic 策略的 reflection 可能跨使用者彙整；設在 actor 層級可以避免 | `[官方已寫]` 風險 / `[推測]` 做法 | 同上、[02 Memory](../02-memory/README.md) |
| 刪除一位使用者的全部資料要先刪 event 再刪 record | `[推測]` | [multi-tenant-isolation.md](../02-memory/multi-tenant-isolation.md) |
| VM 內任何程式讀得到 execution role 憑證；用範圍縮小的 STS 臨時憑證可以限制 | `[官方已寫]` / `[推測]`（討論中的設計） | [01 Runtime：安全要點](../01-runtime/README.md#安全要點) |
| `USAGE_LOGS` 可以分攤到每個 session | `[官方已寫]`，WP0 會先驗 | [06 Observability](../06-observability/README.md) |
| `AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT` 的名稱和實際行為看起來相反 | `[矛盾]` | 同上 |
| 定價：短期記憶每千個 event $0.25；長期儲存 built-in 每千筆每月 $0.75；檢索每千次 $0.50；`ListEvents` 等讀取操作定價頁沒列 | `[官方已寫]` / 無數字 | [read-write-cost.md](../02-memory/read-write-cost.md) |

## 步驟

1. **Memory：** 建一個 Memory，開 semantic + user preference + episodic 三種策略，episodic 的 reflection 設在 actor 層級。用 A、B 各寫 50 個 event（內容刻意有共通主題，例如都在聊「旅遊」）。
2. 用兩個 IAM role（只允許各自的 actorId；寫法參考研究庫 `multi-tenant-isolation.md` 列出的兩種 condition key，兩種都試）：用 A 的 role 讀 B 的 namespace，看是否被拒。
3. 等萃取完成（約 1–2 分鐘，episodic 更久），讀 reflection，看有沒有混到 B 的內容。
4. **範圍縮小憑證：** 後端用 `AssumeRole` 加 session policy（S3 只允許 `users/A/*`）產生臨時憑證，透過 payload 傳進 Runtime；在 VM 裡用這組憑證讀 `users/B/`，應被拒。再在 VM 裡用 execution role 自己 `AssumeRole`（不帶 session policy）讀 `users/B/`，預期**能讀到**，證明「不能讓 VM 自己 AssumeRole」。記錄要怎麼用 IAM trust policy 擋住後者。
5. **刪除：** 刪掉 A 的全部資料，記錄 API 順序、呼叫次數、耗時，再確認 reflection 裡沒有 A 的殘留。
6. **Observability：** 開 tracing，看 span 裡有沒有對話內容；設 `AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT` 的兩種值各跑一次，記錄實際行為。
7. **成本情境：** 模擬一位使用者一天：100 個 Memory event、20 次檢索、Runtime 在線 2 小時（idle 30 分鐘）、Browser 10 分鐘。跑 3 天，隔天拉帳單，換算成月費。用 `USAGE_LOGS` 算同一位使用者的 Runtime 用量，和帳單比對。

## 檢核點

| # | 檢核點 | 來源等級 | 判定 |
|---|---|---|---|
| 1 | IAM 依 actorId 限制：哪一種 condition key 有效 | `[矛盾]` | 記錄有效的寫法 |
| 2 | Actor 層級的 reflection 沒有混到另一位使用者 | `[推測]` | 是 / 否；貼 reflection 內容 |
| 3 | 範圍縮小的臨時憑證在 VM 裡讀不到 B 的資料 | `[官方已寫]`（AWS 通用） | 是 / 否 |
| 4 | VM 自己 AssumeRole 能繞過；trust policy 能擋 | `[推測]` | 是 / 否；附 trust policy |
| 5 | `USAGE_LOGS` 分攤到使用者的金額，與帳單差多少 | `[官方已寫]` | 百分比 |
| 6 | Span 裡有沒有對話內容；opt-out 變數的實際行為 | `[矛盾]` | 記錄 |
| 7 | 刪除一位使用者資料的步驟與耗時；reflection 無殘留 | `[推測]` | 記錄 |
| 8 | 一位使用者一個月的實際費用（Memory、Runtime、Browser 分開列） | 成本 | USD |
| 9 | `ListEvents` / `GetMemoryRecord` 這類讀取操作有沒有出現在帳單 | 無數字 | 是 / 否 |

## 判定對選型的影響

- 檢核點 1、2、3 任一否定 → 該層的隔離要改由自家後端做（例如 Memory 改成自管），成本和工時要加進方案 B。
- 檢核點 8 直接進決策矩陣，和 WP6、WP7 比較。
- 檢核點 6 決定正式環境 tracing 的設定與個資處理流程。

## 交付

- 兩個 IAM role 的 policy、trust policy 範本放在 `02-memory/experiments/tenant-guard/aws/`。
- 本檔案下方的回填區。

## 關聯

- 研究庫：[02 Memory](../02-memory/README.md)、[multi-tenant-isolation.md](../02-memory/multi-tenant-isolation.md)、[read-write-cost.md](../02-memory/read-write-cost.md)、[06 Observability](../06-observability/README.md)、[04 Identity：多租戶治理](../04-identity/multi-tenant-governance.md)
- 既有腳本：[`02-memory/experiments/tenant-guard/`](../02-memory/experiments/tenant-guard/)（`guard.py` 從 JWT 推導 actorId 與 namespace，假 client 驗證過，改成真 client 即可）、[`02-memory/experiments/cost-model/`](../02-memory/experiments/cost-model/)（月費試算，拿來和實際帳單對照）

## 回填

（複製 [`_template.md`](_template.md) 的內容到這裡）
