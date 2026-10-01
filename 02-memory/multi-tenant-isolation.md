# 延伸：Memory 多租戶隔離的參考實作

> 接續 [02-memory](README.md#namespace-設計與多租戶隔離)。這篇從「後端決定 actorId 與 namespace」開始，逐層加上 IAM 條件、Gateway 的細粒度授權（FGAC），並處理批次 API、跨使用者 reflection、以及「刪除某個使用者全部資料」這幾個缺口。
>
> 資料查核日期：2026-10-01。標示「推論」的部分是官方文件沒有明說、由我推導的。
>
> 本機實作：[experiments/tenant-guard](experiments/tenant-guard/)（後端隔離層與刪除流程，用假的 client 測試 9 個案例全部通過；呼叫 AWS 的參數已對 botocore 1.43.105 的 model 離線驗證）。

## 結論先講

- **IAM 其實可以依 actorId 限制短期記憶（更正 02 本文）：** IAM 的官方參考列出了 `bedrock-agentcore:actorId` 和 `sessionId` 兩個 condition key，適用於 `CreateEvent`、`GetEvent`、`ListEvents`、`DeleteEvent`。但**只有在「每個使用者或租戶各自用不同的 IAM principal 呼叫」時才有用**。最常見的「後端用一個 role 服務所有人」架構，IAM 還是分不出使用者。
- **最基本、也最有效的一層是後端：** `actorId`、`sessionId`、`namespace` 一律從**已驗證的身分**推導，前端傳來的一概不用。這一層做對了，後面幾層是縱深防禦；這一層做錯了，後面幾層也救不回來。
- **actorId 的格式要自己驗：** AgentCore 允許 actorId 含有 `/` 和 `:`。如果 `sub` 是 `alice/x`，它的資料會落在 `.../alice/*` 這個 namespace 前綴底下，跟 alice 混在一起。
- **沒有「刪除某個使用者全部資料」的 API：** 只能逐個 session、逐筆 event 刪，再依 namespace 列出 record 分批刪。**namespace 裡沒有 actorId 的 record（例如跨使用者的 reflection）無法歸屬到個人，也就刪不乾淨。**

## 四層防線

```
前端 ──► 你的後端（第 1 層：從 JWT 推導 actorId / namespace）
            │
            ├─ IAM（第 2 層：principal 能碰哪些 actorId / namespace）
            │
            ├─ Gateway + Cedar（第 3 層：每個請求的 actorId 必須等於 JWT 的 sub）
            │
            └─ Memory resource policy（第 4 層：只接受經由 Gateway 的請求）
```

| 層 | 能防什麼 | 前提 | 缺口 |
|---|---|---|---|
| **1. 後端推導身分** | 前端竄改 actorId、namespace | 後端程式正確 | 後端本身有 bug 或被攻破 |
| **2. IAM 條件** | 某個 principal 存取不該存取的 actorId / namespace | **每個租戶（或使用者）有自己的 principal** | 共用 principal 時無效；部分 API 沒有對應的 condition key |
| **3. Gateway + Cedar** | 共用 principal 時，依 JWT 的身分逐請求檢查 | Memory 經由 Gateway 存取 | 批次 API、`IngestData` 不經過 Cedar |
| **4. Resource policy** | 有人繞過 Gateway 直接呼叫 Memory | 官方範例**需要補上 Deny** | — |

## 第 1 層：後端推導身分

參考實作 `guard.py` 的做法：

```python
def actor_id_for(claims):                          # claims 必須是已驗證過簽章的 JWT
    actor = f"{claims['tenant']}_{claims['sub']}"  # 租戶前綴：不同租戶的 sub 撞名也不會混在一起
    if not SAFE.match(actor):                      # [A-Za-z0-9][A-Za-z0-9_-]{0,99}，拒絕 / 和 :
        raise IsolationError(...)
    return actor

def actor_namespace(strategy_id, actor_id):
    return f"/strategy/{strategy_id}/actor/{actor_id}/"   # 結尾的 / 不能省
```

- **前端只能提供「內容」和「查詢字串」**，`actorId`、`sessionId`、`namespace` 都由後端決定。
- **sessionId 也要驗格式**，或者乾脆由後端產生。
- **檢索時每個 strategy 各查一次自己的 actor namespace**，不要用 `namespacePath` 做前綴查詢，除非確定前綴不會比對到別人（推論：`/actor/alice` 會比對到 `/actor/alice2`，結尾一定要加 `/`）。

本機測試的 9 個案例（`python3 test_local.py`）：

```
✓ actorId 由後端推導（租戶前綴）
✓ sub 含 / 會被拒絕
✓ 缺 tenant claim 會被拒絕
✓ sessionId 含 / 會被拒絕
✓ alice 只檢索到自己的 150 筆
✓ namespace 結尾有 /
✓ 刪除 alice：2 筆事件、150 筆 record（分兩批）
✓ alice2 的資料不受影響
✓ 跨使用者的 reflection 刪不到（已知限制）
```

## 第 2 層：IAM 條件

### 每個 API 可用的 condition key

依 IAM 的官方參考（Service Reference JSON，2026-09-25 版）：

| API | 可用的 Memory 專屬 key |
|---|---|
| `CreateEvent`、`GetEvent`、`ListEvents`、`DeleteEvent` | **`actorId`、`sessionId`** |
| `ListSessions` | `actorId` |
| `RetrieveMemoryRecords`、`ListMemoryRecords` | `namespace`、`strategyId` |
| `BatchCreateMemoryRecords`、`BatchUpdateMemoryRecords` | `namespace` |
| `StartMemoryExtractionJob` | `actorId`、`sessionId`、`strategyId` |
| `ListActors`、`GetMemoryRecord`、`DeleteMemoryRecord`、`BatchDeleteMemoryRecords`、`ListMemoryExtractionJobs` | **沒有** |
| `IngestData` | **不在 IAM 參考的 action 清單裡** |

⚠️ **文件之間的矛盾，要實測：**

- **`namespacePath` 和 `namespaceVariable/<key>` 只出現在開發指南**，IAM 的官方參考沒有列出。02 本文把它們寫成既定的 key，需要實測確認。
- **`GetMemoryRecord`、`DeleteMemoryRecord`、`BatchDeleteMemoryRecords` 的 API 有一個選填的 `namespace` 參數**，說明是「用於 IAM condition key 授權」，但 IAM 參考沒有對應的 key。**服務會不會檢查你給的 namespace 跟 record 實際所在的 namespace 一致，文件沒寫。** 如果不檢查，知道別人 record ID 的人，就能帶一個自己被允許的 namespace 去刪它（推論）。
- **`IngestData` 有 API、需要 `bedrock-agentcore:IngestData` 權限，但不在 IAM 參考、resource policy、跨帳號清單、Gateway connector 的任何清單裡。** 目前沒辦法用 condition key 或 Cedar 限制它。

**其他缺口：**

- **`ListActors` 沒有任何 key：** 有這個權限的人，能列出這個 memory 裡所有使用者的 actorId。
- **`ListMemoryExtractionJobs` 沒有 key**，而它的輸出含有 actorId 和 sessionId。
- **Record 沒有 actorId 欄位**（只有 ID、內容、strategy ID、namespace、建立時間、metadata）。所以長期記憶要依使用者隔離，**只能靠 namespace 裡包含 actorId**。

### 官方範例

讀取（限制 namespace）：

```json
{"Sid": "SpecificNamespaceAccess", "Effect": "Allow",
 "Action": ["bedrock-agentcore:RetrieveMemoryRecords"],
 "Resource": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/memory_id",
 "Condition": {"StringEquals": {"bedrock-agentcore:namespace": "summaries/agent1/"}}}
```

寫入（限制自訂變數的值）：

```json
{"Sid": "AllowCreateEventForAcme", "Effect": "Allow",
 "Action": "bedrock-agentcore:CreateEvent",
 "Resource": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/memory_id",
 "Condition": {"StringEquals": {"bedrock-agentcore:namespaceVariable/orgname": "acme"}}}
```

### 每個租戶一個 role 的設計

如果每個租戶的後端（或每個租戶的 agent）用各自的 IAM role，可以這樣限制（推論：組合官方的 key，沒有官方範例）：

```json
{"Effect": "Allow",
 "Action": ["bedrock-agentcore:CreateEvent", "bedrock-agentcore:GetEvent",
            "bedrock-agentcore:ListEvents", "bedrock-agentcore:DeleteEvent", "bedrock-agentcore:ListSessions"],
 "Resource": "arn:aws:bedrock-agentcore:REGION:ACCOUNT:memory/MEMORY_ID",
 "Condition": {"StringLike": {"bedrock-agentcore:actorId": "acme_*"}}},
{"Effect": "Allow",
 "Action": ["bedrock-agentcore:RetrieveMemoryRecords", "bedrock-agentcore:ListMemoryRecords"],
 "Resource": "arn:aws:bedrock-agentcore:REGION:ACCOUNT:memory/MEMORY_ID",
 "Condition": {"StringLike": {"bedrock-agentcore:namespace": "/strategy/*/actor/acme_*"}}}
```

- 這就是第 1 層要用「租戶前綴」的另一個理由：**IAM 只能用 `StringLike` 比對前綴**，actorId 要有一致的格式才寫得出條件。
- ⚠️ 用 `_` 當分隔字元時，`acme_*` 也會比對到 `acme_corp_bob`（另一個叫 `acme_corp` 的租戶）。**租戶 ID 本身不能含分隔字元**，或改用租戶 ID 不可能出現的字元當分隔（推論）。
- **ABAC**（用 `${aws:PrincipalTag/tenant}` 帶入條件）是合法的 IAM 語法，但**官方沒有 Memory 的範例**，要實測。
- `ListActors`、`GetMemoryRecord`、`DeleteMemoryRecord` 沒有 key，**每個租戶的 role 不要給這些權限**，需要時由一個受控的管理用 role 執行。

## 第 3 層：Gateway + Cedar（共用 principal 的情況）

### 怎麼接

在 Gateway 上建立一個 connector 型的 target：

```json
"http": {"connector": {"source": {"connectorId": "agentcore-memory"}, "parameters": {"memoryId": "your-memory-id"}}}
```

- Inbound 用 JWT 時，outbound 必須用 Gateway 的 IAM role。這時**IAM 看到的是 Gateway 的 role**，第 2 層針對個別使用者的 IAM 條件不會生效（官方原文：「are not evaluated against the original caller」），所以 per-user 的檢查全部靠 Cedar。
- 曝露 12 個操作（`ListEvents`、`CreateEvent`、`GetEvent`、`DeleteEvent`、`ListSessions`、`ListActors`、`RetrieveMemoryRecords`、`ListMemoryRecords`、`GetMemoryRecord`、`DeleteMemoryRecord`、`ListMemoryExtractionJobs`、`StartMemoryExtractionJob`）。Action 名稱是 `<target>___<METHOD>:<URI 樣板>`，**不能用萬用字元**。
- **沒有曝露的：** 三個批次 API 和 `IngestData`。

### Cedar 範例（官方）

```cedar
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"<target>___POST:/memories/{memoryId}/actor/{actorId}/sessions/{sessionId}",
  resource == AgentCore::Gateway::"<gw-arn>"
) when {
  principal.hasTag("sub") &&
  context has input && context.input has actorId &&
  context.input.actorId == principal.getTag("sub")
};
```

```cedar
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"<target>___POST:/memories/{memoryId}/retrieve",
  resource == AgentCore::Gateway::"<gw-arn>"
) when {
  principal.hasTag("namespace") &&
  context has input && context.input has namespacePath &&
  context.input.namespacePath == principal.getTag("namespace")
};
```

### 要注意的地方

- **Cedar 不能串接字串，`like` 的樣式也必須是常數。** 所以「namespace 必須等於 `/strategy/x/actor/` + sub + `/`」這種規則寫不出來，**要讓 IdP 直接發一個含有完整 namespace 的 claim**（第二個範例就是這樣做）。
- **actorId 跟 `sub` 不同時**（例如第 1 層加了租戶前綴），要比對自訂的 claim，例如 `principal.getTag("custom:app_user_id")`。**也就是說，第 1 層的 actorId 格式要跟 IdP 的 claim 設計一起規劃。**
- **`has` 的陷阱（官方原文）：** policy 引用了請求沒帶的欄位時，policy 照樣會變成 `ACTIVE`，但請求會被 403 拒絕，「建立時不會回報」。每條 policy 要只針對特定的 action，並用 `context has input && context.input has X` 保護，先用 `LOG_ONLY` 測試。
- **`GetMemoryRecord`、`DeleteMemoryRecord` 的請求裡沒有 actorId**，只有 record ID（和選填的 namespace）。Cedar 沒辦法判斷這筆 record 屬於誰（推論）。**這兩個操作不要開放給一般使用者**，或只允許管理用途的身分。
- **`ListActors` 也不該開放**，理由同第 2 層。

## 第 4 層：防止繞過 Gateway

官方的「只允許經由 Gateway」範例只有一條 Allow：

```json
{"Sid": "AllowOnlyThroughGateway", "Effect": "Allow",
 "Principal": {"AWS": "arn:aws:iam::123456789012:role/CallerRole"},
 "Action": "bedrock-agentcore:*",
 "Resource": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/<memory-id>",
 "Condition": {"ArnEquals": {"aws:SourceArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/<gateway-id>"}}}
```

**這擋不住同帳號的其他 principal：** resource policy 與 identity policy「任一允許即可」，帳號裡已經有 Memory 權限的 role 照樣能直接呼叫。要真正擋住，**必須加一條 Deny**（推論，依官方的評估規則）：

```json
{"Sid": "DenyDirectAccess", "Effect": "Deny", "Principal": "*",
 "Action": "bedrock-agentcore:*",
 "Resource": "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/<memory-id>",
 "Condition": {"ArnNotEquals": {"aws:SourceArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/<gateway-id>"}}}
```

⚠️ 加上這條之後，**連管理用途的直接呼叫（例如刪除使用者資料的批次作業、批次 API）也會被擋**，因為它們本來就不經過 Gateway。要為管理用的 role 加上例外條件，例如 `aws:PrincipalArn`（推論）。

## 缺口怎麼補

### 批次 API

`BatchCreate` / `Update` / `DeleteMemoryRecords` 不經過 Cedar，只能用 IAM 整個允許或拒絕。

- **一般的 agent 用的 role 不給批次權限。**
- 只有 self-managed pipeline 的寫回 Lambda、資料刪除作業這類**受控的後台程序**才給，而且用 `namespace` condition key 限制範圍（`BatchCreate`、`BatchUpdate` 有這個 key；`BatchDelete` 沒有）。

### 跨使用者的 reflection

Episodic 策略的 reflection 可以設在 strategy 層級，也就是**跨所有使用者彙整**。官方原文：「Because reflections can span multiple actors within the same memory resource, consider the privacy implications of cross-actor analysis when retrieving reflections. Consider using guardrails in conjunction with memory or reflecting at the actor level if this is a concern.」

**判斷：** 多租戶的服務一律把 reflection 設在 **actor 層級**（`/strategy/{memoryStrategyId}/actor/{actorId}/`）。如果真的需要「從所有人的經驗學習」，**每個租戶一個 memory resource**，至少不會跨租戶。

### 刪除某個使用者的全部資料（被遺忘權）

| 資料 | 刪除方式 | 限制 |
|---|---|---|
| 短期記憶（event） | `ListSessions` → `ListEvents` → 逐筆 `DeleteEvent` | 每個 actor + session 5 TPS；**刪除 event 不會刪掉從它萃取出來的長期記憶** |
| 長期記憶（record） | 依 actor 的 namespace `ListMemoryRecords` → `BatchDeleteMemoryRecords`（每次最多 100 筆） | **只刪得到 namespace 含 actorId 的 record** |
| Strategy 層級的 reflection / episode | 無法歸屬到個人 | 刪不乾淨 |
| 下游的複本（record streaming） | 收到 `MemoryRecordDeleted` 後刪除 | 刪除事件**只有 record ID**，下游要自己維護「record ID → 使用者」的對照 |
| 自動過期 | `eventExpiryDuration` | 只適用短期記憶 |

- **順序：先刪 event，再刪 record。** 反過來的話，還在進行中的萃取可能在刪除後又產生新的 record（推論，未確認）。保險做法是刪完後等幾分鐘再掃一次。
- **namespace 設計要以「能刪除」為前提：** 每個 strategy 的 namespace 都要含 `{actorId}`。這也是多租戶隔離本來就該有的設計。

## 配額與格式

| 項目 | 值 |
|---|---|
| actorId | 最長 255 字元，**允許 `/` 和 `:`** |
| sessionId | `[a-zA-Z0-9][a-zA-Z0-9-_]*`，最長 100 |
| 自訂 namespace 變數 | 每個 memory 最多 5 個；key 為 `[a-z][a-z0-9]*`、最長 32；值為 `[a-z0-9][a-z0-9-_]*`、最長 64 |
| `allowedValues` / `regexPattern` | 最多 10 個值 / 最長 64 字元；兩者都設時都要符合 |
| `DeleteEvent` | 每個 actor + session 5 TPS（可調整） |
| `BatchDeleteMemoryRecords` | 每次 100 筆 |

## 參考資料

- [IAM service reference：bedrock-agentcore](https://servicereference.us-east-1.amazonaws.com/v1/bedrock-agentcore/bedrock-agentcore.json)、[Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html)
- [Memory organization](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-organization.html)、[Namespaces 與 IAM](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/specify-long-term-memory-organization.html)
- [Memory gateway connector](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-gateway-connector.html)、[FGAC](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-gateway-fgac.html)、[FGAC policy examples](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-gateway-fgac-policy-examples.html)、[Restrict direct access](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-gateway-restrict-access.html)
- [Resource-based policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html)
- [Episodic strategy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/episodic-memory-strategy.html)
- [Delete event](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/short-term-delete-event.html)、[Record streaming](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-record-streaming.html)
