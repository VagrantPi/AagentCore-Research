# Nova Act SDK

> Python SDK：用 `act()` 交代任務，用 Playwright 補上確定性操作，用 `Workflow` 把執行紀錄接上 AWS。
>
> 資料查核日期：2026-09-30（PyPI `nova-act` 3.4.187.0）。主要來源為 [aws/nova-act README](https://github.com/aws/nova-act) 與 [使用者指南](https://docs.aws.amazon.com/nova-act/latest/userguide/step-2-develop-locally.html)。名詞見 [00](../00-overview/README.md#先對齊幾個名詞)。

## TL;DR

- **最小程式：** `with NovaAct(starting_page=...) as nova: nova.act("...")`。SDK 會開瀏覽器、跑 agent loop、結束後關閉瀏覽器。
- **兩個核心方法：** `act()` 負責「做事」，`act_get(schema=...)` 負責「做事並回傳結構化資料」。要拿資料就一定要傳 schema（可以用 pydantic 產生），否則回傳值裡沒有 response。
- **`nova.page` 就是 Playwright 的 `Page`：** 密碼、下載、對話框、截圖這類確定性操作，直接用 Playwright 處理，不要交給模型。
- **prompt 的原則：** 直接、完整、拆小。官方經驗是 **30 步內能完成的 act 最可靠**；`max_steps` 預設 30。
- **`Workflow` / `@workflow`：** 包住一段程式，SDK 會自動呼叫 `CreateWorkflowRun` / `UpdateWorkflowRun`，把每個 session、act、step 都記錄到 AWS。**要用 IAM 驗證就必須走 Workflow**。
- **平行：** 一個 `NovaAct` 就是一個瀏覽器，只能單執行緒。要平行就開多個實例（官方稱為「瀏覽器版 map-reduce」）。`Workflow` 物件**不能跨 process**（boto3 client 無法 pickle）。
- **登入狀態：** 預設每次都是乾淨的瀏覽器。可以用四種 provider 保存：本機檔案、S3（SSE-KMS 加密）、AgentCore Browser profile、Chromium profile 目錄。

## 開發迴圈

| 模式 | 用法 | 適合 |
|------|------|------|
| Script | `with NovaAct(...) as nova:` | 正式的腳本 |
| Interactive | `nova = NovaAct(...); nova.start(); nova.act(...)` | 在 Python REPL 一句一句試 prompt。`ctrl+x` 中斷目前的 act 並保留瀏覽器；`ctrl+c` 會關掉瀏覽器 |
| Async | `from nova_act.asyncio import NovaAct` + `async with` / `await` | 搭配 asyncio 程式 |

其他開發工具：
- **Act trace：** 每個 act 結束後會產生一份**獨立的 HTML 檔**，記錄每一步的截圖和動作，路徑印在 console。可以用 `logs_directory` 指定存放位置。
- **錄影：** `record_video=True`（需要同時設定 `logs_directory`）。
- **看 headless 瀏覽器：** 設定 `NOVA_ACT_BROWSER_ARGS="--remote-debugging-port=9222"`，再打開 `localhost:9222/json` 的 `devtoolsFrontendUrl`。
- **Time worked：** 每個 act 結束時會印出「扣掉等真人時間」的工作時間。官方聲明這只是估計值，**不能拿來對帳**。
- **IDE 擴充：** Builder Mode（即時預覽瀏覽器）、用聊天產生腳本。

限制：第一次執行要安裝 Playwright 瀏覽器，約需 1–2 分鐘（可以用 `NOVA_ACT_SKIP_PLAYWRIGHT_INSTALL` 關掉自動安裝）；只支援英文 prompt；不能在 Jupyter 裡用。

## 驗證方式

| 方式 | 設定 | 適用條款 | 用途 |
|------|------|---------|------|
| API key | `NOVA_ACT_API_KEY` 環境變數或 `nova_act_api_key=` | nova.amazon.com 條款（**互動資料會被收集**） | 試用 |
| IAM | 設定好 AWS credentials，並用 `Workflow` 包住程式 | AWS 服務條款 | 開發與正式環境 |

IAM 模式下，`Workflow` 預設用 `{"region_name": "us-east-1"}` 建立 boto3 session。要指定 profile 就傳 `boto_session_kwargs={"profile_name": "...", "region_name": "us-east-1"}`。

## act() 與 act_get()

```python
from nova_act import NovaAct
from pydantic import BaseModel

class Flight(BaseModel):
    departure: str
    price: float

with NovaAct(starting_page="https://nova.amazon.com/act/gym/next-dot/search") as nova:
    nova.act("Find flights from Boston to Wolf on Feb 22nd")          # 做事
    result = nova.act_get("Return the cheapest flight",              # 做事 + 取資料
                          schema=Flight.model_json_schema())
    flight = Flight.model_validate(result.parsed_response)
```

- **參數：** `max_steps`（預設 30，服務的硬上限是 200）、`timeout`（整個 act 的秒數；官方建議優先用 `max_steps`，因為每一步的時間會隨服務負載與網站速度浮動）、`observation_delay_ms`（等動畫跑完再截圖）。
- **回傳：** `ActResult.metadata` 有 `session_id`、`act_id`、`num_steps_executed`、開始與結束時間。`act_get` 回傳 `ActGetResult`，多了 `response`、`parsed_response`、`valid_json`、`matches_schema`。
- **布林判斷：** `act_get("Am I logged in?", schema=BOOL_SCHEMA)`，適合當作流程分支的條件。
- **擷取資料要獨立一個 act：** 官方建議不要在同一個 act 裡「先操作再擷取」。

> 白話：`act_get` + schema 的角色，就像呼叫外部 API 時的 response DTO 驗證。模型的輸出不保證正確，所以要用 schema 擋一層；不符合 schema 時會拋出 `ActInvalidModelGenerationError`。

## 怎麼寫 prompt

官方的 [prompt 指南](https://github.com/aws/nova-act#how-to-prompt-act) 可以濃縮成三條：

1. **直接、精簡：** 寫「Navigate to the routes tab」，不要寫「Let's see what routes vta offers」。
2. **講完整：** 條件、偏好、**停在哪裡**都要寫清楚，例如「stop when you get to the payment page」。把它當成交代一個不熟悉這個網站的新同事。
3. **拆小：** 一個大任務拆成幾個 act，中間用 Python 串接，前一個 act 的輸出當作下一個 act 的輸入。如果還是不穩，就再拆得更細。

```python
# 拆成三個 act，前一個的輸出當下一個的輸入
addr = nova.act_get(f"book the first hotel under $100 ... return the address").response
nova.act(f"book a restaurant near {addr} at 12:30pm for two people")
nova.act(f"rent a small car near {addr} between {start} and {end}")
```

小技巧：日期用絕對日期（「march 23 to march 28」）；找不到搜尋按鈕時，在 prompt 加上「type enter to initiate the search」。

> 判斷：「拆小」同時會影響可靠度、速度和成本（見 [00 計費](../00-overview/README.md#計費)）。把確定性的部分（跳轉 URL、填帳密、下載檔案）從 act 移到 Python / Playwright，是最直接的優化方式。

## 模型與程式碼的分工

`nova.page` 是 Playwright 的 `Page` 物件，以下這些事交給程式碼比交給模型更好：

| 需求 | 做法 | 為什麼 |
|------|------|--------|
| 輸入密碼、卡號 | 先 `act("click on the password field")`，再用 `nova.page.keyboard.type(getpass())` | 模型會拒絕處理密碼。⚠️ 但如果之後的 act 截圖時密碼**顯示在畫面上**，還是會被截進去 |
| 換頁 | `nova.go_to_url(url)` | 比 `page.goto` 更能等到頁面真的載入完成（逾時用 `go_to_url_timeout` 設定） |
| 下載 | `with nova.page.expect_download() as d: nova.act("click download")` | 讓模型負責點，由 Playwright 接住檔案 |
| 原生對話框（alert / confirm） | `nova.page.on("dialog", handler)` | Playwright 預設會自動關掉對話框 |
| 上傳 | 用 `SecurityOptions(allowed_file_upload_paths=[...])` 開放路徑，再用 act 上傳 | 預設禁止上傳；路徑要開得越窄越好（見 [05](../05-security/)） |
| 截圖、DOM | `nova.page.screenshot()`、`nova.page.content()` | 用來除錯或存證 |

## 錯誤處理

所有例外都在 `nova_act.types.act_errors`，分四類：

| 類別 | 意思 | 例子 | 怎麼處理 |
|------|------|------|---------|
| `ActAgentError` | 任務沒完成 | `ActAgentFailed`（agent 判斷做不到）、`ActExceededMaxStepsError`、`ActInvalidModelGenerationError` | 改 prompt 或拆小後重試 |
| `ActClientError` | 請求被拒 | `ActGuardrailsError`（被負責任 AI 的 guardrail 擋下）、`ActRateLimitExceededError` | 調整請求或降速後重試 |
| `ActExecutionError` | 本機執行失敗 | `ActActuationError`（操作瀏覽器時出錯）、`ActCanceledError` | 回報 bug |
| `ActServerError` | 服務端錯誤 | `ActInternalServerError`、`ActServiceUnavailableError` | 回報 bug |

**重試的成本陷阱：** `Workflow` 預設在請求逾時的時候重試一次，`read_timeout` 為 60 秒，可以用 `boto_config` 調整。官方提醒：**同一個請求重試，可能真的被執行了兩次，費用也算兩次**。

> 後端類比：act 不是冪等（idempotent）的。一個「送出訂單」的 act 重試，可能下兩次單。有副作用的 act 在重試前，應該先用 `act_get(schema=BOOL_SCHEMA)` 確認目前的狀態。

## Workflow：把執行紀錄接上 AWS

```python
from nova_act import NovaAct, workflow

@workflow(workflow_definition_name="book-flight", model_id="nova-act-v1.0")
def main():
    with NovaAct(starting_page="https://...") as nova:
        nova.act("...")
```

- **兩種寫法：** `with Workflow(...) as wf:` 再把 `workflow=wf` 傳給 `NovaAct`，或是用 `@workflow` decorator。decorator 靠 ContextVar 自動注入 workflow。
- **生命週期：** 進入時呼叫 `CreateWorkflowRun`，結束時呼叫 `UpdateWorkflowRun` 回報狀態。中間所有的 `CreateSession`、`CreateAct`、`InvokeActStep`、`UpdateAct` 都會掛在這個 run 底下，讓 Console 可以依層級呈現。
- **前置條件：** workflow definition 要先建立好（用 `CreateWorkflowDefinition` API、Console 或 CLI）。細節見 [02](../02-deploy-operate/)。
- **多執行緒的陷阱：** ContextVar 不會自動傳到新的執行緒。用 decorator 時要搭配 `copy_context().run`，或用 `get_current_workflow()` 手動傳入。**多 process 目前不支援。**

## 平行執行

```python
from concurrent.futures import ThreadPoolExecutor
from nova_act import NovaAct, get_current_workflow, workflow

def check(url, wf):
    with NovaAct(starting_page=url, workflow=wf, headless=True) as nova:
        return nova.act_get("Return the price", schema=...).parsed_response

@workflow(workflow_definition_name="price-check", model_id="nova-act-v1.0")
def main(urls):
    wf = get_current_workflow()
    with ThreadPoolExecutor(max_workers=5) as ex:
        return list(ex.map(lambda u: check(u, wf), urls))
```

> 推論：真正的上限是 `InvokeActStep` 的 5 TPS 預設配額（見 [00 配額](../00-overview/README.md#值得先知道的配額)），以及本機能同時開幾個 Chromium。收到 `ActRateLimitExceededError` 時要退避（backoff）重試。上面的範例是依照 README 的模式改寫的，還沒有實測。

## 保存登入狀態

預設每個 session 都會複製一份 Chromium user data 目錄，結束時刪除，也就是每次都從乾淨的瀏覽器開始。要保存登入狀態，有四種選擇：

| | 本機檔案 | S3 | AgentCore Browser profile | Chromium profile |
|---|---|---|---|---|
| 設定方式 | `browser_auth=LocalFileSessionProvider(...)` | `browser_auth=S3SessionProvider(...)` | `AgentCoreBrowserSessionProvider` + `cdp_session()` | `user_data_dir=` + `clone_user_data_dir=False` |
| Cookie | ✅ | ✅ | ✅ | ✅ |
| localStorage | 有存，要設定 `restore_local_storage=True` 才會還原 | 同左 | ✅ | ✅ |
| IndexedDB / 快取 | ❌ | ❌ | ❌ | ✅ |
| 可以跨機器 | ❌ | ✅ | ✅ | ❌ |
| 加密 | ❌（檔案權限 0o600） | ✅ SSE-KMS | ✅ 服務代管 | ❌ |

- 官方的看法：大多數的 OAuth / SAML 登入，**只保存 cookie 就夠了**。
- Chromium profile 模式下，平行執行時每個實例**一定要各自複製一份**（`clone_user_data_dir=True`）。
- ⚠️ 在沒有系統 keyring 的 Linux 上，Chromium 密碼管理器存的密碼是**明文**。
- AgentCore Browser profile 的對應說明見 [AgentCore 05](../../05-built-in-tools/)。

> 判斷：部署到雲端（AgentCore Runtime、ECS）時，本機檔案和 Chromium profile 在容器重啟後就會消失，實際上只能選 S3 或 AgentCore Browser profile。

## 其他常用參數

| 參數 | 用途 |
|------|------|
| `headless` | 無頭模式（預設 `False`） |
| `screen_width` / `screen_height` | 畫面尺寸。官方最佳化範圍是 `864×1296` 到 `1536×2304` |
| `user_agent` | 覆寫 UA。官方建議保留 `NovaAct` 字串，讓網站能辨識這是 agent |
| `proxy` | `{"server", "username", "password"}`；**接 CDP 端點時無效**，要在啟動瀏覽器的那一端設定 |
| `cdp_endpoint_url` / `cdp_headers` | 連到遠端瀏覽器，例如 AgentCore Browser |
| `use_default_chrome_browser` | 使用本機已安裝的 Chrome（只支援 macOS，會重新啟動你的 Chrome） |
| `state_guardrail` | 每次觀察後檢查網址，可以擋掉不允許的網域（見 [05](../05-security/)） |
| `stop_hooks=[S3Writer(...)]` | session 結束時把 trace、截圖上傳到自己的 S3 |
| `human_input_callbacks` / `tools` | HITL 與工具（見 [03](../03-hitl-tools/)） |

### 文件中的小矛盾

- README 說最佳化範圍是 `864×1296` 到 `1536×2304`，但同一段的範例是 `screen_width=1920, screen_height=1080`，這個寬度已經超出範圍。另外，範圍寫法（寬 × 高）看起來像直式畫面，和一般桌面瀏覽器的橫式畫面不同。實際應該用什麼尺寸需要實測。
- 使用者指南 AgentCore 整合頁的範例寫的是 `from nova_act_sdk import NovaAct`，但 SDK 實際的套件名稱是 `nova_act`（見 [04](../04-agentcore/)）。

## 研究問題

- [x] SDK 的核心 API（`act`、`act_get`、`page`）
- [x] prompt 寫法與拆解原則
- [x] 錯誤分類與重試
- [x] Workflow 的生命週期與多執行緒注意事項
- [x] 平行執行與登入狀態保存

## 參考資料

- [aws/nova-act README](https://github.com/aws/nova-act)（Quick Start、How to prompt、Workflows、Common Building Blocks、Reference）
- [Step 2: Develop locally](https://docs.aws.amazon.com/nova-act/latest/userguide/step-2-develop-locally.html)、[Prompting best practices](https://docs.aws.amazon.com/nova-act/latest/userguide/prompting-best-practices.html)
- [nova-act-samples](https://github.com/amazon-agi-labs/nova-act-samples)、[nova-act-extension](https://github.com/aws/nova-act-extension)

## 延伸調研方向

範圍在 Nova Act 00–01 之內，以 01 為主：

1. **可靠度工程：** 建一套固定的測試網站（官方的 `nova.amazon.com/act/gym` 就能用），量測「一個大 act」和「拆成多個小 act」的成功率、步數、耗時。另外比較 `max_steps` 與 `observation_delay_ms` 對結果的影響。沒有憑證時先做成可執行的實驗腳本。
2. **有副作用的 act 如何做到安全重試：** 設計「送出前檢查狀態 → 送出 → 送出後確認」的模式。也要搞清楚 `ActServerError` 發生時，如何判斷操作到底有沒有執行（act trace、`session_id` / `act_id`）。
3. **平行執行的容量規劃：** 單機能跑幾個 headless Chromium、`InvokeActStep` 5 TPS 對應到多少同時執行的 session、收到 `ActRateLimitExceededError` 時怎麼退避。可以搭配 00 的計費模型，估算平行度和成本的關係。
