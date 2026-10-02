# ~~WP4 Browser 接手登入~~（已由其他工程師完成）

> **設計變更：** 後來決定 Browser 改由自家 MCP server 呼叫，agent 的 execution role 不再有 Browser 權限（見 [WP2](WP2-capability-boundary.md#設計變更背景)）。如果既有實作是「agent 直接呼叫 Browser」，接手流程的程式要搬到 server 端，並由 server 把 Live View URL 直接推給 App；這部分由 WP2 的 #7、#8 重新驗證。
>
> **狀態：✅ 已由其他工程師完成，不列入本次分工。** 請將其結果依[回填模板](_template.md)整理到本檔最下方的「回填」區，特別是檢核點 #9 的 Browser 費用，WP5 計算每位使用者月費時會用到。

> 回答：「agent 操作到登入頁時停下來，使用者在聊天室裡看到瀏覽器畫面、自己登入、交還給 agent 繼續」這條流程，能不能在 AgentCore Browser 上做出來？手機上可不可用？
>
> 估點：8。優先序：5（風險中、價值中）。前置：WP0。分群：B。

## 目標

做一個最小可運作的 demo（後端 + 一頁前端），走完整個流程，並把研究庫裡標為「文件沒寫」的行為實測出來。

## 前提

| 前提 | 來源等級 | 出處 |
|---|---|---|
| 每個 Browser session 有一個 DCV server；前端用 TypeScript SDK 的 `BrowserLiveView` 嵌入；URL 用 SigV4 預簽，最長 300 秒 | `[官方已寫]` | [browser-reliability-security.md：真人接手](../05-built-in-tools/browser-reliability-security.md#真人接手live-view--take-control) |
| `UpdateBrowserStream` 的 `streamStatus: DISABLED` 暫停自動化、`ENABLED` 恢復；SDK 有 `take_control()` / `release_control()` | `[官方已寫]` | 同上 |
| 接手後 agent 端的 CDP 連線會斷開還是指令被拒，文件沒寫 | `[推測]` | 同上 |
| URL 過期後已建立的 DCV 連線會不會中斷，文件沒寫 | `[推測]` | 同上 |
| AgentCore 不會通知 agent「被接手了」，要自己協調 | `[官方已寫]` | 同上 |
| Profile 只在明確呼叫儲存時寫入；後存的整個覆蓋前面的；每個帳號上限 100 個 | `[官方已寫]` | [browser-reliability-security.md：Profile](../05-built-in-tools/browser-reliability-security.md#登入狀態profile) |
| Profile 的 IAM condition key 只有 `aws:ResourceTag` | `[官方已寫]` | 同上 |
| Profile 能否用自訂 KMS 金鑰加密，未確認 | `[推測]` | 同上 |
| `remoteWidth` / `remoteHeight` 必須和 session 的 viewport 一致 | `[官方已寫]` | 同上 |
| 錄影裡密碼欄位有沒有遮罩，文件沒寫 | `[推測]` | 同上 |
| Web Bot Auth（預覽）會簽署每個請求，讓機器人防護服務辨識；不保證放行 | `[官方已寫]` | [05 內建工具](../05-built-in-tools/README.md) |
| Nova Act 的 `ui_takeover` 回呼要自己實作串流；雲端只能走 AgentCore Browser + DCV | `[推測]` | [Nova Act 03](../nova-act/03-hitl-tools/README.md#ui-takeover-需要遠端瀏覽器) |
| Browser 計費與 Runtime v1 相同；profile 從 2026-04-15 起「依 S3 價格」但沒有數字 | `[官方已寫]` / 無數字 | [05 內建工具](../05-built-in-tools/README.md) |

## 步驟

1. **測試站：** 架一個有帳密登入的簡單網站（或用任何公開的 demo 登入站），不要用真實的電商。
2. **後端（FastAPI）：** 四個端點：開 Browser session、產生 Live View URL、`take_control`、`release_control`。agent 用 browser-use 或 Nova Act（兩個各做一次），指令是「登入後把帳號頁的使用者名稱讀出來」。
3. **前端（一頁）：** 嵌 `BrowserLiveView`，加一個「完成，交還」按鈕。
4. 走流程：agent 到登入頁 → 自己停止送指令 → `take_control` → 推 URL → 使用者登入 → 交還 → `release_control` → agent 重讀頁面繼續。記錄每一步的行為與時間。
5. **接手後 agent 端行為：** 在 DISABLED 期間，從 agent 端送一個 CDP 指令，看是連線斷開、指令被拒，還是照樣執行。
6. **URL 過期：** 開著 Live View 不動，等 300 秒後看連線還在不在；再試 URL 過期後重新產生一個，能不能無縫接回同一個 session。
7. **Profile：** 登入後 `SaveBrowserSessionProfile`；開新 session 載入 profile，確認仍是登入狀態。給 profile 加 tag `user=A`，用另一個只允許 `user=B` 的 role 嘗試讀取，確認被拒。
8. **手機尺寸：** session viewport 設 390×844，前端 `remoteWidth/Height` 也設一致，看畫面；再故意設不一致，記錄現象。
9. **錄影：** 開啟錄影，流程走完後看密碼輸入的畫面有沒有遮罩。
10. **Web Bot Auth：** 開啟後連到一個會回顯 request header 的站（例如自己架的 echo 站，或 Cloudflare 保護的測試站），確認有簽章 header。
11. **成本：** 一次「等使用者 3 分鐘 + 操作 2 分鐘」的 session，隔天拉帳單；profile 存 10 個看有沒有費用出現。

## 檢核點

| # | 檢核點 | 來源等級 | 判定 |
|---|---|---|---|
| 1 | Live View 在前端能看到畫面並操作 | `[官方已寫]` | 是 / 否 |
| 2 | 接手期間 agent 端送 CDP 指令的結果 | `[推測]` | 斷開 / 被拒 / 照常執行 |
| 3 | URL 過期後既有 DCV 連線是否中斷；重新產生 URL 能否接回 | `[推測]` | 是 / 否 |
| 4 | 交還後 agent 重讀頁面能繼續完成任務（browser-use、Nova Act 各一） | `[推測]` | 是 / 否；各自的程式量 |
| 5a | Profile 載入後仍登入 | `[官方已寫]` | 是 / 否 |
| 5b | `aws:ResourceTag` 能擋住另一個 role 讀 profile | `[推測]` | 是 / 否 |
| 6 | 手機 viewport 可用；尺寸不一致的現象 | `[推測]` | 記錄 |
| 7 | Web Bot Auth 的簽章 header 有出現 | `[官方已寫]`（預覽） | 是 / 否 |
| 8 | 錄影中密碼有遮罩 | `[推測]` | 是 / 否 |
| 9 | 5 分鐘 session 實際費用；profile 費用 | 成本 | USD |
| 10 | 整個接手流程的端到端時間（從 agent 停下到使用者看到畫面） | — | 秒 |

## 判定對選型的影響

- 檢核點 1、2、4 都通過 → 方案 B 的接手登入可行。
- 檢核點 2 是「照常執行」→ 接手期間 agent 可能和使用者搶操作，後端必須先讓 agent 停下再 `take_control`（研究庫已建議的順序成為必要）。
- 檢核點 8 否定 → 錄影功能不能開，或要另外處理合規。
- 檢核點 10 超過 10 秒 → 前端要先顯示「準備畫面中」。

## 交付

- Demo 程式放在 `05-built-in-tools/experiments/takeover-demo/`（後端、前端、README 含執行方式）。
- 本檔案下方的回填區。

## 關聯

- 研究庫：[05 內建工具](../05-built-in-tools/README.md)、[browser-reliability-security.md](../05-built-in-tools/browser-reliability-security.md)、[Nova Act 03 HITL](../nova-act/03-hitl-tools/README.md)、[Nova Act 04 Browser 接法](../nova-act/04-agentcore/README.md)、[Nova Act 05 安全](../nova-act/05-security/README.md)
- 既有腳本：[`05-built-in-tools/experiments/url-guard/`](../05-built-in-tools/experiments/url-guard/)（導覽白名單檢查，可以直接套進 demo）

## 回填

（複製 [`_template.md`](_template.md) 的內容到這裡）
