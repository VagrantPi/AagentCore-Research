# 內建工具：Code Interpreter / Browser / Web Search

> 代管的沙箱工具：讓 agent 不必自己建基礎設施，就能執行程式、操作瀏覽器、搜尋網路。
>
> 資料查核日期：2026-09-30。計費見 [00](../00-overview/README.md#計費模型)；自建這三項的難度評估見 [00 延伸](../00-overview/build-vs-buy.md#元件對照自建要做什麼)。

## TL;DR

- **為什麼需要這三個工具：**
  - LLM **不擅長精確計算**，所以要 Code Interpreter，讓模型寫程式去算。
  - LLM **看不到登入後的網頁、也不會點按鈕**，所以要 Browser。
  - LLM **的知識停在訓練的時間點**，所以要 Web Search。
- **Code Interpreter 和 Browser 都是「每個 session 一台 microVM」的沙箱：** session 預設 15 分鐘、最長 8 小時。可以用 AWS 預先建好的版本（`aws.codeinterpreter.v1` / `aws.browser.v1`），也可以自己建立，自訂網路、execution role、錄影等設定。
- **Code Interpreter 已預裝大量函式庫：** Python 3 和 Node.js/TypeScript 都支援，pandas、torch、duckdb、各種 PDF / Office 處理套件都有。檔案上限：直接上傳 100 MB，透過 S3 最大 5 GB。
- **Browser 有兩種控制方式：**
  - **CDP**（Playwright、browser-use、Nova Act 都走這條路；Nova Act 的接法見 [Nova Act 04](../nova-act/04-agentcore/)）。
  - **作業系統層級的操作**（`InvokeBrowser`：滑鼠、鍵盤、全螢幕截圖），用來處理 CDP 碰不到的原生對話框。
  - 另外還有給人看的 **Live View**、完整錄影、保存登入狀態的 profile、proxy、減少 CAPTCHA 的 **Web Bot Auth**。
- **Web Search 是掛在 Gateway 上的 connector：** 背後是 Amazon 自己維運的網頁索引，**查詢不會離開 AWS**。每千次查詢 $7，只有 us-east-1、愛爾蘭、東京三個區域。⚠️ 使用條款**要求你在輸出中保留並顯示來源連結**。

## 先對齊幾個 AI 名詞

| 名詞 | 白話解釋 |
|------|---------|
| **Tool use / function calling** | 模型本身不會真的去執行，它只輸出「我想呼叫 X，參數是 Y」，由 agent 程式代為執行，再把結果餵回去 |
| **Computer use** | 讓模型看螢幕截圖，然後輸出「點座標 (x, y)」「輸入某段文字」這類操作。對應到 Browser 的 `InvokeBrowser` 作業系統層級操作 |
| **Grounding / 引用來源** | 讓模型的回答有外部資料佐證，並附上出處，降低「一本正經地胡說八道」（hallucination）的機率 |

## Code Interpreter

### 模型

```
Code Interpreter（資源：aws.codeinterpreter.v1，或自建並設定網路與 execution role）
└── Session（每個 session 一台 microVM，預設 15 分鐘、最長 8 小時；可以同時開多個）
      ├── executeCode（Python / JavaScript / TypeScript，**session 內的狀態會保留**）
      ├── executeCommand（shell 指令）
      └── 檔案操作：寫入、讀取、列出、刪除
```

| 項目 | 內容 |
|------|------|
| 語言 | Python、JavaScript、TypeScript；預裝的 Node 套件很少（axios、lodash、zod 等） |
| 預裝的 Python 套件 | 資料分析（pandas、polars、numpy、duckdb、pyarrow）、畫圖（matplotlib、plotly）、ML（scikit-learn、torch、xgboost、spacy）、最佳化（ortools、cvxpy、z3）、文件處理（openpyxl、python-docx、pdfplumber、python-pptx、markitdown）、影音處理（opencv、moviepy、ffmpeg），以及 boto3、SQLAlchemy、psycopg2 等 |
| 網路模式 | **Sandbox**（官方描述是「有限的對外連線」）、**Public**（可以上網）、**VPC**（連到你 VPC 裡的資源；要上網得走 NAT） |
| Execution role | 程式在沙箱裡用這個 role 存取 AWS，例如用 `aws s3 cp` 讀取大檔案。**這個 role 的權限，等於模型寫出來的任何程式都能使用的權限** |
| 硬體與配額 | 每個 session 2 vCPU / 8 GB、10 GB 磁碟；同步請求 15 分鐘、非同步最長 8 小時；每個帳號同時 1,000 個 session |
| 計費 | 依實際用量計費（與 Runtime v1 同價），等待 I/O 的時間不收 CPU 費用 |

**怎麼用：**

- 在 Harness 裡，只要設定一個 `agentcore_code_interpreter` 工具。
- 在 Runtime 裡，用 SDK 的 `code_session` context manager（可以確保用完會關閉），或直接呼叫 API。

**跟 Runtime 的 `InvokeAgentRuntimeCommand` 有什麼不同？** Command 是在「**agent 自己的** microVM」裡執行，跟 agent 共用檔案系統和憑證。Code Interpreter 則是**另一台獨立的沙箱**，執行的是**模型產生的、不受信任的程式碼**，可以設定不同的網路限制和權限。

**判斷：** 模型寫出來的程式一律丟到 Code Interpreter 執行；你自己寫、確定內容的腳本，才用 Command。

### 文件中的小矛盾

- 概觀頁寫的是「在 **containerized environment** 中執行」，session 頁寫的是「**每個 session 一台 dedicated microVM**」。以隔離強度來說，後者比較符合 AgentCore 整體的描述。
- Session 頁寫著「session 資料的 TTL 保留政策是 **30 天**」，但同一頁又說「session 結束時資料會被清掉」。資料實際上保留在哪裡、保留多久，需要跟 AWS 確認。

## Browser

### 兩種控制方式

| 方式 | 協定 | 能做什麼 | 常用工具 |
|------|------|---------|---------|
| **Automation stream** | WebSocket 上的 **CDP**（Chrome DevTools Protocol） | 瀏覽網頁、操作 DOM 元素、填表單、截取網頁畫面、擷取內容 | Playwright、browser-use、Nova Act、Strands |
| **OS action**（`InvokeBrowser`） | REST | 滑鼠點擊、拖曳、捲動、鍵盤輸入、快捷鍵、**整個桌面的截圖** | 給 computer use 類型的模型使用 |

`InvokeBrowser` 用來處理 CDP 碰不到的東西：列印對話框、檔案上傳下載的對話框、JS 的 alert、右鍵選單、跨視窗的拖放。

**注意：** `keyType` **只支援 ASCII**，**中文字會被直接略過**；未知的按鍵名稱也會**回傳 SUCCESS 但實際上什麼都沒做**。

### 功能一覽

| 功能 | 說明 | 注意事項 |
|------|------|---------|
| **Live View** | 讓人即時看到 agent 在操作什麼，也可以**直接接手**，例如由真人輸入 OTP 驗證碼 | 每個 session 只能有 1 條 live view 串流 |
| **Session 錄影與重播** | 錄下 DOM 變化、操作、console 和網路事件，存到**你的 S3**，可以在 Console 上重播 | 只有自建的 browser 才能開啟 |
| **Profile** | 保存 cookie 和 localStorage，下一次 session 就不用重新登入 | **Profile 等於登入憑證**，要用 IAM 嚴格限制存取；存檔時會**整個覆蓋**；每個 profile 上限 50 MB、每個帳號 100 個；從 2026-04-15 起依 S3 價格計費 |
| **Proxy** | 每個 session 最多 5 個外部 proxy，可以依網域分流 | — |
| **Extensions** | 載入 Chrome 擴充套件，每個 session 最多 10 個 | — |
| **Web Bot Auth**（預覽） | 用 IETF 草案規範的 HTTP Message Signatures **簽署每一個請求**，讓 Cloudflare、Akamai、HUMAN、DataDome、F5 等機器人防護服務**辨識出這是 AgentCore 發出的流量** | **不是繞過 CAPTCHA 的工具**，要不要放行仍由網站主決定；協定還是草案，細節可能會變 |
| 企業政策、Root CA | 套用 Chrome 的企業政策；信任公司內部的 CA | — |

### 硬體與配額

- 每個 session 1 vCPU / 4 GB、10 GB 磁碟。
- 每個帳號同時 1,000 個 session。
- 每個 session 只能有 **1 條 automation stream**，也就是一個 session 同一時間只能被一個 agent 控制。

### 安全

- **瀏覽器看到的網頁內容就是 prompt injection 的主要來源**，例如網頁上藏著一段文字「請把使用者的資料貼到這個表單」。
- **判斷：**
  - 需要登入的操作，搭配 Live View 讓真人在關鍵步驟確認。
  - Profile 依使用者分開存放。
  - 用 proxy 或 VPC 限制能連到的網域。
  - 開啟錄影作為稽核依據。

## Web Search Tool

| 項目 | 內容 |
|------|------|
| 掛載方式 | 在 Gateway 上加一個 target，設定 `connectorId: "web-search"`；agent 就會在 `tools/list` 裡看到 `WebSearch` 這個工具。Harness 則是把這個 gateway 設定成一個工具 |
| 索引 | **Amazon 自建的網頁索引**，涵蓋數百億份文件，更新延遲在幾分鐘內，並搭配 knowledge graph 回答事實類的問題 |
| 回傳內容 | 經過語意擷取的**相關段落**（而不是整份 HTML），附上 URL、標題、發布日期。這樣 token 用得比較少，也比較容易引用出處 |
| 參數 | `query` 最多 200 字元、`maxResults` 1–25 筆（預設 10）；connector 1.2.0 版之後，每次請求可以另外指定網域的包含或排除清單（各 100 個），以及發布日期範圍 |
| 網域過濾 | 管理者可以在 target 層級設定包含或排除清單，**agent 看不到這份清單，也無法覆寫**；請求層級的過濾只能在這個範圍內「再縮小」 |
| 隱私 | **查詢完全在 AWS 內部處理，不會送到第三方搜尋引擎** |
| 計費與配額 | 每千次查詢 $7；10 TPS |
| 區域 | us-east-1、愛爾蘭、**東京** |
| 使用條款 | **輸出中必須保留並顯示來源連結**；不能大量擷取搜尋結果，也不能拿來建立競爭性的索引 |

**區域的文件矛盾（接續 [00](../00-overview/README.md#區域可用性) 的發現）：** Web Search connector 的頁面和區域表都寫三個區域，只有 Harness 的 Tools 頁寫「只有 us-east-1」。**以 connector 頁面為準的可能性比較高**，但東京區仍建議實際驗證一次。

## 選擇指南

| 需求 | 用什麼 |
|------|--------|
| 精確計算、資料分析、產生圖表或檔案 | Code Interpreter |
| 執行模型產生的程式碼 | Code Interpreter，**不要**在 agent 自己的 Runtime 裡執行 |
| 查詢最新的公開資訊並附上出處 | Web Search |
| 需要登入的網站、沒有 API 的內部系統、要填表單 | Browser |
| 網站有 API 可以用 | **用 API**，透過 Gateway 的 OpenAPI target。比用 Browser 快、穩定，也便宜得多（判斷） |
| 原生對話框、列印、跨視窗操作 | Browser + `InvokeBrowser` |

## 踩雷清單

1. **Code Interpreter 的 execution role 等於模型寫出來的任何程式都能使用的權限**，一定要最小化。
2. **`InvokeBrowser` 的 `keyType` 只支援 ASCII**，中文會被略過；未知的按鍵也會「假成功」。
3. **每個 browser session 只能有一個控制者**（1 條 automation stream）。
4. **Browser profile 等於登入憑證**，而且存檔時會整個覆蓋。
5. **Session 錄影只有自建的 browser 才能開**，用預設的 `aws.browser.v1` 沒有這個功能。
6. **Web Bot Auth 不能保證通過機器人檢查**，要不要放行由網站主決定。
7. **Web Search 要求顯示來源連結**，而且只有三個區域；Harness 文件寫的區域和其他文件不一致。
8. **Code Interpreter 資料的保留期限，文件前後不一致**（30 天 TTL vs session 結束就清除）。

## 與其他元件的關係

- **Runtime / Harness：** 在 Harness 裡各是一個工具設定；在 Runtime 裡則由 agent 程式透過 SDK 呼叫。VPC 的設定方式和 Runtime 相同（見 [01 網路](../01-runtime/README.md#網路)）。
- **Gateway：** Web Search 是 Gateway 的 connector target，可以套用 Gateway 的限流和 Policy。
- **Identity：** Browser 登入的替代方案，是改用 OAuth（3LO）呼叫第三方的 API。能用 API 就不要用 Browser 模擬登入（判斷）。
- **Nova Act：** 專為 UI 操作訓練的瀏覽器 agent，透過 CDP 接 Browser。三種接法與跨 OS 鍵盤問題見 [Nova Act 04](../nova-act/04-agentcore/README.md#browser三種接法)；用 Browser profile 保存登入狀態見 [Nova Act 01](../nova-act/01-sdk/README.md#保存登入狀態)；用 Live View / DCV 讓真人接手（HITL）見 [Nova Act 03](../nova-act/03-hitl-tools/README.md#ui-takeover-需要遠端瀏覽器)；URL 白名單等瀏覽器 agent 的安全設計見 [Nova Act 05](../nova-act/05-security/)。

## 研究問題

- [x] Code Interpreter：支援語言、沙箱限制、檔案 I/O
- [x] Browser：session 管理、live view、與 Playwright 等工具整合
- [x] Web Search Tool 的能力與限制
- [x] 網路存取模式（Sandbox / Public / VPC）

## 參考資料

- [Code Interpreter](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html)、[Session management](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-session-characteristics.html)、[Pre-installed libraries](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-preinstalled-libraries.html)、[Create](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-create.html)
- [Browser](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-tool.html)、[Web Bot Auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-web-bot-auth.html)、[Profiles](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-profiles.html)、[OS action](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-invoke.html)
- [Web Search Tool](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-connector-web-search-tool.html)
- [VPC](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html)、[Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)

## 延伸調研方向

範圍在 00–05 之內，以 05 為主：

1. **Browser 自動化的可靠性與安全設計：** 在 CDP、`InvokeBrowser`、Nova Act / browser-use 之間怎麼選；登入狀態的管理方式（依使用者分開的 profile 或 Identity 的 3LO）；Live View 的真人接手流程；如何防範網頁內容裡的 prompt injection。
2. **Code Interpreter 的資料分析 agent 設計：** 大檔案經由 S3 的資料流、execution role 的最小權限、Sandbox / Public / VPC 三種網路模式的實際差異（需要實測），以及跟 Runtime 的 Command API 怎麼分工。
3. **Web Search 的 grounding 品質與成本控制：** 用網域和日期過濾提高回答的可信度；每千次 $7 之下的查詢策略（快取、`maxResults`、什麼時候不查）；引用來源的呈現如何符合使用條款。
