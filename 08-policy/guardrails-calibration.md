# 延伸：Guardrails in policy 的門檻校準與縱深防禦

> 接續 [08-policy](README.md#2-guardrails-in-policy)。這篇討論：怎麼用 `LOG_ONLY` 收集分數、標註、選門檻；`suppressOutput` 在工具輸出上實際能做到什麼；以及它跟 Runtime 的輸入驗證、Memory poisoning 防護、Evaluations 的安全評估器之間怎麼分工。
>
> 資料查核日期：2026-09-30。標示「推論」的部分是官方文件沒有明說、由我推導的。
>
> 本機工具：[experiments/guardrail-threshold](experiments/guardrail-threshold/)（用合成資料驗證過可以執行；**沒有真實的 guardrail 分數**）。

## 結論先講

- **分數只有 6 種值（0、0.2、0.4、0.6、0.8、1.0）**，所以「選門檻」其實只有 5 個選項。與其調小數，不如**用資料算出每個選項的誤擋與漏擋**，再依照業務成本挑一個。
- **`suppressOutput` 不是遮罩，是整個輸出拿掉：** 08 本文把它寫成「遮蔽個資」，這個說法**不精確，這裡更正**。文件沒有任何「只遮掉某幾個字」的機制；而且輸出被拿掉時，**工具的副作用已經發生了**。
- **Guardrail 分數在 LOG_ONLY 期間看得到，但「被評估的內容」不一定記下來。** 要做標註，得把 span 的分數跟你自己的請求紀錄 join 起來，所以事前就要規劃好請求 ID 的串接。
- **縱深防禦的分工原則：** Policy 的 guardrail 只看得到「**工具呼叫的參數與輸出**」。使用者的原始輸入、模型的最終回覆、寫進記憶的內容，都要在其他層處理。

## 先釐清：分數代表什麼

| Guardrail | 分數名稱（Bedrock 官方用語） | 意義 |
|---|---|---|
| `ContentFilter`、`PromptAttack` | severity score | 內容**符合該類別的強度**，不是模型的確信度 |
| `SensitiveInformation` | confidence score | 偵測到個資的確信度 |

- AgentCore 的語法三種都用 `.confidenceScore`，但意義不同。**PromptAttack 0.8 的意思是「很像攻擊」，不是「80% 機率是攻擊」**，所以不能把它當機率解讀，也不能跨類別比較。
- **預設門檻只在用自然語言產生 policy 時才會套用**（ContentFilter 0.2、PromptAttack 0.4、SensitiveInformation 0.2）。手寫的 policy 一定要自己寫門檻。
- 可用的比較方式：`.greaterThan / .greaterThanOrEqual / .lessThan / .lessThanOrEqual(decimal("X"))`，以及 `.maxConfidenceScore()`、`.minConfidenceScore()`、`.count()`。

## 校準流程

```
1. 寫好 guardrail policy，policy 本身設成 LOG_ONLY（或整個 engine 設成 LOG_ONLY）
2. 讓正式流量跑一段時間，收集每次評估的分數
3. 抽樣、人工標註（這次到底該不該擋）
4. 對每個門檻算混淆矩陣，用業務成本挑門檻
5. 切到 ACTIVE / ENFORCE，持續看 LogOnlyDecisionFlips 與誤擋回報
```

### 分數去哪裡找

| 來源 | 內容 | 用途 |
|---|---|---|
| CloudWatch metric（`AWS/Bedrock-AgentCore`） | `ConfidenceScore`、`ConfidenceThreshold`（維度 `PolicyEnforcementMode=LOG_ONLY`）、`LogOnlyMatches`、`LogOnlyDecisionFlips`、`GuardrailLatency`、`SuppressOutputs` | 看整體分布與趨勢 |
| Span（`aws/spans` log group，需要開啟 gateway 的 tracing） | `aws.agentcore.policy.guardrails.<category>.scores`（policy、filter、分數的組合）、`…log_only_decision_flipping_policies…`、`aws.agentcore.policy.effects` | **逐筆的分數**，用來標註 |

- **`LogOnlyDecisionFlips` 是最重要的上線訊號：** 它代表「如果現在切成強制，決策會改變」的次數。持續為 0 表示切換是安全的；不為 0 就要逐筆檢查是誤擋還是真的該擋。
- ⚠️ **文件矛盾：** guardrail 的說明頁寫「每筆紀錄都包含被評估的內容和分數」，但 span 屬性的列表裡**沒有內容欄位**。在確認之前，要假設**拿不到原文**，必須用 trace ID 或請求 ID 去 join 你自己的應用程式 log（推論）。
- 每個請求的比對清單最多記錄 1,000 筆。

### 標註的實務建議（判斷）

- **正常流量佔絕大多數**，隨機抽樣會幾乎都是 0 分。建議**分層抽樣**：每個分數等級各抽一定數量，高分的全部看。
- **自己準備一批攻擊樣本混進測試流量**，例如已知的 prompt injection 句型、含個資的測試資料。這樣才有足夠的正樣本估算漏擋率。
- 標註的問題要具體：不是「這是不是攻擊」，而是「**如果這次被擋，是對的嗎？**」

### 選門檻：用成本，而不是用直覺

本機工具 `calibrate.py` 讀入「分數 + 標註」，對 5 個門檻算出混淆矩陣和總成本。以下是用**合成資料**跑出來的示範（500 筆，其中 40 筆應擋）：

```
 門檻   TP   FP   FN   TN  precision  recall  誤擋率   成本(誤擋=1, 漏擋=20)
  0.2   37  143    3  317       0.21    0.93    0.31    203.0
  0.4   33   86    7  374       0.28    0.82    0.19    226.0
  0.6   26   42   14  418       0.38    0.65    0.09    322.0
  0.8   13   17   27  443       0.43    0.33    0.04    557.0
  1.0    4    7   36  453       0.36    0.10    0.02    727.0
```

- **同一份資料，成本假設不同，答案就不同：** 漏擋成本是誤擋的 20 倍時（例如轉帳工具），最佳門檻是 0.2；兩者成本相同時（例如一般問答），最佳門檻是 1.0。
- **所以門檻應該「依工具」設定，而不是全域一個值。** 高風險工具用低門檻，寧可多擋；低風險工具用高門檻，減少干擾。Policy 本來就是一個工具一條，正好可以這樣做。
- **別忘了誤擋的隱性成本：** 模型收到拒絕後可能反覆重試，每次重試都會再付一次 guardrail 和模型的費用。

## `suppressOutput` 實際上做什麼

官方原文：「operates on the data an action returns. After an authorized action is completed, it evaluates the outputs against the guardrail and suppresses the output when the guardrail is violated.」

| 問題 | 答案 |
|---|---|
| 是遮罩部分內容，還是整個拿掉？ | **整個輸出拿掉**。文件沒有任何「只遮掉個資那幾個字」的機制 |
| 呼叫端收到什麼？ | **文件沒寫**（MCP 的 `isError`？空內容？HTTP 狀態碼？），官方範例也沒有涵蓋，**需要實測** |
| 工具的副作用呢？ | **已經發生了**。例如「寄信」工具，信已經寄出，只是結果沒有回傳給模型 |
| 能搭配一般 Cedar 或 temporal 條件嗎？ | **不行**，只能用 guardrail 條件 |

**判斷：**

- **`suppressOutput` 適合「讀取型」工具**，例如查詢客戶資料、搜尋文件，目的是**不讓個資進到模型的 context**（進去之後就可能被寫進回覆、寫進記憶，或被記到 log）。
- **不適合「寫入型」工具**，因為副作用已經發生。寫入型工具要在**輸入端**用 `forbid` 攔截。
- **真正的個資遮罩，應該在工具本身（後端 API）做**：只回傳必要欄位，或回傳已經遮罩過的值。`suppressOutput` 是在工具忘了遮罩時的最後一道防線。
- 被擋掉的輸入回 403，錯誤訊息會帶 policy 名稱，例如 `Policy evaluation denied due to blockviolence-xxxxx`。**不要在 policy 名稱裡透露太多規則細節**，因為模型和使用者都可能看到（推論）。

### 其他限制

- **能用的 guardrail 只有三類：** ContentFilter、PromptAttack、SensitiveInformation。**沒有 denied topics、自訂詞彙、contextual grounding、正則表達式。** 需要這些的話，要在 Runtime 裡自己呼叫 Bedrock Guardrails 的 ApplyGuardrail。
- **能不能跟一般 Cedar 條件混用，文件互相矛盾：** guardrail 說明頁說 `when guardrails {…}` 會取代 `when {…}`、不能混用；temporal 的撰寫頁卻有一個範例同時用了 temporal、guardrail 和一般條件。上線前用預設的 `FAIL_ON_ANY_FINDINGS` 驗證，以實際結果為準。
- **支援的區域：** us-east-1、us-east-2、us-west-2、雪梨、東京、倫敦、斯德哥爾摩。
- **Gateway 的 execution role 需要 `bedrock:InvokeGuardrailChecks` 權限。**

## 縱深防禦：各層各管什麼

Policy 的 guardrail 位在 Gateway，所以它**只看得到經過 Gateway 的工具呼叫**。其他的攻擊面要在其他層處理：

```
使用者輸入 ──► Runtime ──► 模型 ──► Gateway（Policy）──► 工具
   │              │           │            │                 │
   │              │           │            │                 └─ 輸出 ──► suppressOutput
   │              │           │            └─ 參數：forbid + guardrail
   │              │           └─ 最終回覆：（Policy 看不到）
   │              └─ 輸入驗證、ApplyGuardrail
   └─ 寫進 Memory 之前：（Policy 看不到）
```

| 攻擊面 | 負責的元件 | 做法 | 說明 |
|---|---|---|---|
| **Payload 格式** | Runtime（[01](../01-runtime/README.md)） | 驗證 `prompt` 是字串、用 schema 驗證整個 payload | 擋下「把 `prompt` 塞成 `toolUse` 結構」這類**直接跳過模型和 guardrail** 的攻擊。這一層不能省 |
| **使用者的原始輸入** | Runtime | 在呼叫模型前用 ApplyGuardrail | Policy 看不到使用者說了什麼，只看得到模型決定傳給工具的參數 |
| **工具的參數** | **Policy** | `forbid` + PromptAttack / SensitiveInformation | 擋下「模型被操控後，把惡意內容或個資傳給工具」 |
| **工具的輸出** | **Policy** | `suppressOutput` | 擋下個資或間接 prompt injection 進到 context。**間接注入（工具回傳的網頁或文件裡藏著指令）是 agent 特有的風險**，這一層很有價值 |
| **寫進記憶的內容** | Memory（[02](../02-memory/README.md#安全memory-poisoning)） | `CreateEvent` 前過濾、`extractionMode: SKIP`、override 的萃取 prompt | Policy 完全碰不到這條路徑。被污染的記憶會影響**之後所有的對話** |
| **模型的最終回覆** | Runtime | 回傳前用 ApplyGuardrail | Policy 看不到模型最後跟使用者說了什麼 |
| **整體安全表現的監控** | Evaluations（[07](../07-evaluations/README.md)） | `Harmfulness`、`Stereotyping`、`Refusal` 評估器，online 抽樣 | **事後量測**，不會擋任何東西；用來發現前面幾層漏掉的東西，以及門檻是不是太嚴（`Refusal` 分數升高） |

**判斷：**

- **Policy 的 guardrail 最大的價值在「工具的輸入與輸出」這兩個點**，因為這是 agent 跟外部世界互動的地方，也是傳統的輸入輸出過濾照顧不到的地方。
- **Evaluations 是校準回饋的來源之一：** 在 Policy 切到強制之後，如果 `Refusal` 評估器的分數明顯上升，可能表示門檻太嚴，模型頻繁被擋而放棄回答。
- **Memory 是最容易被忽略的一層：** 攻擊者透過對話植入的內容，就算工具呼叫都被 Policy 擋下，**仍然可能被萃取成長期記憶**。這一層必須在 Memory 自己處理。

## 成本

- **Guardrail 依 Bedrock 的 InvokeGuardrailChecks 價格計費**（不是一般的 ApplyGuardrail 價格），每 1,000 個文字單位（一個單位最多 1,000 字元）：

  | 類型 | 價格 |
  |---|---|
  | ContentFilter | $0.07 |
  | PromptAttack | $0.08 |
  | SensitiveInformation | $0.10 |

- 授權請求本身另外計費，每次 $0.000025。
- **每條 policy、每個資料路徑是不是各算一次，文件沒寫**（需要實測）。如果是，同一個工具掛三條 guardrail policy，成本就是三倍。
- **延遲沒有公開數字**，只能看 `GuardrailLatency` metric。每個工具呼叫都多一次 guardrail 檢查，對多步驟的 agent 會累積成可觀的延遲。

## 參考資料

- [Guardrails in policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-guardrails-in-policies.html)、[Getting started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-guardrails-getting-started.html)
- [Policy metrics](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-policy-metrics.html)
- [Test a policy（LOG_ONLY）](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-test-a-policy.html)
- [Bedrock Guardrails：scores](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-invoke-guardrail-checks-scores.html)
- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)、[AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
