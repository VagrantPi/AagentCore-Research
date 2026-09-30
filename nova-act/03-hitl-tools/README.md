# Nova Act 的 HITL 與工具

> 讓 agent 在需要時找真人（核准、接手瀏覽器），也能呼叫瀏覽器以外的工具（Python 函式、MCP、被 Strands 當成工具）。
>
> 資料查核日期：2026-09-30。來源為使用者指南的 [HITL](https://docs.aws.amazon.com/nova-act/latest/userguide/hitl.html)、[Tool use](https://docs.aws.amazon.com/nova-act/latest/userguide/tool-use.html)、[Strands](https://docs.aws.amazon.com/nova-act/latest/userguide/strands.html) 頁面，以及 [aws/nova-act README](https://github.com/aws/nova-act)、[nova-act-human-intervention](https://github.com/amazon-agi-labs/nova-act-human-intervention)。

## TL;DR

- **HITL 有兩種模式：**
  - **Human approval**：截圖給真人，讓他選「核准 / 拒絕」或從選項中選一個，屬於非同步的決策。
  - **UI takeover**：把瀏覽器即時畫面串流給真人，讓他用滑鼠鍵盤直接操作，例如解 CAPTCHA、輸入 MFA 碼。
- **SDK 只提供介面，不是代管服務：** 你要實作 `HumanInputCallbacksBase` 的 `approve()` 和 `ui_takeover()`。通知、審核介面、串流要自己架，或部署官方的參考實作 [Human Intervention Service](https://github.com/amazon-agi-labs/nova-act-human-intervention)（CDK：WebSocket API + Step Functions + DynamoDB + S3/CloudFront + DCV，可以發 Slack / Email 通知）。
- **等真人的時間不計費：** agent hour 會扣掉 HITL 的等待時間（見 [00 計費](../00-overview/README.md#計費)）。
- **工具（Preview）：** 用 `@tool` 把 Python 函式變成工具，傳給 `NovaAct(tools=[...])`，由模型決定何時呼叫。MCP 工具要透過 **Strands 的 `MCPClient`** 轉接。每個 act 最多 100 個工具，但官方建議越少越好。
- **反過來當工具：** Nova Act 可以被包成 Strands agent 的一個工具。這時 Nova Act SDK **跟 Strands agent 跑在同一台機器上**。

## 先對齊幾個名詞

| 名詞 | 白話解釋 |
|------|---------|
| **Tool / tool use** | 模型不直接執行任何東西，它只輸出「我要呼叫 X，參數是 Y」，由 SDK 代為執行，再把結果餵回去。後端類比：模型產生一個 RPC 請求，SDK 是 RPC client |
| **MCP**（Model Context Protocol） | 把工具包成標準協定的伺服器，任何支援 MCP 的 agent 都能直接使用，不用為每個 API 各寫一套轉接器。類比：工具界的 OpenAPI + 通用 client |
| **Strands Agents** | AWS 開源的 agent 框架，用通用 LLM 當大腦，搭配各種工具（見 [AgentCore 90](../../90-integrations/)） |
| **Actuator** | SDK 裡把模型的指令轉成實際瀏覽器操作（用 Playwright）的元件 |

## Human-in-the-loop

### 兩種模式

| | Human approval | UI takeover |
|---|---|---|
| 真人要做什麼 | 看截圖，按「核准 / 拒絕」或選一個選項 | 直接操作遠端瀏覽器 |
| 同步性 | 非同步：送出請求，等人回覆 | 即時：要有人在線 |
| 典型情境 | 費用或採購核准、送出前確認資料 | CAPTCHA、登入、MFA / 2FA |
| SDK 回呼 | `approve(message) -> ApprovalResponse` | `ui_takeover(message) -> UiTakeoverResponse` |

### 怎麼觸發

```python
from nova_act import NovaAct
from nova_act.tools.human.interface.human_input_callback import (
    ApprovalResponse, HumanInputCallbacksBase, UiTakeoverResponse,
)

class MyCallbacks(HumanInputCallbacksBase):
    def approve(self, message: str) -> ApprovalResponse:
        ...  # 發通知、等人回覆（例如輪詢 DB、等 WebSocket）
    def ui_takeover(self, message: str) -> UiTakeoverResponse:
        ...  # 給真人一個能操作瀏覽器的連結，等他完成

with NovaAct(starting_page="...", tty=False, human_input_callbacks=MyCallbacks()) as nova:
    nova.act("Submit the expense report. Ask for approval before clicking submit.")
```

- 建構子文件說明：**沒有傳 `human_input_callbacks`，模型就不會發出「請求人類輸入」的工具呼叫**。
- 也就是說，**什麼時候要找人，是模型根據 prompt 和畫面判斷的**。回呼只負責「怎麼找人、怎麼等」。

> 推論：HITL 在機制上就是「SDK 內建的兩個工具」，所以「什麼時候觸發」跟一般工具一樣，由 prompt 控制。對於「一定要核准」的關鍵步驟（例如付款），不要只靠模型自己判斷，應該在 Python 裡**明確**拆成「act 到付款頁 → 程式呼叫核准流程 → 核准後才 act 付款」。這樣核准是確定性的程式邏輯，不是機率性的模型行為。

### UI takeover 需要遠端瀏覽器

真人要接手，就要**看得到、操作得到**那個瀏覽器。瀏覽器跑在不同地方，做法也不同：

| 瀏覽器在哪 | 真人怎麼接手 |
|-----------|------------|
| 本機、有畫面（headed） | 直接在螢幕上操作 |
| 本機或伺服器的 headless | 開 `--remote-debugging-port`，把 `devtoolsFrontendUrl` 傳給真人（見 [01](../01-sdk/README.md#開發迴圈)）。遠端主機要另外做 port forwarding |
| AgentCore Browser | AgentCore Console 的 Live View，或 Human Intervention Service 的 **DCV 串流**（只傳加密後的畫面像素） |

> 判斷：在雲端正式環境跑，UI takeover 實際上只能用 AgentCore Browser + DCV 這條路。暴露 CDP 除錯埠等於把瀏覽器的完整控制權交出去，不適合正式環境（見 [05](../05-security/)）。

### 官方參考實作：Human Intervention Service（HIS）

使用者指南把它稱為「Option 1：Managed Human Intervention Service（Recommended）」，但實際上它是**部署在你自己帳號裡的 CDK 專案**：

```text
Nova Act workflow ──(client SDK, WebSocket)──▶ API Gateway WebSocket
                                                    │
                                              Step Functions（管理生命週期、每 30 秒輪詢、逾時處理）
                                               │           │            │
                                            DynamoDB     S3（截圖以 KMS   Slack / SES Email 通知
                                          （狀態，TTL    加密，1 天後      （附審核頁連結）
                                            24 小時）     刪除）
                                                            │
                                               CloudFront 提供的單頁審核介面（approve）
                                               DCV Web Client 串流 AgentCore Browser（UI takeover）
```

- client SDK 透過 WebSocket **阻塞等待**，直到真人完成。範例的逾時設定是 `HITL_EXECUTION_TIMEOUT=7200`（2 小時）。
- 附 Supervisor dashboard：待處理的請求、歷史紀錄、處理時間等指標。
- ⚠️ README 寫著「用 AWS Administrator 權限跑 pattern 比較簡單」。正式環境請改用部署時產生的 `NovaAct-HITL-AssumeExecutionRole-*` 最小權限 policy。

### 文件中的小矛盾

- 使用者指南和 README 都寫「HITL 是在 SDK 裡自己實作，**不是代管的 AWS 服務**」，但同一頁又把 HIS 稱為「**Managed** Human Intervention Service」。實際上它是要自己部署、自己維運的參考實作。「Managed」大概是指「幫你寫好了」，而不是 AWS 代管。

### 官方建議

- 依情境設定逾時：登入可能需要比 CAPTCHA 更長的時間。
- 妥善處理逾時與被拒絕的情況：`approve` 被拒絕之後，流程要能乾淨地停下來。
- 所有 HITL 互動都要留紀錄，以便稽核。

> 後端類比：HITL 很像 Step Functions 的 `waitForTaskToken`。流程停在某一步，把 token 交給外部系統，等外部回呼才繼續。差別在於，Nova Act 的 session（瀏覽器）在等待期間**必須一直開著**，所以等待時間仍然受運算平台的上限限制（Lambda 15 分鐘、AgentCore Runtime 8 小時等，見 [02](../02-deploy-operate/)）。Nova Act 不收等待時間的錢，但運算平台照樣計費。

## 工具（Preview）

### 本地工具

```python
from nova_act import NovaAct, tool

@tool
def read_row_as_dict(file_path: str, row_number: int) -> dict:
    """Reads a specific row from an Excel file and returns it as a dict.

    Args:
        file_path (str): The path to the Excel file.
        row_number (int): 1-based row number.
    Returns:
        dict: column header -> value
    """
    ...

with NovaAct(starting_page="https://example.com/form", tools=[read_row_as_dict]) as nova:
    nova.act("Read row 1 from data.xlsx using read_row_as_dict, then fill the form with it")
```

- **docstring 就是給模型看的說明書：** 描述、參數、回傳型別都要寫清楚。
- log 會顯示模型的思考與呼叫過程：`think("I need to read ...")` → `tool({"name": ..., "input": ...})` → `Result for tool call ...`。
- **官方建議：** 每個 act 給的工具越少越好；prompt 的用詞要對上工具的描述；和瀏覽器操作一樣，act 要拆小。
- **需要直接操作瀏覽器的工具：** 設定 `my_tool.requires_unlocked_actuator_context = True`，執行期間 SDK 會暫停自己對瀏覽器的控制（HITL 的工具就是這樣運作的）。
- 服務端的限制：每個 act 最多 100 個工具，tool spec 總大小 350 KB（見 [00 配額](../00-overview/README.md#值得先知道的配額)）。

### MCP 工具

```python
from mcp import StdioServerParameters, stdio_client
from strands.tools.mcp import MCPClient
from nova_act import NovaAct

with MCPClient(lambda: stdio_client(StdioServerParameters(
        command="uvx", args=["awslabs.aws-documentation-mcp-server@latest"]))) as docs:
    with NovaAct(starting_page="https://aws.amazon.com/", tools=docs.list_tools_sync()) as nova:
        nova.act_get("Use the 'search_documentation' tool to tell me about Amazon Bedrock. "
                     "Ignore the web browser; do not click, scroll, type, etc.")
```

- SDK 沒有自己的 MCP client，**要借用 Strands 的 `MCPClient`**，所以必須安裝 `strands-agents`。
- 官方說支援「remote MCP」，範例用的卻是本機的 stdio server。遠端 MCP（例如 [AgentCore Gateway](../../03-gateway/)）的做法見 [04](../04-agentcore/)。
- 如果這一步不需要瀏覽器，要在 prompt 明確寫「Ignore the web browser」，否則模型可能還是去操作網頁。

> 判斷：Nova Act 的強項在「看畫面、操作 UI」。需要大量工具編排的推理任務（查 A、比對 B、決定 C），比較適合交給通用 LLM 的 agent，再把 Nova Act 當成它的一個工具（見下一節）。Tool use 目前還是 Preview，正式環境不要依賴。

## 反過來：Nova Act 當 Strands 的工具

```python
from strands import Agent, tool
from nova_act import NovaAct

@tool
def browser_automation_tool(starting_url: str, instr: str) -> str:
    """Automates tasks in a browser on the starting_url website, using the instructions provided.

    Args:
        starting_url (str): The website url to perform actions on
        instr (str): natural-language instruction for the browser task
    Returns:
        str: The result of the action performed.
    """
    with NovaAct(starting_page=starting_url) as browser:
        return str(browser.act_get(instr, max_steps=10).response)

agent = Agent(tools=[browser_automation_tool])   # Strands 預設用 Bedrock 上的通用模型當大腦
agent("On nova.amazon.com, generate an image of a wise robot and download it.")
```

- **分工：** Strands 的 LLM 負責規劃與推理（要去哪個網站、做什麼），Nova Act 負責在網頁上把事情做完。
- **執行位置：** Nova Act SDK 跑在 Strands agent 的同一台機器上。Strands 部署在 AgentCore Runtime，Nova Act 就在同一個容器裡；瀏覽器要不要放到 AgentCore Browser，要在工具內自己設定（見 [04](../04-agentcore/)）。
- 官方範例的工具把例外吃掉、回傳錯誤字串，讓上層的 LLM 自己決定要重試還是換做法。

> 判斷：**成本是兩份**：Strands 那一層的 LLM 按 token 計費，Nova Act 那一層按 agent hour 計費。上層 LLM 可能反覆呼叫工具，所以工具要設 `max_steps` 上限（範例是 10），避免單次呼叫跑太久。

## 三種架構怎麼選

| 架構 | 誰是大腦 | 適合 |
|------|---------|------|
| 純 Nova Act workflow | Python 程式碼 + Nova Act 模型 | 流程固定、以網頁操作為主（填單、擷取、QA） |
| Nova Act + 工具（Preview） | Nova Act 模型 | 網頁流程中需要少量外部資料（查 Excel、查 API） |
| Strands（或其他框架）+ Nova Act 當工具 | 通用 LLM | 需要跨系統推理、網頁只是其中一個步驟 |

## 研究問題

- [x] HITL 的兩種模式、觸發機制與實作方式
- [x] Human Intervention Service 的架構
- [x] 本地工具與 MCP 工具
- [x] Nova Act 當 Strands 的工具

## 參考資料

- [Human-in-the-loop](https://docs.aws.amazon.com/nova-act/latest/userguide/hitl.html)、[Tool use beyond the browser](https://docs.aws.amazon.com/nova-act/latest/userguide/tool-use.html)、[Strands](https://docs.aws.amazon.com/nova-act/latest/userguide/strands.html)
- [aws/nova-act README：HITL、Tool Use](https://github.com/aws/nova-act#human-in-the-loop-hitl)
- [nova-act-human-intervention](https://github.com/amazon-agi-labs/nova-act-human-intervention)
- [nova-act-samples：human_in_the_loop、tool_use](https://github.com/amazon-agi-labs/nova-act-samples/tree/main/examples)

## 延伸調研方向

範圍在 Nova Act 00–03 之內，以 03 為主：

1. **確定性的核准閘門：** 比較「在 prompt 叫模型呼叫 `approve`」和「用 Python 在關鍵步驟前強制核准」兩種寫法，在付款、送出這類不可逆操作上的可靠度。另外設計核准被拒或逾時後的補償流程。
2. **HITL 的端到端延遲與成本：** 部署 Human Intervention Service，量測從發出通知到真人回覆、流程恢復的時間分布。另外計算等待期間的運算平台費用（agent hour 不計，但容器和瀏覽器照樣收費），評估長時間等待要不要改成「存檔登入狀態 → 結束 session → 核准後重開」。
3. **Strands + Nova Act 的分層成本：** 用同一個任務比較「純 Nova Act workflow」和「Strands 大腦 + Nova Act 工具」的成功率、token 成本與 agent hour，找出值得加上一層通用 LLM 的情境。
