# 延伸：LLM 評審的可靠度校準

> 接續 [07-evaluations](README.md#評估器)。這篇討論：怎麼用一小批人工標註，檢查內建評審、換過模型的評審（CustomDerived）、自訂評審跟人的判斷有多一致；從官方公開的評審 prompt 看出哪些偏誤；以及哪些指標應該改用確定性的方法。
>
> 資料查核日期：2026-09-30。標示「推論」的部分是官方文件沒有明說、由我推導的。
>
> 本機工具：[experiments/judge-agreement](experiments/judge-agreement/)（一致性分析腳本；**示範資料是合成的**，不是真實的評審結果）。

## 結論先講

- **官方沒有提供任何校準機制或一致性數據：** 文件裡沒有「評審跟人工判斷的一致率」，也沒有偏誤清單或校準流程。**你得自己做。**
- **內建評審的模型不公開，也不能換。** 要控制模型，就用 CustomDerived（沿用內建的 prompt 和量表、換成你指定的模型）或完全自訂的評審。
- **從公開的評審 prompt 就能看出幾個「寬鬆」傾向：** 例如 `Faithfulness` 預設給最高分，除非看到矛盾；`InstructionFollowing` 在沒有明確指示時預設給「是」。這些不是 bug，而是設計取向，但**會讓分數普遍偏高**。
- **做法：** 標註 100–200 個 session，算每個評審跟人工的 **Cohen's kappa**（扣掉碰巧一致之後的一致程度），並檢查分數有沒有跟「回覆長度」這類不該有關的因素相關。kappa 太低的指標，就不要拿來擋部署。

## 為什麼 LLM 評審需要校準

「LLM-as-a-judge」是讓一個模型讀完對話，依照評分說明打分數。它比人工便宜、比規則有彈性，但有幾個已知的問題（這些是業界對 LLM 評審的普遍觀察，不是 AgentCore 文件寫的）：

| 問題 | 說明 | 類比 |
|---|---|---|
| **雜訊** | 同一段對話評兩次，分數可能不同 | 同一份考卷給不同的閱卷老師 |
| **長度偏誤** | 傾向給比較長、看起來比較完整的回答高分 | 作文寫得長，分數就比較高 |
| **自我偏好** | 評審模型跟被評的模型同一家時，可能給比較高的分數 | 球員兼裁判 |
| **寬鬆傾向** | 評分說明寫得模糊時，傾向給高分 | 沒有評分標準的面試 |

## 三種評審的比較

| | Built-in | CustomDerived | 自訂 LLM 評審 |
|---|---|---|---|
| 評分 prompt | 官方的，公開但**不能改** | 沿用內建或第三方的 | 自己寫 |
| 評審模型 | **不公開**，不能換 | 你指定的 Bedrock 模型 | 你指定的 Bedrock 模型，或 Bedrock Mantle 的模型（例如 `openai.gpt-oss-120b`） |
| 推論參數 | 不能調 | `temperature`、`topP`、`maxTokens` | 同左；Mantle 模型另有 `reasoning.effort` |
| 模型在哪裡跑 | AgentCore；可能**跨區域** | 你的帳號（online 用 execution role，on-demand 用呼叫者的憑證） | 同左 |
| 官方品質保證 | 「tested and benchmarked」（但沒有公布數據） | 「The service doesn't validate the model against each metric」 | 無 |

設定範例（CustomDerived，把內建評審換成指定模型、temperature 設 0）：

```json
{"derived": {
  "baseEvaluatorId": "Builtin.Helpfulness",
  "modelConfig": {"bedrockEvaluatorModelConfig": {
    "modelId": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "inferenceConfig": {"temperature": 0.0, "topP": 1.0, "maxTokens": 2048}}}}}
```

- **沒有 seed 參數**，所以就算 temperature 設成 0，也不保證每次結果完全相同。
- **官方範例自己也不一致：** 主要範例用 `temperature: 1.0`，ground truth 的範例用 `0.0`。**評審一律建議用 0**（判斷），因為評審要的是穩定，不是創意。
- **輸出格式由服務端控制：** 服務會在你的 prompt 後面附加一段固定的指示，強制模型先寫理由、再給分數。官方說**不要自己加輸出格式的要求**。

## 從公開的評審 prompt 看出的傾向

內建評審的 prompt 範本是公開的，可以直接讀出評分邏輯：

| 評估器 | Prompt 裡的原文 | 影響 |
|---|---|---|
| `Faithfulness` | 「You should select 'Completely Yes' unless you see any information… conflicting」 | **預設給最高分**，只有看到明確矛盾才扣分。捏造了但沒有跟上下文矛盾的內容，可能不會被抓到（推論） |
| `InstructionFollowing` | 模型的回應完全迴避時，也評為「Yes」；沒有明確指示時預設為「Yes」 | 分數普遍偏高；**迴避問題也可能拿高分** |
| `GoalSuccessRate`（有 ground truth） | 「Evaluate assertions by their intent, not by exact text matching… Ignore style and verbosity」 | 只看意圖，不看字面；這是合理的設計，但斷言寫得模糊時會偏寬鬆 |
| 共通 | 理由限制在 250 字（部分範本 200 字） | 複雜的判斷可能講不清楚 |

- **量表是文字標籤，不是數字：** 例如 `Helpfulness` 有 7 個等級，官方範例裡「Very Helpful」對應 0.83，推測是 0 到 1 平均分配（推論）。
- ⚠️ **內建評估器的數量說法不一：** 定價頁寫 13 個，文件列出 17 個評審 prompt 範本，07 本文依評估器清單寫 16 個。以文件的清單為準。

## 校準流程

```
1. 抽樣：從正式流量或測試流量抽 100–200 個 session（分層：高分、低分、中間都要有）
2. 人工標註：每個 session 對每個要校準的指標，給 Pass/Fail（或同樣的量表）
3. 跑評審：同一批 session，跑 built-in、CustomDerived、自訂評審
4. 算一致性：一致率、Cohen's kappa、混淆矩陣
5. 找偏誤：分數跟長度、語言、工具數量等「不該有關」的因素是否相關
6. 決策：kappa 夠高的指標可以用來擋部署；不夠的只當參考，或改用確定性的方法
```

### 為什麼要用 kappa，而不是一致率

假設 90% 的 session 在人工判斷下都是 Pass。一個**永遠回答 Pass** 的評審，一致率也有 90%，但它其實什麼都沒判斷。Cohen's kappa 扣掉了「碰巧一致」的部分：永遠回答 Pass 的評審，kappa 是 0。

常用的解讀分級：< 0.4 差、0.4–0.6 普通、0.6–0.8 良好、> 0.8 很好。

### 示範：用合成資料跑一次

`agreement.py` 讀入「人工判定 + 各評審判定 + 回覆長度」，輸出一致性和長度偏誤。以下是用**合成資料**跑的結果（200 個 session，刻意設計成「內建評審偏寬鬆、偏好長回覆」）：

```
評審                    一致率  kappa   TP  FP  FN  TN   偽陽率(短)  偽陽率(長)
builtin_helpfulness     0.85   0.61   133  23   7  37      0.19       0.59
custom_judge            0.86   0.69   123  10  17  50      0.26       0.07
```

怎麼讀：

- **兩個評審的一致率幾乎一樣（0.85 和 0.86），但錯的方向不同。** 內建評審的錯誤主要是**誤判為 Pass**（FP 23），自訂評審則是**誤判為 Fail**（FN 17）。只看一致率會以為兩者差不多。
- **「偽陽率」是人工判定為 Fail、評審卻給 Pass 的比例。** 內建評審在長回覆上的偽陽率是 0.59，短回覆只有 0.19，**表示它被長度影響了**。自訂評審沒有這個現象。
- 要擋部署的話，**偽陽（放過壞的）通常比偽陰（誤擋好的）更危險**，這時自訂評審比較適合。

再強調一次：這份資料是合成的，只用來說明工具怎麼用、結果怎麼讀。**真實的偏誤要用你自己的標註資料才看得出來。**

### 標註的實務建議（判斷）

- **至少兩個人標註同一批資料**，先算人跟人之間的 kappa。如果人跟人之間都只有 0.5，那評審能到 0.5 就已經是上限了，問題在於**指標本身定義不清**。
- **評分說明要寫成「可以判斷」的形式：** 「回答是否有幫助」很難判斷；「回答是否包含使用者要求的訂單編號與出貨日期」就很容易。
- **官方的建議**：在自訂評審的 prompt 裡放 1–3 個「人會怎麼評」的範例；不確定時，先從二元（Pass/Fail）量表開始。

## 哪些指標應該改用確定性的方法

| 指標 | LLM 評審的問題 | 改用 |
|---|---|---|
| 有沒有呼叫正確的工具 | 不需要判斷力 | `Trajectory*Match`（程式判斷，不花 token） |
| 輸出格式（JSON、欄位） | 模型可能漏看 | Code-based 評估器，直接解析 |
| 有沒有洩漏個資 | 評審可能漏判；而且評審本身也會讀到個資 | Code-based 評估器用正則表達式，或 Policy 的 guardrail |
| 數字計算是否正確 | 模型本身就不擅長算術 | Code-based 評估器重算一次 |
| 是否符合業務規則（金額上限等） | 規則是確定的 | Code-based 評估器，或直接在 Policy 攔截 |
| 回答品質、語氣、完整度 | — | **留給 LLM 評審**，這是它真正的用途 |

**判斷：** 能用程式判斷的就用程式判斷。LLM 評審只負責「需要理解語意才能判斷」的部分，而且只在 kappa 夠高時才用來擋部署。

## 持續校準

- **評審的模型或 prompt 一改，就要重新校準。** 所以 CustomDerived 和自訂評審**要固定模型版本**，不要用會自動更新的別名（推論）。
- **內建評審的模型不公開，AWS 更新時你不會知道。** 建議保留一批固定的標註資料，定期（例如每月）重跑，看 kappa 有沒有變化（判斷）。
- **自訂評審一旦被啟用中的 online 設定引用，就不能修改**（更正 07 本文：這個限制適用於**所有**自訂評估器，不只是 code-based）。要改就得複製一份新的，再切換設定。

## 成本

- 內建評審依 token 計費；CustomDerived 和自訂評審每千次評估 $1.50，**模型費用另計**（在你的帳號）。
- 校準本身的成本主要是**人工標註的時間**。200 個 session × 3 個指標，大約是一個人一到兩天的工作量（推論，依對話長度而定）。

## 參考資料

- [Built-in evaluators](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/built-in-evaluators-overview.html)、[Prompt templates](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/prompt-templates-builtin.html)
- [Third-party and derived evaluators](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/third-party-evaluators.html)
- [Create a custom evaluator（含 best practices）](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/create-evaluator.html)、[Update evaluator](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/update-evaluator.html)
- [Cross-region inference](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations-cross-region-inference.html)
- Cohen's kappa 的分級：Landis, J. R. & Koch, G. G. (1977). *The Measurement of Observer Agreement for Categorical Data*
