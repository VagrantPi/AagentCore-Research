# WP3 沙箱連外

> 回答：「agent 可以寫程式、跑程式，但不能上網」擋不擋得死？用哪一種網路模式？多出多少建置成本？
>
> 估點：3。優先序：2（風險高、價值高）。前置：WP0、WP2 建好的 Gateway。分群：B。

## 目標

確認 Code Interpreter 的 Sandbox 模式實際能連到哪裡；如果擋不乾淨，確認「VPC 模式、不開 NAT、只放 Gateway 的 endpoint」這條路能不能啟動、能不能呼叫 Gateway 工具。

## 前提

| 前提 | 來源等級 | 出處 |
|---|---|---|
| Sandbox 模式是「有限的對外連線」，明確可以存取 S3；DNS、PyPI、其他 AWS 服務能不能連，文件沒寫 | `[推測]` | [code-interpreter-data-agent.md：網路模式](../05-built-in-tools/code-interpreter-data-agent.md#網路模式) |
| 沙箱裡的程式讀得到 execution role 的憑證（MMDS），與網路模式無關 | `[官方已寫]` | 同上 |
| 憑證是否也在環境變數、MMDSv2 有沒有強制，文件沒寫 | `[矛盾]` | 同上 |
| Runtime VPC 模式要走 NAT 才能上網；放 public subnet 也連不到網際網路 | `[官方已寫]` | [01 Runtime：網路](../01-runtime/README.md#網路) |
| Container 型 agent 會定期從 ECR 重新拉 image，建議加 ECR、S3 gateway endpoint | `[官方已寫]` | 同上 |
| Code Interpreter 計費與 Runtime v1 相同 | `[官方已寫]` | [05 內建工具](../05-built-in-tools/README.md) |

## 步驟

1. 用既有的 [`05-built-in-tools/experiments/sandbox-probe/probe.py`](../05-built-in-tools/experiments/sandbox-probe/probe.py)（**只在 macOS 確認能執行，從未在 Code Interpreter 裡跑**）。它會測 DNS、HTTPS（PyPI、S3、STS）、MMDS、`sts get-caller-identity`、`pip download`。
2. 建三個 Code Interpreter：Sandbox、Public、VPC（private subnet，**不開 NAT**，只放 S3 gateway endpoint 和 `bedrock-agentcore` 的 interface endpoint）。各跑一次 `probe.py`。
3. 在 VPC 模式下，從沙箱裡呼叫一個 Gateway 工具（可以借用 WP2 的 Gateway，或自己建一個最小的），確認走 endpoint 能通。
4. **Runtime 的 VPC 無 NAT：** 建一個 container 型 Runtime 放在同一個 private subnet，確認沒有 ECR endpoint 時啟不啟得來；補上 ECR 的 `api` 和 `dkr` endpoint 後再試。
5. 在三種模式下各執行一段 5 分鐘的程式，隔天拉帳單。另外記錄每個 VPC endpoint 的月費（Pricing 頁，標「官網價」）。

## 檢核點

| # | 檢核點 | 來源等級 | 判定 |
|---|---|---|---|
| 1 | Sandbox：DNS、任意 HTTPS、PyPI、S3、STS、MMDS 各自通不通 | `[推測]` | 六個是 / 否 |
| 2 | Public：同上（對照組） | `[官方已寫]` | 六個是 / 否 |
| 3 | VPC 無 NAT：任意 HTTPS 不通、S3 通、Gateway 工具通 | `[推測]` | 三個是 / 否 |
| 4 | 沙箱內讀到的憑證：MMDS 可讀？環境變數有沒有？MMDSv2 是否強制？ | `[官方已寫]` / `[矛盾]` | 記錄 |
| 5 | Runtime container 在 VPC 無 NAT 下，沒有 ECR endpoint 能否啟動；加了之後能否啟動 | `[官方已寫]` | 是 / 否 |
| 6 | 5 分鐘沙箱 session 的實際費用；VPC endpoint 每月費用 | 成本 | USD |
| 7 | Sandbox 模式的 `pip install` 不通時，預先打包套件進 image 的做法可行（只在 1 的 PyPI 不通時做） | `[推測]` | 是 / 否 |

## 判定對選型的影響

- 檢核點 1 的「任意 HTTPS」是**否** → Sandbox 模式夠用，沙箱連外的問題解決，建置成本最低。
- 檢核點 1 的「任意 HTTPS」是**是** → 必須走 VPC 無 NAT；檢核點 3 和 5 要通過，並把 endpoint 月費加進方案 B 的成本。
- 檢核點 4 證實憑證可讀 → execution role 必須最小權限（WP5 會接著驗證範圍縮小憑證）。

## 交付

- 三種模式的 `probe.py` 輸出，回填到 [`sandbox-probe/README.md`](../05-built-in-tools/experiments/sandbox-probe/README.md)。
- 本檔案下方的回填區。

## 關聯

- 研究庫：[05 內建工具](../05-built-in-tools/README.md)、[code-interpreter-data-agent.md](../05-built-in-tools/code-interpreter-data-agent.md)、[01 Runtime：網路](../01-runtime/README.md#網路)
- 既有腳本：[`05-built-in-tools/experiments/sandbox-probe/`](../05-built-in-tools/experiments/sandbox-probe/)

## 回填

（複製 [`_template.md`](_template.md) 的內容到這裡）
