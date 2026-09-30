# Nova Act × AgentCore

> Nova Act 負責「看畫面、決定下一步」，AgentCore 提供跑程式的地方（Runtime）、雲端瀏覽器（Browser）、身分（Identity）、觀測（Observability）、工具入口（Gateway）。
>
> 資料查核日期：2026-09-30。來源為使用者指南 [Bedrock AgentCore 整合](https://docs.aws.amazon.com/nova-act/latest/userguide/bedrock-agentcore.html)、[aws/nova-act README](https://github.com/aws/nova-act)、[nova-act-samples](https://github.com/amazon-agi-labs/nova-act-samples)（`cdk/agentcore`、`examples/agentcore`）。AgentCore 各元件的細節請看本 repo 的 [00–09](../../README.md)。

## TL;DR

- **官方整合了五個元件：**
  - **Runtime**：跑 workflow 程式。CLI 和 IDE 的預設部署目標就是它。
  - **Browser**：透過 CDP 提供雲端瀏覽器，附 Live View 和 profile。
  - **Identity**：`@requires_access_token` 取得第三方 OAuth token。
  - **Observability**：ADOT + OTel baggage，把 Nova Act 的 session ID 串進 trace。
  - **Gateway**：workflow 可以呼叫 Gateway 上的工具，也可以把 workflow 本身掛上 Gateway 給其他 agent 用。
  Memory、Policy、Evaluations、Payments **沒有官方整合說明**。
- **接 AgentCore Browser 有三種寫法：** `bedrock_agentcore` 的 `browser_session()`、Nova Act SDK 內建的 `AgentCoreBrowserSessionProvider`（同時保存登入狀態）、自訂 actuator（把開關 session 包進 `start()` / `stop()`）。
- **區域：** Nova Act 服務只在 us-east-1。Runtime 和 Browser 可以放在其他區域，但每一步的模型推論都要跨區呼叫 us-east-1。
- **成本結構：** Nova Act 的 agent hour（$4.75/h）**遠高於** Runtime + Browser 的運算費用。推估一個 5 分鐘的流程，AgentCore 的部分只占幾個百分點。
- ⚠️ **官方範例有幾個地方不能直接照抄：**
  - Identity 範例把 OAuth token **直接寫進 act prompt**，違反官方自己「不要把敏感資訊交給模型」的建議。
  - CDK handler 把 **CDP 連線的認證 header 寫進 log**。
  - 範例 import 的套件名稱（`nova_act_sdk`）是錯的。

## 整合地圖

```text
呼叫者（API / 排程 / 其他 agent 透過 Gateway）
   │ InvokeAgentRuntime（Identity 驗證 inbound JWT）
   ▼
AgentCore Runtime（你的 workflow 容器，ARM64）
   │  ├─ Identity：@requires_access_token → 第三方 OAuth token
   │  ├─ Observability：ADOT → CloudWatch（baggage 帶 Nova Act session.id）
   │  ├─ Gateway：呼叫 MCP 工具
   │  │
   │  ├─ CDP（WebSocket + SigV4 header）──▶ AgentCore Browser（microVM 瀏覽器、Live View、profile、錄影）
   │  │                                           ▲
   │  │                                           └─ 真人：Console Live View / HIS 的 DCV 串流（見 03）
   │  │
   │  └─ HTTPS ──▶ Nova Act 服務（us-east-1）：InvokeActStep（截圖 → 下一個動作）、workflow run 紀錄
```

| AgentCore 元件 | Nova Act 怎麼用 | 本 repo 對應篇章 |
|---------------|----------------|-----------------|
| Runtime | 部署 workflow；CLI 和 IDE 預設的部署目標 | [01](../../01-runtime/)、Nova Act [02](../02-deploy-operate/) |
| Browser | 雲端瀏覽器（CDP）、Live View、profile 保存登入狀態 | [05](../../05-built-in-tools/) |
| Identity | 取得第三方 OAuth token，代替使用者執行 | [04](../../04-identity/) |
| Observability | ADOT 自動埋點 + baggage 傳 session ID | [06](../../06-observability/) |
| Gateway | 當 client 呼叫工具；把 workflow 本身掛成工具 | [03](../../03-gateway/) |
| Memory / Policy / Evaluations / Payments | 官方沒有整合說明 | — |

## Runtime：跑 workflow

兩種部署方式（細節見 [02](../02-deploy-operate/)）：

1. **CLI / IDE 擴充：** `act workflow deploy`，入口是 `main(payload)`。CLI 會自己加上 AgentCore 的 handler。
2. **自己寫 handler（CDK 範例 `cdk/agentcore/handler.py`）：**

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.tools.browser_client import browser_session
from nova_act import NovaAct

app = BedrockAgentCoreApp()

@app.entrypoint
def handler(payload):
    with browser_session(region) as client:            # 開一個 AgentCore Browser session
        ws_url, headers = client.generate_ws_headers() # CDP 端點與 SigV4 header
        with NovaAct(starting_page=payload["starting_page"],
                     cdp_endpoint_url=ws_url, cdp_headers=headers,
                     headless=True, clone_user_data_dir=False) as nova:
            return {"status": "success", "response": str(nova.act(payload["prompt"]))}
```

- 容器是 ARM64（Runtime 的 microVM 模式只支援 ARM64，Instances 模式才支援 x86_64，見 [AgentCore 01](../../01-runtime/)）。
- 流程時長受 Runtime 限制：microVM 最長 8 小時、Instances 最長 14 天。

> 判斷：瀏覽器放在 AgentCore Browser，而不是跟 workflow 一起塞在 Runtime 容器裡，好處有三個：
> 1. 容器映像檔不用裝 Chromium，比較小。
> 2. 可以用 Live View 或 DCV 讓真人接手（見 [03](../03-hitl-tools/README.md#ui-takeover-需要遠端瀏覽器)）。
> 3. 瀏覽器在隔離的 microVM 裡，被惡意網頁攻破時影響範圍比較小。
>
> 代價是多了一段網路延遲，而且要處理跨作業系統的鍵盤問題（見下方）。

## Browser：三種接法

| 寫法 | 來源 | 適合 |
|------|------|------|
| `browser_session(region)` + `generate_ws_headers()` | `bedrock_agentcore` SDK | 最簡單，CDK 範例用的就是這個 |
| `AgentCoreBrowserSessionProvider(profile=...)` + `provider.cdp_session()`，再傳 `browser_auth=provider` | Nova Act SDK 內建 | 需要**跨 run 保存登入狀態**（cookie、localStorage 存在 AgentCore Browser profile） |
| 自訂 `AgentCoreBrowserActuator`（繼承 `DefaultNovaLocalBrowserActuator`） | `examples/agentcore/browser_actuator` | 想把開關 session 的邏輯藏起來，workflow 程式碼完全不用改；還提供 `console_live_view_url` |

```python
from nova_act import AgentCoreBrowserSessionProvider, NovaAct

provider = AgentCoreBrowserSessionProvider(profile="crm-bot", region="us-east-1")
with provider.cdp_session() as (ws_url, headers):
    with NovaAct(starting_page="https://crm.example.com",
                 cdp_endpoint_url=ws_url, cdp_headers=headers,
                 browser_auth=provider) as nova:
        nova.act("Open today's unresolved tickets")
```

**要注意的地方：**
- **跨作業系統的鍵盤問題：** SDK 在 macOS、AgentCore Browser 在 Linux 時，像 `ControlOrMeta+A`（全選）這類快捷鍵可能對應錯誤，影響 `agent_type()` 等功能。README 說這是「跨 OS 架構的預期行為」。把 SDK 也部署到 Linux（Runtime）就不會有這個問題。
- **proxy 參數無效：** 接 CDP 端點時，`NovaAct(proxy=...)` 不會生效，要改用 AgentCore Browser 自己的 proxy 設定（見 [AgentCore 05](../../05-built-in-tools/)）。
- **一個 Browser session 只能有一條 automation stream：** 一個 `NovaAct` 對應一個 Browser session，平行執行時每個 session 各開一個（帳號上限是同時 1,000 個）。
- **Profile 就是登入憑證：** 用 IAM 限制誰能讀寫 profile。存檔時會整個覆蓋，所以平行的 session 不要共用同一個 profile 寫回（見 [AgentCore 05](../../05-built-in-tools/)）。

## Identity：取得第三方 token

官方範例：先建立 OAuth2 credential provider，再用 `@requires_access_token` 在 Runtime 裡拿到 token：

```python
from bedrock_agentcore.identity.auth import requires_access_token

@requires_access_token(provider_name="custom-oauth-provider")
def automate_customer_outreach(*, access_token: str):
    ...
```

⚠️ **官方範例的問題：** 接下來它執行的是 `browser.act(f"Use OAuth token {access_token} to: 1. Log into the site ...")`，**把 token 直接寫進 prompt**。這表示：
- token 會送到 Nova Act 服務，出現在 agent trajectory 裡，如果有設定 S3 匯出也會被寫進去；
- 違反同一份使用者指南 [Data protection](https://docs.aws.amazon.com/nova-act/latest/userguide/data-protection.html) 的建議：「不要在 act() 裡放敏感資訊」；
- FAQ 也說模型有 guardrail，不處理密碼類輸入，所以這個範例能不能跑成功本身就有疑問。

> 判斷：拿到 token 之後，應該在**程式碼層**使用，不要交給模型。
> - 用 Playwright 設定 header（`nova.page.context.set_extra_http_headers(...)`）或塞 cookie；
> - 或是 `act()` 只負責點到欄位，再用 `nova.page.keyboard.type(token)` 輸入（見 [01](../01-sdk/README.md#模型與程式碼的分工)）。
>
> 需要代表使用者的情境，要走 Identity 的 3LO 流程，並做好 session binding（見 [AgentCore 04](../../04-identity/)）。

## Observability：接上 CloudWatch trace

1. 安裝 `aws-opentelemetry-distro`，設定 `AGENT_OBSERVABILITY_ENABLED=true`、`OTEL_PYTHON_DISTRO=aws_distro` 等環境變數（在 Runtime 上大多已預設好）。
2. `nova.start()` 之後，用 `nova.get_session_id()` 取得 Nova Act 的 session ID，放進 OTel baggage：`baggage.set_baggage("session.id", session_id)`。
3. ADOT 自動埋點會把 trace 送到 CloudWatch，出現在 GenAI Observability 儀表板（見 [AgentCore 06](../../06-observability/)）。

> 推論：這樣可以把**三套紀錄**用同一個 session ID 串起來：AgentCore 的 trace、Nova Act Console 的 step 紀錄、以及 CloudWatch `AWS/NovaAct` 的指標（見 [02](../02-deploy-operate/README.md#觀察consolecloudwatchcloudtrail)）。官方範例只示範了 baggage，沒有說明 Nova Act 的每一步會不會自動變成 span，需要實測才知道。

## Gateway：兩個方向

- **Nova Act 當 client：** workflow 連到既有的 Gateway，把 Gateway 上的 MCP 工具傳給 `NovaAct(tools=...)`（工具功能還在 Preview，做法見 [03](../03-hitl-tools/README.md#mcp-工具)）。
- **Nova Act 當工具：** 把部署在 Runtime 的 workflow 掛到 Gateway，讓其他 agent（例如用 Claude 的 Strands agent）當成一個工具呼叫。官方只說「可以」，細節請參考 Gateway 的開發者指南（見 [AgentCore 03](../../03-gateway/)）。

> 判斷：「把 workflow 掛到 Gateway」是讓組織內其他 agent 共用瀏覽器自動化能力最乾淨的方式。例如「在供應商入口網站查訂單狀態」這個 workflow 只維護一份，所有 agent 都能透過 Gateway 使用，加上 [Policy](../../08-policy/) 控制誰可以呼叫。

## 成本疊加

| 項目 | 5 分鐘流程的估算 | 依據 |
|------|---------------|------|
| Nova Act agent hour | $4.75 × 5/60 ≈ **$0.396** | [00 計費](../00-overview/README.md#計費) |
| AgentCore Browser（1 vCPU / 4 GB） | CPU 全程滿載的上限約 $0.0075 + 記憶體約 $0.0032 ≈ **$0.011** | [AgentCore 00 計費](../../00-overview/README.md#計費模型)（v1 價格） |
| AgentCore Runtime（等待推論的 I/O 時間不收 CPU 費） | 通常 < $0.005 | 同上 |

> 推論：Nova Act 約占 97%。AgentCore 帶來的額外成本幾乎可以忽略，**省錢的關鍵是減少步數與 act 的時間**（見 [01](../01-sdk/README.md#怎麼寫-prompt)）。上表是用牌價估算的，實際的 CPU 使用率要看網頁的複雜度。

## 範例程式碼的問題清單

| 位置 | 問題 | 建議 |
|------|------|------|
| 使用者指南 Identity 範例 | `from nova_act_sdk import NovaAct`，實際套件名稱是 `nova_act` | 改成 `from nova_act import NovaAct` |
| 同上 | `NovaAct()` 沒有傳 `starting_page`，但它是必填參數（見 README 的 Reference） | 補上 |
| 同上 | token 寫進 prompt | 見上方 Identity 一節 |
| `cdk/agentcore/handler.py` | `logger.info(f"headers are {headers}")`，把 CDP 的 SigV4 認證 header 寫進 CloudWatch | 刪掉這行；log 的存取權限也要收緊 |
| 同上 | 用 `NOVA_ACT_API_KEY` 驗證，但 CDK 總覽寫「All examples use IAM Role authentication」 | 正式環境改用 `Workflow` + IAM（見 [02](../02-deploy-operate/README.md#文件中的小矛盾)） |
| `examples/agentcore` | 前置條件要求「full access」權限 | README 自己也說只是範例；正式環境請依 [05](../05-security/) 縮小權限 |

## 研究問題

- [x] Nova Act 用到哪些 AgentCore 元件、怎麼接
- [x] AgentCore Browser 的三種接法與注意事項
- [x] Identity、Observability、Gateway 的整合方式
- [x] 成本疊加
- [x] 官方範例的問題

## 參考資料

- [Integrating Nova Act with Amazon Bedrock AgentCore](https://docs.aws.amazon.com/nova-act/latest/userguide/bedrock-agentcore.html)、[Integrations](https://docs.aws.amazon.com/nova-act/latest/userguide/integrations.html)
- [aws/nova-act README：Use Nova Act SDK with AgentCore Browser Tool、Persisting browser sessions](https://github.com/aws/nova-act#use-nova-act-sdk-with-amazon-bedrock-agentcore-browser-tool)
- [nova-act-samples/cdk/agentcore](https://github.com/amazon-agi-labs/nova-act-samples/tree/main/cdk/agentcore)、[examples/agentcore](https://github.com/amazon-agi-labs/nova-act-samples/tree/main/examples/agentcore)
- [Introducing Amazon Bedrock AgentCore Browser Tool（AWS blog）](https://aws.amazon.com/blogs/machine-learning/introducing-amazon-bedrock-agentcore-browser-tool/)

## 延伸調研方向

範圍在 Nova Act 00–04 之內，以 04 為主（可引用已完成的 AgentCore 00–09）：

1. **正式環境參考架構：** 把 Runtime（ARM64）+ AgentCore Browser（依使用者分開的 profile）+ Identity（3LO，token 只在程式碼層使用）+ Nova Act `Workflow`（IAM 驗證）+ S3 trajectory 匯出組成一個 CDK stack，並修正官方範例的問題清單。沒有憑證時先做成可部署的樣板，驗證結果留空。
2. **Nova Act workflow 當 Gateway 工具：** 把 workflow 掛到 Gateway，讓一個 Strands（Claude）agent 呼叫。研究 payload 格式、長時間執行怎麼回傳結果（同步還是非同步）、怎麼用 Policy 限制誰可以觸發哪個 workflow。
3. **三套紀錄的串接：** 實測 ADOT 能不能把 Nova Act 的 act / step 自動變成 span。再設計用 session ID 串起 AgentCore trace、Nova Act Console、CloudWatch 指標和 Browser 錄影的除錯流程。
