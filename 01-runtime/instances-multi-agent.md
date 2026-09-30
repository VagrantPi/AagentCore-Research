# 延伸：Instances 上的多 agent 協作

> 接續 [01-runtime](README.md#運算型態microvm-vs-instances)。這篇討論：多個 runtime 用同一個 session ID 跑在同一台 EC2 上、共享檔案系統的時候，隔離邊界和權限要怎麼劃分；適合哪些情境；以及跟其他多 agent 模式（包括 00 提到的 Harness「把 agent 當成工具」）有什麼差別。
>
> 資料查核日期：2026-09-30。標示「推論」的部分是官方文件沒有明說、由我根據文件推導出來的。

## 結論先講

- **隔離單位是 session，不是 agent：** 同一個 session 裡的多個 agent **彼此之間沒有安全邊界**。官方原文是「neither provides a security boundary」，所以**只能放互相信任的 agent**。
- **權限實際上會疊加（推論）：** 每個 agent 雖然有自己的 execution role，但「機器上的任何程式都能讀到它可取得的憑證」，而 agent 之間又沒有隔離。所以同一台機器上的有效權限，應該視為**所有 agent 權限的聯集**。
- **最適合的情境：** 互相信任的一組 agent（例如規劃、實作、測試），一起處理一份大型工作區或跑很久的任務；或是需要 GPU。
- **成本模型完全不同：** 從 EC2 開機到關機都計費，**閒置也照算**。EBS 在 session 停止後也會持續計費，直到 session 被刪除為止。

## 運作方式

```
Capacity provider（機器樣板：機型、VPC、EBS volume）
      │
      ├── Runtime A（planner，role A）┐
      ├── Runtime B（coder，  role B）├── 用同一個 runtimeSessionId 呼叫
      └── Runtime C（tester， role C）┘
                    │
                    ▼
      Session = 一台 EC2（對應關係：capacity provider + session ID → 1 台機器）
      ├── agent A、B、C 以 container 或 process 的形式並存
      └── /mnt/ws ← 共享的 EBS volume（每個 runtime 都要在自己的設定裡掛上同一個 volumeName）
```

- **怎麼讓多個 agent 落在同一台機器：** 多個 runtime 綁定**同一個 capacity provider**，然後用**同一個 session ID** 各自呼叫。第一次呼叫會開一台 EC2，之後的呼叫就在同一台機器上啟動其他 agent。
- **同一個 session ID，但不同的 capacity provider，會是不同的 session、不同的機器。**
- **共享 volume 不是自動的：** 每個 runtime 都要在自己的 `filesystemConfigurations` 裡掛上同一個 `volumeName`。但官方也特別提醒，**「沒有掛載」並不代表隔離**，隔離的邊界仍然是 session。
- **每個 session 最多 20 個 agent**（這是配額，無法調整）。
- **Session 停止時：** EC2 會被終止，但 volume 會保留。之後用同一個 session ID 再呼叫，會開一台新的機器並重新掛上原本的 volume，而且新機器可能已經套用了最新的系統修補。

### Agent 之間怎麼溝通

官方文件描述的只有**共享檔案系統**。其他方式文件沒有提到，以下是推論：

- **檔案：** 例如約定目錄結構，或用 `tasks/`、`results/` 目錄做交接，這是官方唯一明確提到的方式。
- **localhost 網路：** 同一台機器上的 agent 之間能不能直接互連，文件沒有說明，需要實測。
- **由呼叫端編排：** 最穩的做法是讓後端依序呼叫 A → B → C，用檔案交接結果（判斷）。
- **Agent 自己呼叫其他 runtime：** 讓 agent A 用同一個 session ID 呼叫 runtime B，理論上可行，但需要給 A 的 role 呼叫 B 的權限，文件沒有提到這種用法。

## 安全模型

| 層級 | 誰負責隔離 | 說明 |
|------|-----------|------|
| 不同客戶之間 | AWS | EC2 跑在你自己的帳號裡 |
| 不同 session 之間 | AWS（每個 session 一台 EC2） | **這才是隔離單位** |
| **同一個 session 裡的不同 agent** | **沒有人** | Container 或 process 都不構成安全邊界，必須互相信任 |
| Session 屬於哪個使用者 | **你** | 平台只檢查 session ID 的格式，**不驗證它是不是屬於呼叫者** |

### 多租戶部署的建議（官方）

1. **後端綁定 session 和使用者：** session ID 應該由後端根據已驗證的使用者產生，**絕對不要直接接受前端傳來的值**。
2. **高安全需求的場景，讓每個使用者或租戶用不同的 IAM principal 呼叫：** 這樣 IAM 本身就能限制 session 的範圍。官方稱這是「最強的控制手段」。
3. **用 CloudTrail 偵測跨 principal 的存取：** 同一筆事件裡會同時記錄呼叫者和 `sessionId`，可以用來找出「某個 principal 存取了別人建立的 session」這類異常。
4. **信任等級不同的 agent 不要放在同一個 session。**

### 權限的注意事項

- **Infrastructure role：** AgentCore 用這個 role 在你的帳號裡開關 EC2。它的權限很大，官方建議用 IAM 條件限制在特定的 VPC、subnet 和機型。
- **SCP 管不到清理用的 service-linked role：** 你的組織 SCP 會套用在 AgentCore 的操作上，**唯一的例外**是用來刪除、清理資源的 service-linked role。
- **Instance profile** 只用來收集系統 log，**不會**授權給你的 agent 程式。

## 適合與不適合的情境

| 適合 | 不適合 |
|------|--------|
| 互相信任的 agent 一起處理一份大型工作區（例如大型 monorepo 的重構：規劃、實作、測試分工） | 需要互相隔離的多租戶 agent 放在同一個 session |
| 超過 8 小時的長時間任務（例如資料遷移、批次轉換，最長 14 天） | 很短的 API 互動（用 microVM 比較快、比較便宜） |
| 需要 GPU（推論、渲染），又想讓 agent 直接使用 | 流量忽高忽低、大部分時間閒置（Instances 閒置也計費） |
| 資料必須留在自己帳號和 VPC 裡的法遵需求 | 需要 PUBLIC 網路模式（Instances 只能用 VPC） |
| 已經有 Savings Plans 或 RI 想用上 | 需要 CloudFormation 等 IaC 一次建好全部資源（capacity provider 建立後只能改描述） |

## 多 agent 模式比較（範圍限 00–01）

|  | Instances 同 session 共居 | microVM + 共享 EFS / S3 Files | A2A 協定（runtime 互相呼叫） | Harness：agent 當工具 |
|--|--------------------------|------------------------------|------------------------------|----------------------|
| Agent 之間的隔離 | ❌ 沒有 | ✅ 各自有 microVM，但**共用的檔案系統彼此看得到** | ✅ 各自有 microVM | ✅ 各自有 microVM |
| 共享狀態的方式 | 本機磁碟（EBS） | NFS 共享目錄 | 只能透過訊息傳遞 | 只能透過工具的輸入輸出 |
| 通訊延遲 | 最低，本機檔案 | 中等，NFS | 較高，網路 RPC，還可能遇到冷啟動 | 較高，同 A2A |
| 最長執行時間 | 14 天 | 8 小時 | 8 小時 | 8 小時 |
| 計費方式 | EC2 開機時間 + 12% | 依用量計費 + EFS 費用 | 依用量計費 | 依用量計費 |
| 需要 VPC | 需要 | 需要 | 不一定 | 不一定 |
| 複雜度 | 中：要管 capacity provider 和機型 | 中：要管 VPC 和 mount target | 中：要實作 A2A server | 低：寫設定即可 |
| 適合 | 高度協作的大型工作區、GPU | 需要共享資料、又希望運算彼此隔離 | 鬆散耦合、跨團隊的 agent 服務 | 簡單的「主管 + 專家」分工 |

**判斷：** 大多數多 agent 的需求，**先考慮 A2A 或 agent-as-tool**，因為它們的隔離最好。只有在「agent 之間需要頻繁交換大量檔案」或「需要 GPU 或超過 8 小時」時，才值得付出 Instances 的維運和閒置成本。

## 成本與限制

- **計費：** EC2 的 On-Demand 價格 + 12% 管理費（GPU 機型 7.8%），從開機算到關機，**最少約 1 分鐘**，跟實際使用量無關。
- **EBS：** session 停止後 volume 仍然保留，會持續計費，**要刪除 session 才會停止**。
- **你帳號的 EC2 配額也會被用到：** 包括執行中的機器數量、EBS、ENI、Auto Scaling 的 API 速率等等。量大的話要另外申請提高。
- **第一次呼叫比較慢：** 要先開一台 EC2。
- **設定建立後就不能改：** capacity provider 除了描述之外都不能改；runtime 的運算型態也不能改。
- **可用區域：** us-east-1、us-east-2、us-west-2、法蘭克福、愛爾蘭、孟買、新加坡、雪梨、東京。

## 參考資料

- [Instances：How it works](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-how-it-works.html)
- [Security model and permissions for Runtime Instances](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-security.html)
- [File system configurations：Capacity provider volumes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html)
- [Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)
- [AgentCore pricing：Runtime Instances](https://aws.amazon.com/bedrock/agentcore/pricing/)
- [Supported AWS Regions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html)
