# 延伸：Agent 的測試金字塔與 CI 整合

> 接續 [07-evaluations](README.md#五種執行模式)。這篇把五種執行模式和各類評估器排成一座「測試金字塔」，說明每一層測什麼、多久跑一次、成本多少；接著說明怎麼在 CI 裡等 CloudWatch 收進資料、怎麼設定通過門檻。
>
> 資料查核日期：2026-09-30。標示「推論」的部分是官方文件沒有明說、由我推導的。
>
> 本機工具：[experiments/ci-gate](experiments/ci-gate/)（code-based 評估器範例與 CI 門檻腳本，**用合成資料在本機測試通過；沒有在 AWS 上跑過**）。

## 結論先講

- **Agent 的測試跟傳統軟體最大的差別是「同樣的輸入，輸出不固定」。** 所以測試金字塔的底層要盡量用**確定性**的檢查（程式判斷、軌跡比對），把「LLM 評審」留給確定性方法判斷不了的部分，例如回答品質。
- **服務端沒有「通過門檻」這個功能**：沒有任何 API 欄位或 CLI 參數可以設「低於 0.8 就失敗」。**門檻必須在 CI 腳本裡自己判斷。**
- **CI 裡最麻煩的是等待：** span 要先送進 CloudWatch 才能評估，官方說要等 2–5 分鐘。SDK 的 runner 預設等 180 秒，官方的 CI 範例則是先等 60 秒，再每 30 秒重試、最多 10 分鐘。
- **官方 CI 範例的門檻取「每個評估器的最高分」**，這太寬鬆了：十題裡只要有一題過關就通過。實務上要看**平均和最低分**。

## 測試金字塔

```
                 ┌──────────────────────┐
                 │  Online 抽樣監控      │  正式流量，持續；看趨勢，不擋部署
                 ├──────────────────────┤
                 │  Simulation          │  上線前 / 每週；擴大情境覆蓋率
             ┌───┴──────────────────────┴───┐
             │  Dataset + LLM 評審           │  每次合併；回答品質的回歸測試
         ┌───┴──────────────────────────────┴───┐
         │  Dataset + 軌跡比對 + code-based 評估器 │  每次 PR；確定性、便宜、快
     ┌───┴──────────────────────────────────────┴───┐
     │  一般的單元測試：工具本身、prompt 組裝、schema 驗證  │  每次 commit；不用 AgentCore
     └──────────────────────────────────────────────┘
```

| 層 | 測什麼 | 用什麼 | 確定性 | 成本 | 建議頻率 |
|---|---|---|---|---|---|
| 單元測試 | 工具的商業邏輯、payload 驗證 | pytest / jest，不呼叫模型 | 完全確定 | 近乎 0 | 每次 commit |
| **確定性的 agent 測試** | 有沒有呼叫該呼叫的工具、有沒有呼叫禁止的工具、輸出格式、有沒有個資 | Dataset + `Trajectory*Match` + code-based 評估器 | **評分確定**（但 agent 的行為本身不確定） | 軌跡比對不花 token；code-based 每千次 $1.50 + Lambda | 每次 PR |
| **品質回歸** | 回答正不正確、有沒有幫助、有沒有捏造 | Dataset + `Correctness`（搭配 `expectedResponse`）、`GoalSuccessRate`（搭配 `assertions`） | LLM 評審，有雜訊 | 依 token 計費 | 每次合併到主線，或 prompt、模型變更時 |
| **情境擴展** | 多輪對話、沒想到的使用者行為 | Simulation | 使用者和評審都是 LLM | 評估費 + 扮演使用者的模型費 | 上線前、每週 |
| **正式環境監控** | 品質趨勢、找出低分 session | Online 評估，抽樣 | — | 依抽樣比例 | 持續 |

**判斷：**

- **軌跡比對是投資報酬率最高的一層。** 它不花 token、結果確定，而且能抓到 agent 最常見的退化：「該查資料卻沒查」「多呼叫了不該呼叫的工具」。
- **Code-based 評估器適合寫成「不變式」（invariant）**，也就是任何情況下都必須成立的規則，例如「回覆不能出現 email」「不能呼叫刪除類的工具」。它的結果只有 PASS 或 FAIL，**門檻就是 100%**。
- **LLM 評審的分數會浮動**，同一個 agent 重跑兩次可能差好幾個百分點。所以這一層的門檻要設得比較寬，而且要看多題的平均，而不是單題（見 [judge-calibration](judge-calibration.md)）。

## 各層的具體寫法

### 軌跡比對：三種模式怎麼選

| 模式 | 規則 | 例子：預期 `[calculator, weather]` | 適合 |
|---|---|---|---|
| `TrajectoryExactOrderMatch` | 工具與順序完全一致，不能多 | `[calculator, weather, calculator]` **不通過** | 流程固定的工作，例如「驗證 → 查詢 → 執行」 |
| `TrajectoryInOrderMatch` | 依序出現即可，中間可以夾其他工具 | `[calculator, search, weather]` 通過 | 有前後依賴、但允許額外查詢 |
| `TrajectoryAnyOrderMatch` | 都有出現即可，順序不拘 | `[weather, calculator]` 通過 | 只在乎「有沒有查」 |

- **只比對工具名稱，不比對參數。** 參數對不對，要用 `ToolParameterAccuracy`（LLM 評審）或自己寫 code-based 評估器。
- **判斷：** 預設用 `InOrderMatch`。`ExactOrderMatch` 太嚴格，模型多查一次資料就會失敗，測試會很不穩定；只有「多做一步就是錯」的流程才用它。

### Dataset 的格式

```json
{"scenarios": [{
  "scenario_id": "math-then-weather",
  "turns": [
    {"input": "What is 15 + 27?", "expected_response": "15 + 27 = 42"},
    {"input": "What's the weather?", "expected_response": "The weather is sunny"}
  ],
  "expected_trajectory": ["calculator", "weather"],
  "assertions": ["Agent used the calculator tool for the math question"]
}]}
```

- `expected_response` 依**順序**對應到每一輪（第 0 輪對應第 0 個 trace）；`assertions` 和 `expected_trajectory` 作用在整個 session。
- **補充（更正 07 本文）：** Dataset 不只是 SDK 端的檔案格式，**控制面也有代管的 Dataset 服務**（`CreateDataset`、`AddDatasetExamples`、`CreateDatasetVersion`）。發布的版本不可修改，Draft 可以編輯。**CI 應該固定引用某個版本**，題庫的修改才不會讓測試結果無法比較。

### Code-based 評估器的契約

輸入（官方格式）：

```json
{"schemaVersion": "1.0", "evaluatorId": "...", "evaluationLevel": "TRACE",
 "evaluationInput": {"sessionSpans": [...]},
 "evaluationReferenceInputs": [],
 "evaluationTarget": {"traceIds": ["trace123"], "spanIds": ["span123"]}}
```

輸出：成功時 `{"label": "PASS", "value": 1.0, "explanation": "..."}`（只有 `label` 是必填），失敗時 `{"errorCode": "...", "errorMessage": "..."}`。

- **一定要回傳 `value`**：沒有數值的評估器不能用在 Recommendations 和 A/B test。
- Lambda 逾時預設 60 秒，最長 300 秒；輸入超過 6 MB 會被截斷。
- SDK 有 `@code_based_evaluator()` decorator 可以省去解析的工作。
- **span 的欄位名稱依框架而不同。** 本篇的範例 `code_evaluator.py` 採用 OTel GenAI semantic conventions（`gen_ai.tool.name` 等）。接上真實 agent 之前，**先用 on-demand 撈一份真的 `sessionSpans` 下來對照**，再調整解析邏輯（推論：不同框架的 span 結構差異很大，這是最容易出錯的地方）。

### Simulation：擴大覆蓋率

```json
{"scenario_id": "geography-student",
 "actor_profile": {"traits": {"expertise": "novice", "tone": "curious"},
                   "context": "...", "goal": "Find out the capital cities of at least two different countries"},
 "input": "Hi! ...", "max_turns": 5, "assertions": ["..."]}
```

- 扮演使用者的模型在**你的環境**執行，依 Bedrock 一般價格計費。
- 結束條件：扮演者判斷目標達成、到達 `max_turns`（預設 10），或扮演者沒有產生訊息。
- **不能用 `expected_response` 和 `expected_trajectory`**，因為對話內容事先無法預測，只能用 `assertions`。
- **判斷：** Simulation 最適合測「使用者不照劇本走」的情況，例如中途改變需求、給錯資訊、情緒激動。把客服實際遇過的難纏情境寫成 actor profile，比讓 LLM 自由發揮有用。

## 在 CI 裡怎麼跑

### 三種執行方式

| 方式 | 同步或非同步 | 回傳什麼 | 適合 |
|---|---|---|---|
| **SDK：`OnDemandEvaluationDatasetRunner`** | 同步：呼叫 agent → 等待 → 評估 | 每個情境、每個評估器的分數 | **PR 檢查**（題數少、要逐題結果） |
| **SDK：`BatchEvaluationRunner`** | 非同步，內部輪詢 | **只有每個評估器的平均分數**；逐 session 的分數要去 CloudWatch 查 | 大量題目的回歸測試 |
| **CLI：`agentcore run eval` / `run batch-evaluation`** | 可加 `--wait`、`--json` | JSON 結果 | 不想寫 Python 的 pipeline |

- **`Evaluate` API 每次只能用一個評估器，最多回傳 10 筆結果，而且是「最後 10 個 trace」。** 一個 15 輪的 session，前 5 輪會被略過。長對話的測試要注意這一點。
- **Batch job 的名稱不能有 `-`**：格式是 `[a-zA-Z][a-zA-Z0-9_]{0,47}`，但官方文件的範例用了連字號，照抄會失敗。

### 等待資料進 CloudWatch

| 來源 | 建議的等待時間 |
|---|---|
| 官方文件 | 2–5 分鐘（另一頁寫 2–3 分鐘） |
| SDK runner 預設 | `evaluation_delay_seconds=180`（整次執行只等一次，不是每題都等） |
| 官方 CI 範例 | 先等 60 秒，再每 30 秒重試，最多 10 分鐘，直到每個評估器都有結果 |

**判斷：** 採用官方 CI 範例的「**先短暫等待，再輪詢到有結果為止**」，比固定等 5 分鐘好：資料早到就早結束，晚到也不會誤判失敗。並且要**區分「沒有結果」和「分數太低」**，前者通常是基礎設施的問題（資料還沒進來、instrumentation 壞了），不應該算成品質退化。本篇的 `gate.py` 用不同的結束碼區分這兩種情況。

### 門檻怎麼設

服務端沒有門檻功能，所以要在 CI 自己判斷。`gate.py` 的做法：

```json
{"Builtin.Correctness":    {"mean": 0.8, "min": 0.5},
 "Builtin.TrajectoryInOrderMatch": {"min": 1.0},
 "Custom.NoPII":           {"min": 1.0}}
```

本機測試結果：

```
✓ gate: 全部通過     exit=0
✓ gate: 有一題很差   exit=1   FAIL Builtin.Correctness mean 0.68 < 0.8；min 0.30 < 0.5（最差：s2）
✓ gate: 缺評估器結果 exit=2   MISSING Custom.NoPII
```

| 評估器類型 | 建議門檻 | 理由 |
|---|---|---|
| Code-based（不變式） | `min = 1.0` | 任何一題違規就是失敗 |
| 軌跡比對 | `min = 1.0`，或允許少數題目失敗 | 分數確定；但 agent 行為本身不確定，太嚴格會不穩定 |
| LLM 評審 | `mean` 為主，`min` 設寬鬆 | 單題分數有雜訊；看平均比較穩定 |

- **官方 CI 範例的缺陷：** 它對每個評估器「保留最高分」（原文 keep best score per evaluator），然後跟 0.8 比較。這等於只要有一題拿到 0.8 以上就通過，**幾乎不可能失敗**。實務上要改成平均或最低分。
- **門檻要跟基準線比，而不是用絕對值（判斷）：** 先在主線跑出基準分數，PR 的分數不能比基準低超過某個幅度，例如 0.05。絕對門檻（例如 0.8）在題庫變難時會一直失敗，在題庫變簡單時又抓不到退化。

### 讓測試不要太「抖」

Agent 的測試天生不穩定，同一份程式碼重跑，結果可能不同。緩解方法（判斷）：

- **題數要夠多**，看平均而不是單題。以通過率 0.7 的二元分數為例，10 題平均的標準誤約 0.14，50 題約 0.06，200 題約 0.03。題數太少，分數的正常浮動就會大於你想抓的退化幅度。
- **把 agent 的 temperature 設成 0**（如果框架允許），減少輸出的變異。
- **把「不穩定」和「失敗」分開處理：** 失敗的題目自動重跑一次，兩次都失敗才算真的失敗。
- **不要讓 LLM 評審的分數擋住每一個 PR**：PR 只擋確定性的那層；LLM 評審的結果以留言呈現，由人判斷。

## 成本估算

- 內建評估器：每千個 input token $0.0024、每千個 output token $0.012。以官方範例的「每次評估 15,000 input、300 output token」計算，**每次評估約 $0.04**。
- 一個 50 題、3 個 LLM 評估器的 PR 檢查：50 × 3 × $0.04 ≈ **$6**，再加上呼叫 agent 本身的模型費用。
- 軌跡比對不花 token；code-based 每千次 $1.50 加上 Lambda 費用。
- **判斷：** 每次 PR 跑確定性的那層（幾乎免費），合併到主線才跑 LLM 評審，可以把評估成本壓在合理範圍。

## 配額（都不能調整）

| 項目 | 值 |
|---|---|
| On-demand | 每分鐘 1,200 次評估（孟買、新加坡 200 次）、每個請求 1 個評估器 |
| Batch | 同時 5 個 job、每個 job 500 個 session、10 個評估器 |
| Dataset 的 ground truth | 每個 batch 最多 500 筆 |

**多個 PR 同時跑 CI 時，batch 的「同時 5 個 job」很容易撞到上限**，CI 需要排隊或重試。

## 參考資料

- [Code-based evaluators](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-based-evaluators.html)
- [Ground truth evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ground-truth-evaluations.html)
- [Dataset schema](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations-schema.html)、[Datasets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/datasets-getting-started.html)
- [On-demand dataset runner](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations-on-demand.html)、[Batch runner](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations-batch.html)
- [User simulation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/user-simulation.html)
- [awslabs/amazon-bedrock-agentcore-samples：cicd-gated-evaluation](https://github.com/awslabs/amazon-bedrock-agentcore-samples)（`01-features/06-observe-evaluate-optimize-your-agent/02-evaluate/cicd-gated-evaluation`）
- [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)、[Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)
