# Nova Act 總覽

> 用自然語言 + Python 寫「操作網頁」的自動化流程，由 AWS 自家訓練的模型看畫面、點按鈕、填表單。
>
> 資料查核日期：2026-09-30。來源為 [Nova Act 使用者指南](https://docs.aws.amazon.com/nova-act/latest/userguide/what-is-nova-act.html)、[計費頁](https://aws.amazon.com/nova/pricing/)、[aws/nova-act](https://github.com/aws/nova-act) 的 README 與 FAQ。

## TL;DR

- **它是什麼：** 一個專門做**瀏覽器 UI 自動化**的 agent 服務。你寫 `nova.act("搜尋 rubber duck debugging")`，模型就會看著網頁一步一步操作，直到完成或放棄。可以和一般的 Python 程式碼、Playwright 呼叫混著寫。
- **四件套：** 模型（Nova Act 自家訓練，**不能換成別的模型**）、Python SDK（`pip install nova-act`，**只有 Python**）、CLI 與 IDE 擴充（VS Code / Cursor / Kiro）、AWS Console（檢視 workflow run 的逐步紀錄）。另外還有免設定的網頁 [Playground](https://nova.amazon.com/act)。
- **兩種身分、兩套條款：** API key（在 nova.amazon.com 申請，免費試用，**截圖等互動資料會被拿去改進服務**）和 AWS IAM（正式的 AWS 服務，適用 AWS 服務條款）。正式環境要走 IAM。
- **計費：** **每 agent hour $4.75**，按「agent 實際在工作的牆鐘時間」計算。平行跑幾個 agent 就算幾份；Human-in-the-loop 等真人回應的時間不計。部署產生的 AgentCore Runtime、ECR、S3 **另外計費**。
- **只在 us-east-1。** 官方沒有公布其他區域的時程。
- **跟 AgentCore 的關係：** 不是替代，而是疊在上面。Nova Act 管「決定下一步要點哪裡」，AgentCore [Browser](../../05-built-in-tools/) 提供雲端瀏覽器，[Runtime](../../01-runtime/) 負責跑你的 workflow 程式。IDE 擴充的一鍵部署，底層就是 AgentCore Runtime。

## 先對齊幾個名詞

| 名詞 | 白話解釋 |
|------|---------|
| **act** | 呼叫一次 `act()`，就是交代模型一件事，例如「點登入按鈕，然後搜尋某某」。一個 act 內部是一段 agent loop |
| **step** | act 內部的一輪循環：模型**截圖觀察**頁面 → 決定一個動作（點擊、輸入、捲動）→ 執行。預設最多 30 步，硬上限 200 步 |
| **session** | 一個瀏覽器實例（或 API client）。一個 session 裡的 act 依序執行，**同一個 session 只能單執行緒**；要平行就開多個 session |
| **workflow** | 整件自動化工作的定義：幾個 act 加上串接它們的 Python 程式碼 |
| **workflow run** | workflow 的一次執行，有開始、結束時間和結果。概念上像 CI 的一次 pipeline run |
| **HITL**（Human-in-the-loop） | 流程走到需要人核准、或 agent 卡住（例如 CAPTCHA）時，轉給真人處理，處理完再交還 agent |
| **Agent loop** | 「觀察 → 決策 → 行動」反覆執行直到完成的迴圈。後端類比：一個由模型決定下一個狀態的狀態機 |

層級關係（Console 就是依這個層級呈現紀錄）：

```text
Workflow definition（在 AWS 上註冊的名字）
└── Workflow run（一次執行）
      └── Session（一個瀏覽器，可以多個平行）
            └── Act（一次 act() 呼叫，依序執行）
                  └── Step（一次觀察 + 一個動作）
```

## 它怎麼運作（誰跑在哪裡）

這是理解 Nova Act 最重要的一點：**瀏覽器不在 Nova Act 服務裡，而是在你的程式那一端。**

```text
你的 workflow 程式（Python + nova-act SDK）
  │   跑在：本機 / AgentCore Runtime 容器 / 你自己的 ECS、Lambda…
  │
  ├─ 操作瀏覽器（Playwright / CDP）
  │     瀏覽器在：本機 Chromium / 容器內 Chromium / AgentCore Browser（雲端）
  │
  └─ 每一步把截圖等觀察資料送給 Nova Act 服務 ─→ 模型回傳下一個動作
        （資料面 API：InvokeActStep，預設 5 TPS／帳號；單次 payload 上限 5 MB）
        同時把 workflow run / session / act 的紀錄寫進服務，供 Console 檢視
```

> 推論：從配額表列出的 API（`CreateWorkflowRun`、`CreateSession`、`CreateAct`、`InvokeActStep`、`UpdateAct`…）可以看出，Nova Act 服務本身是「**模型推論 + 執行紀錄**」這兩件事，運算與瀏覽器的成本落在你選的執行環境上。這也解釋了為什麼部署會另外產生 AgentCore Runtime、ECR、S3 的費用。

## 介面：從試玩到上線

官方設計的路徑是「Explore → Develop → Deploy → Monitor」：

| 階段 | 介面 | 要點 |
|------|------|------|
| Explore | [Playground](https://nova.amazon.com/act) | 用 Amazon.com 帳號登入，不需要 AWS 帳號。在代管的瀏覽器裡試指令，滿意後**下載成 Python 腳本** |
| Develop | SDK + IDE 擴充 | SDK 可以設中斷點、加 assertion、互動模式逐步試。IDE 擴充有 Builder Mode（即時預覽瀏覽器）、用聊天產生腳本、範本 |
| Deploy | CLI / IDE 擴充的 Deploy 分頁 / CDK 範例 | CLI 會**自動包容器、建 ECR、S3、IAM role，部署到 AgentCore Runtime**。要自訂基礎設施就用 [nova-act-samples](https://github.com/amazon-agi-labs/nova-act-samples) 的 CDK 範例 |
| Monitor | AWS Console | 依 run → session → act → step 往下看，每一步的觀察與動作、artifact（存在 S3） |

SDK 的限制（出自 FAQ 與 README）：Python 3.10 以上；支援 macOS、Ubuntu 22.04+、WSL2、Windows 10+；**不能在 Jupyter / iPython 裡用**；3.0 以前的版本已停止支援（查核時 PyPI 最新為 3.4.187.0，2026-04-30 發布）。

## 模型版本

模型分兩種支援等級：**GA**（正式版，承諾至少支援 1 年）與 **Preview**（嘗鮮版，不能固定版本）。在 workflow 定義裡用 `model_id` 指定：

| model_id | 行為 |
|----------|------|
| `nova-act-latest` | 自動追最新的 GA 版。**永遠不會自動跳到 preview** |
| `nova-act-preview` | 自動追最新的 preview 版（查核時為 v1.1）。如果 SDK 太舊不支援，會退回該 SDK 支援的最新 GA 版並跳警告 |
| `nova-act-v1.0` | 固定在 2025-12-02 發布的 GA 版，至少支援 1 年 |

```python
@workflow(workflow_definition_name="my-flow", model_id="nova-act-v1.0")
def my_flow():
    with NovaAct(starting_page="https://example.com") as nova:
        nova.act("...")
```

> 判斷：正式環境建議固定版本號（例如 `nova-act-v1.0`），跟鎖定相依套件版本的道理一樣。模型換版可能改變「同一句 prompt 會點哪裡」，而 UI 自動化對這種行為變化很敏感。`nova-act-latest` 適合開發環境。

## 適用情境

官方列出四類，FAQ 也提到客戶實際的用途：

- **資料輸入：** 把結構化資料填進沒有 API 的網頁表單（CRM、ERP、各種廠商入口網站）。
- **資料擷取：** 在網站上搜尋、篩選，把欄位抓成結構化資料。適合沒有匯出功能的產業平台。
- **結帳 / 訂位流程：** 從選商品一路做到付款確認。
- **Web QA 測試：** 用自然語言描述使用者旅程來跑端到端測試，取代維護成本高的 selector 腳本。

**不適用：**
- 非瀏覽器的應用程式。FAQ 明說目前只支援瀏覽器，不支援一般的 computer use。
- 瀏覽器本身的彈窗（例如要求位置權限），`act()` 碰不到。
- 輸入密碼：模型有 guardrail，**會拒絕處理密碼欄位**，官方建議改用 Playwright API 直接填。
- 畫面解析度：最佳化範圍是 `864×1296` 到 `1536×2304`，超出範圍準確度可能下降。

## 跟其他瀏覽器自動化方案的比較

> 以下比較是整理後的判斷，不是官方文件的說法。

| 方案 | 誰決定下一步 | 優點 | 代價 |
|------|------------|------|------|
| **Playwright / Selenium 腳本** | 你寫死的 selector 與流程 | 確定性高、便宜、快 | 網站改版就壞，維護成本高 |
| **browser-use 等框架 + 通用 LLM**（Claude、GPT…） | 通用模型 | 可以換模型、生態系大 | 按 token 計費，截圖很吃 token；UI 操作的準確度看模型 |
| **Nova Act** | 專為 UI 操作訓練的 Nova Act 模型 | 官方宣稱在日期選擇器、下拉選單、彈窗這類難點上有 >90% 的內部評測分數；按時間計費，成本好預估；有 Console 與 workflow 紀錄 | 只有 Python、模型不能換、只在 us-east-1 |
| **AgentCore Browser** | （不決定，只提供瀏覽器） | 雲端 microVM 瀏覽器、Live View、錄影、profile | 需要搭配上面任一種「大腦」使用 |

實務上 Nova Act 常見的組合是：**Nova Act（大腦）+ Playwright（處理密碼、下載這類確定性操作）+ AgentCore Browser（雲端瀏覽器）+ AgentCore Runtime（跑 workflow）**。這個組合在 [04](../04-agentcore/) 再深入。

## 計費

| 項目 | 價格 | 說明 |
|------|------|------|
| Nova Act agent hour | **$4.75 / 小時** | agent 在工作的牆鐘時間。平行的 agent 各自計算；HITL 等真人回應的時間**不計** |
| AgentCore Runtime / Browser、ECR、S3 | 依各服務計價 | 部署時自動建立，另外計費（見 [AgentCore 00 計費](../../00-overview/README.md#計費模型)） |
| API key（nova.amazon.com） | 免費 | 僅供試用；互動資料會被收集用於改進服務 |

計費頁沒有列出 token 或 step 的費用。

> 推論：模型推論成本應該已經包含在 agent hour 裡。所以 step 越少、每步越快，費用就越低。拆成小而明確的 act（FAQ 也建議這樣做來加速）同時能省錢。

粗估：一個 5 分鐘的流程一天跑 1,000 次，約 83 agent hours/天，也就是約 $396/天（還沒算 Runtime 與 Browser 的費用）。

## 值得先知道的配額

| 配額 | 預設 | 可調整 |
|------|------|--------|
| `InvokeActStep`（模型推論） | **5 TPS／帳號** | 可 |
| 其他控制面 / 資料面 API | 100 TPS／帳號 | 可 |
| Workflow definition 數量 | 100K／帳號 | 可 |
| 每個 act 最多幾步 | 200 | 否 |
| Act timeout | 24 小時 | 否 |
| Workflow run timeout | 1 週 | 否 |

⚠️ AWS AI Service Card 寫的是「每個任務最多 100 步、瀏覽器 session 最長 30 分鐘」，跟上表不一致，比較見 [05](../05-security/README.md#上限與行為邊界的矛盾)。
| 每個 act 最多幾個工具 | 100（tool spec 上限 350 KB） | 否 |

> 推論：`InvokeActStep` 5 TPS 是平行擴展時最先碰到的上限。假設每一步大約 2–5 秒（這是假設，官方沒有公布），5 TPS 大約能撐 10–25 個同時在跑的 session。要跑一大批 agent 之前，先申請提高這個配額。

## 研究問題

- [x] Nova Act 是什麼、由哪些部分組成
- [x] 名詞與層級（workflow → run → session → act → step）
- [x] 模型版本策略
- [x] 計費、區域、配額
- [x] 跟 Playwright、browser-use、AgentCore Browser 的定位差異

## 參考資料

- [What is Amazon Nova Act?](https://docs.aws.amazon.com/nova-act/latest/userguide/what-is-nova-act.html)、[Model version selection](https://docs.aws.amazon.com/nova-act/latest/userguide/model-version-selection.html)、[Available interfaces](https://docs.aws.amazon.com/nova-act/latest/userguide/interfaces.html)
- [Getting started](https://docs.aws.amazon.com/nova-act/latest/userguide/getting-started.html)、[Quotas](https://docs.aws.amazon.com/nova-act/latest/userguide/load-balancer-limits.html)
- [Amazon Nova 計費](https://aws.amazon.com/nova/pricing/)
- [aws/nova-act README](https://github.com/aws/nova-act)、[FAQ](https://github.com/aws/nova-act/blob/main/FAQ.md)

## 延伸調研方向

目前只研究完 Nova Act 00，範圍以 00 為主：

1. **成本模型試算：** 把 agent hour 計費，加上 AgentCore Runtime / Browser 的費用，套進幾種典型流程（短流程高頻、長流程低頻、含 HITL），做成試算表。再和「通用 LLM + browser-use 按 token 計費」比較損益平衡點。
2. **模型版本治理：** `nova-act-latest` 和固定版本號之間的升版流程怎麼設計，例如用同一組 workflow 在新舊版本各跑一次、比對成功率後再切換。另外查清楚 GA 版「至少支援 1 年」之後的退場通知機制。
3. **Playground → 正式環境的遷移路徑：** API key 與 IAM 兩種驗證方式的差異，包括資料使用條款、功能是否一致、Playground 匯出的腳本要改哪些地方才能部署。
