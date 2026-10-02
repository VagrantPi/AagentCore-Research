# WP3 沙箱連外

> 回答：「agent 可以寫程式、跑程式，但不能上網」擋不擋得死？用哪一種網路模式？多出多少建置成本？
>
> 估點：A 半 2、B 半 3。優先序：2（風險高、價值高）。分群：A、B 各半。
>
> - **A 半（Code Interpreter 沙箱）**：檢核點 #1、#2、#4、#7，#6 的沙箱 session 費用。步驟 1、2 的 Sandbox、Public 兩種模式。前置：WP0。不用等 WP2，可以先做。
> - **B 半（VPC 與連線）**：檢核點 #3、#5、#8，#6 的 endpoint／PrivateLink／Network Firewall 月費。步驟 2 的 VPC 模式、步驟 3–5。前置：WP0、WP2 的自家 MCP server 測試執行個體。

## 目標

確認 Code Interpreter 的 Sandbox 模式實際能連到哪裡；如果擋不乾淨，確認「VPC 模式、不開 NAT」這條路能不能啟動。

設計變更後（見 [WP2](WP2-capability-boundary.md#設計變更背景)），agent 的工具改由**自家 MCP server** 提供，所以還要確認：**Runtime 的 VM 不能上網時，仍然連得到自家 MCP server**，而且只連得到它。

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
3. 在 VPC 模式下，從沙箱裡連一次 WP2 的自家 MCP server 測試執行個體，記錄能不能通（Code Interpreter 一般不需要連它，這一步只是對照）。
4. **Runtime 的 VPC 無 NAT：** 建一個 container 型 Runtime 放在同一個 private subnet，確認沒有 ECR endpoint 時啟不啟得來；補上 ECR 的 `api` 和 `dkr` endpoint 後再試。
5. **Runtime VM 連自家 MCP server：** 依自家 server 部署的位置選一種做法，讓同一個不開 NAT 的 Runtime 連得到它：
   - server 在 AWS：用 PrivateLink（VPC endpoint service）或 VPC peering 讓 private subnet 連得到；
   - server 不在 AWS：只能開 NAT，再用 Network Firewall 只放行 server 的網域。
   在 VM 裡確認：自家 server 連得到；任意外部網站連不到。
6. 在三種模式下各執行一段 5 分鐘的程式，用 WP0 的方法估算費用。另外記錄每個 VPC endpoint、PrivateLink 或 Network Firewall 的月費（Pricing 頁，標「官網價」）。

## 檢核點

| # | 檢核點 | 來源等級 | 判定 |
|---|---|---|---|
| 1 | Sandbox：DNS、任意 HTTPS、PyPI、S3、STS、MMDS 各自通不通 | `[推測]` | 六個是 / 否 |
| 2 | Public：同上（對照組） | `[官方已寫]` | 六個是 / 否 |
| 3 | VPC 無 NAT：任意 HTTPS 不通、S3 通 | `[推測]` | 兩個是 / 否 |
| 4 | 沙箱內讀到的憑證：MMDS 可讀？環境變數有沒有？MMDSv2 是否強制？ | `[官方已寫]` / `[矛盾]` | 記錄 |
| 5 | Runtime container 在 VPC 無 NAT 下，沒有 ECR endpoint 能否啟動；加了之後能否啟動 | `[官方已寫]` | 是 / 否 |
| 6 | 5 分鐘沙箱 session 的實際費用；VPC endpoint、PrivateLink 或 Network Firewall 每月費用 | 成本 | USD |
| 7 | Sandbox 模式的 `pip install` 不通時，預先打包套件進 image 的做法可行（只在 1 的 PyPI 不通時做） | `[推測]` | 是 / 否 |
| 8 | Runtime VM 在不能上網的情況下，連得到自家 MCP server、連不到任意外部網站；採用的連線方式 | `[推測]` | 兩個是 / 否；做法 |

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

### A 半：Code Interpreter 沙箱（#1、#2、#4、#7，#6 的沙箱 session 費用）

- 負責人：Kais
- 執行日期：2026-10-02
- 區域：ap-northeast-1
- 資源 tag：`wp=WP3`、`owner=kais`、`project=hyfai`
- 使用的 AWS 帳號：050571774557
- 資源：`wp3_ci_sandbox-eMBYT5nBx9`（SANDBOX）、`wp3_ci_public-DNP69Pgcan`（PUBLIC），execution role `/wp/wp3-ci-exec`（沒有任何權限）
- 腳本：[`sandbox-probe/probe.py`](../05-built-in-tools/experiments/sandbox-probe/probe.py)（加上 MMDSv2、憑證讀取、他人 bucket 檢查）、[`run.py`](../05-built-in-tools/experiments/sandbox-probe/run.py)（新增）

#### 結論（三句內）

1. **Sandbox 擋得住一般外網**（PyPI、任意網站、STS、其他區域的 S3 都不通），「能寫程式但不能上網」在 Code Interpreter 這層成立，不必為了這點改走 VPC。
2. **但 Sandbox 放行同區域的 S3，而且不限 bucket**：沙箱裡的程式可以對東京區任何 bucket 名稱發請求。若攻擊者在東京開一個允許匿名寫入的 bucket，資料就能用不簽章的請求從沙箱送出去（`[推測]`，需要第二個帳號實證）。用 execution role 簽章的跨帳號寫入不行，因為 role 沒有權限；風險在匿名寫入。
3. **兩種模式都讀得到 execution role 的憑證**（MMDSv2 有強制，但 token 沙箱裡就拿得到）。execution role 必須零權限或最小權限；PyPI 不通時，把 wheel 預先送進沙箱用 `pip install --no-index` 可行。

#### 檢核表

| # | 檢核點 | 來源等級 | 結果 | 證據 | 對選型的影響 |
|---|---|---|---|---|---|
| 1 | Sandbox：DNS、任意 HTTPS、PyPI、S3、STS、MMDS | `[推測]` | DNS：只有 `*.amazonaws.com` 解析得到；任意 HTTPS **否**；PyPI **否**；S3：**同區域是、其他區域否**；STS **否**；MMDS **是**（v2） | [`sandbox-probe/README.md`](../05-built-in-tools/experiments/sandbox-probe/README.md#結果2026-10-02東京wp3-a-半) | Sandbox 模式可用；剩下的風險是同區域 S3 當外送管道（見結論 2） |
| 2 | Public：同上（對照組） | `[官方已寫]` | 全部是 | 同上 | 處理使用者資料時不要用 Public |
| 4 | 沙箱內讀到的憑證：MMDS 可讀？環境變數？MMDSv2 強制？ | `[官方已寫]` / `[矛盾]` | MMDS **可讀**（拿 token 後讀得到 AccessKeyId，有效約 1 小時）；環境變數**沒有**；MMDSv2 **有強制**（不帶 token 回 401） | 同上 | execution role 不給權限；有權限的話等於交給模型寫的程式。`[矛盾]` 的部分：憑證只在 MMDS，不在環境變數 |
| 7 | PyPI 不通時，預先打包套件的做法可行 | `[推測]` | 通過 | 本機 `pip download` 出 `tabulate-0.9.0-py3-none-any.whl`，用 `executeCode` 寫進 `/tmp` 後 `pip install --no-index` 成功、import 成功 | Code Interpreter 不能自帶 image；套件要用 `writeFiles` 或從同區域 S3 送進去。沙箱是 **aarch64、Python 3.12**，含 C 擴充的套件要下載 `manylinux_*_aarch64`、`cp312` 的 wheel |
| 6 | 5 分鐘沙箱 session 的費用（A 只做沙箱 session；endpoint 月費由 B） | 成本 | 5 分鐘吃滿單核：Sandbox 0.084718 vCPU-h、0.085473 GB-h → **$0.00839**；Public 0.084760 vCPU-h、0.093542 GB-h → **$0.00847**。約 1 vCPU、1 GB，換算每小時約 $0.10，兩種模式費用相同 | `USAGE_LOGS`（log group `/aws/vendedlogs/bedrock-agentcore/wp3-usage`），`scripts/usage_cost.py` | 網路模式不影響費用；費用幾乎全是 CPU（和 Runtime 閒置時相反）。session 用完要主動 `StopCodeInterpreterSession` |

A 半全部 13 個沙箱 session（含 probe 重跑與 5 分鐘測試）估算合計 **$0.0207**（`usage_cost.py`，05:55 計算）。

其他觀察：

- **Sandbox 下 Python 的 DNS 偶爾失敗**：解析 `s3.ap-northeast-1.amazonaws.com` 一次 `gaierror`，重測三次都成功。在沙箱裡讀寫 S3 的程式要加重試。
- **沙箱裡沒有 `AWS_REGION`**：AWS CLI 預設打全域端點，Sandbox 下會連不上，要明確帶 `--region`。
- **boto3 預設 60 秒讀取逾時不夠**：Sandbox 下連不上的請求要等到逾時，一次 `executeCode` 超過 60 秒時呼叫端會先逾時，但沙箱裡的程式還在跑。
- **Code Interpreter 也有 `USAGE_LOGS`**，而且 delivery 建立前的 session 也補送了（03:55 的 session 在 04:08 建立 delivery 後出現）。
- **log 延遲**：5 分鐘的 session 04:14 結束，04:32 時 log 已記到 304、306 秒；05:55 重算數字不變。依 WP0 的結論，費用仍一律在 session 結束 1 小時後再算。

#### 交給 B 的結論（同步點 1）

- Sandbox **擋得住外網**，B 的 WP3 後半**不必**為 Code Interpreter 改走 VPC 無 NAT；#3、#5 仍要做（Runtime 本身的 VPC 無 NAT 與連自家 MCP server，見 #8）。
- 需要 B 在 WP2 / WP3 一起考慮的風險：**同區域 S3 可以當外送管道**。要擋的話，選項是 VPC 模式加 S3 gateway endpoint 的 endpoint policy（只允許自家 bucket），這只有 VPC 模式做得到。

#### 否定項目的替代方案

| 被否定的檢核點 | 替代方案 | 多出的成本或限制 |
|---|---|---|
| Sandbox 能 `pip install`（PyPI 不通） | 預先打包 wheel，用 `writeFiles` 或從同區域 S3 送進沙箱，`pip install --no-index` | 要維護一份允許的套件清單與 wheel |
| Sandbox 對 S3 只開放自家 bucket（未證實，傾向否定） | VPC 模式 + S3 gateway endpoint 的 endpoint policy 限定 bucket | VPC endpoint 月費；由 B 在 #3 一起量 |

#### 清理確認

- [ ] Code Interpreter 已刪除 — **保留**到 B 半做完 #3 的 VPC 對照，之後一起刪：`wp3_ci_sandbox-eMBYT5nBx9`、`wp3_ci_public-DNP69Pgcan`、role `/wp/wp3-ci-exec`、`USAGE_LOGS` 投遞（delivery source `wp3_ci_sandbox-usage-src`、`wp3_ci_public-usage-src`，destination `wp3-usage-dst`，log group `/aws/vendedlogs/bedrock-agentcore/wp3-usage`）
- [x] Runtime / Harness、Browser、Gateway、Policy、Memory、VPC endpoint：A 半未建立
- [ ] 隔天確認沒有仍在跑的 session（`list-code-interpreter-sessions`）

#### 要更正研究庫的段落

| 檔案:行號 | 原本寫的 | 實測結果 |
|---|---|---|
| `05-built-in-tools/code-interpreter-data-agent.md:107` | SANDBOX：未確認 DNS、`pip install`、S3 以外的 AWS 服務 | DNS 只解析 `*.amazonaws.com`；`pip install` 不通；STS 不通；S3 只限同區域，但不限 bucket |

### B 半：VPC 與連線（#3、#5、#8，#6 的 endpoint 月費）

（RomanChen 回填）
