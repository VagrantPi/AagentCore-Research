# 實驗：Runtime 冷啟動與 session 建立速率

> 狀態：**PUBLIC 組合已在東京實跑（2026-10-02，[WP1](../../../91-work-packages/WP1-runtime-session.md)）。** VPC 組、zip 尚未跑。
>
> 本機已驗證的部分：agent 直接執行與 container 執行都正常（arm64、`/ping`、`/invocations`）；`bench.py` 的 deploy / measure / cleanup 流程，以及 MMDSv2 補開的分支，都用 botocore Stubber 對照真實的 service model 測試過。

## 要回答的問題

| # | 問題 | 怎麼量 |
|---|------|--------|
| Q1 | 冷啟動大概多久？V1 和 V2 差多少？ | 用新的 session ID 發出第一個請求的延遲（`cold_ms`），扣掉同一個 session 第二個請求的延遲（`warm_ms`） |
| Q2 | Container 和 direct code（zip）哪個快？ | 同上，比較 `img` 和 `zip` 兩種變體 |
| Q3 | VPC 模式會多花多少時間？ | 比較 `pub` 和 `vpc` 兩種變體 |
| Q4 | Image 大小對 V1 / V2 的影響？ | 比較 `img` 和 `bigimg`（加 1 GB 不可壓縮的填充檔） |
| Q5 | V2 的 snapshot 是否真的讓所有 session 共用啟動階段的狀態？ | 看 `boot_token`（啟動時用 `os.urandom` 產生）在不同 session 之間是否相同：V1 應該每次都不同，V2 預期會重複 |
| Q6 | Container 部署的新 session 建立速率，到底是 1.6/s 還是 25/s？（官方文件互相矛盾） | 執行 `burst`：關掉 SDK 自動重試，並發建立大量新 session，統計成功數、被 throttle 的數量與實際速率 |

**量測的限制：** `cold_ms` 是從呼叫端量到的端對端時間，包含網路來回。建議在**同一個區域**的 EC2 或 CloudShell 上執行，減少網路的干擾。

## 實驗矩陣

平台版本（V1 / V2）× 打包方式（img / zip）× 網路（pub / vpc），再加上 bigimg × pub，最多 10 個變體。沒有提供 `--bucket` 就不建立 zip 變體；沒有提供 `--subnets` 就不建立 vpc 變體。

預設區域是**東京**（`ap-northeast-1`），因為亞太區只有東京支援 V2。

## 事前準備

1. **Execution role**：trust policy 允許 `bedrock-agentcore.amazonaws.com` assume（建議加上 `aws:SourceAccount` 條件），權限至少要有：
   - `ecr:GetAuthorizationToken`、`ecr:BatchGetImage`、`ecr:GetDownloadUrlForLayer`
   - `logs:CreateLogGroup`、`logs:CreateLogStream`、`logs:PutLogEvents`
   - 如果有 zip 變體：放 zip 的那個 bucket 的 `s3:GetObject`
2. **ECR image**（arm64）：

   ```bash
   cd agent
   docker build -t <ecr>/agentcore-coldstart:small .
   docker build --build-arg PAD_MB=1024 -t <ecr>/agentcore-coldstart:big .
   docker push <ecr>/agentcore-coldstart:small && docker push <ecr>/agentcore-coldstart:big
   ```

3. **（可選）VPC**：private subnet 必須在支援的 AZ 裡（東京是 `apne1-az1`、`az2`、`az4`），並且能連到 ECR、S3、CloudWatch Logs，透過 NAT 或 VPC endpoint 都可以。
4. **Python 環境**：`uv venv && uv pip install boto3`

## 執行

```bash
python bench.py build-zip --bucket <bucket>                        # 有 zip 變體才需要
python bench.py deploy --role-arn <role> --image <ecr>:small \
  --big-image <ecr>:big --bucket <bucket> \
  --subnets subnet-a,subnet-b --security-groups sg-x               # 會記錄每個變體等到 READY 花了多久（V2 應該要好幾分鐘）
python bench.py measure --role-arn <role> --trials 20              # 結果會追加到 results.csv
python bench.py burst --variant wp1_cs_v1_img_pub --sessions 60 --concurrency 30
python bench.py burst --variant wp1_cs_v1_zip_pub --sessions 60 --concurrency 30
python bench.py concurrent --variants wp1_cs_v1_img_pub,wp1_cs_v1_img_pub_blk   # 需 deploy --blocking；結果寫入 concurrent.csv
python bench.py prewarm --variants wp1_cs_v1_img_pub,wp1_cs_v2_img_pub         # 結果寫入 prewarm.csv
python bench.py deploy ... --busy --image <ecr>:busy                               # 處理中 /ping 回 HealthyBusy 的對照組
python bench.py concurrent --variants wp1_cs_v1_img_pub_busy --n 1 --sleep 180 --trials 1   # 長請求
python storage.py run --role-arn <role> --image <ecr>:ss --owner <人>            # session storage（#5、#6），結果寫入 storage.csv
python storage.py cleanup                                                         # 先刪 endpoint，再跑 bench.py cleanup
python bench.py cleanup
```

- 每個試驗做完都會呼叫 `StopRuntimeSession`；lifecycle 也壓低到閒置 60 秒、最長 600 秒，避免 session 閒置時繼續計費。
- **MMDSv2：** `CreateAgentRuntime` 的 API 沒有 `metadataConfiguration` 參數（boto3 1.43.105 的 service model 只有 Update 才有）。所以如果第一次呼叫因為 MMDS 相關錯誤被擋下，腳本會自動補一次 `UpdateAgentRuntime`，設定 `requireMMDSV2=true`，然後重試。新建立的 runtime 是否預設就是 MMDSv2，也是這次實驗順便要確認的事。

## 成本估算

以下是自行估算，未經實測：

- 每個試驗的 session 只活幾秒鐘，而且 agent 不呼叫任何模型，所以運算費用用 v1 價格粗估**遠低於 1 美元**。
- 另外會有 ECR 儲存費（約 1.2 GB）、CloudWatch Logs，以及 VPC 變體的 NAT 或 endpoint 費用。
- **做完一定要執行 `cleanup`**，並記得手動刪除 ECR image 和 S3 上的 zip。

## 結果

> 2026-10-02，東京，boto3 1.43.107。呼叫端是台灣的筆電，**不是同區域**，所以 warm 的約 190 ms 大多是網路來回；V1 與 V2 的差距不受影響。原始資料：`results.csv`、`concurrent.csv`、`prewarm.csv`、`burst.csv`、`storage.csv`。

| 變體 | n | cold p50 (ms) | cold p90 (ms) | warm p50 (ms) | 不重複的 boot_token 數 | 等待 READY 的時間 (s) |
|------|---|---------------|---------------|---------------|-----------------------|----------------------|
| wp1_cs_v1_img_pub | 20 | 561 | 673 | 190 | 20/20 | 0.2 |
| wp1_cs_v2_img_pub | 20 | 1898 | 2313 | 217 | 2/20 | 183 |
| wp1_cs_v1_bigimg_pub | 20 | 559 | 616 | 192 | 20/20 | 0.1 |
| wp1_cs_v2_bigimg_pub | 20 | 1861 | 2260 | 191 | 1/20 | 203 |

**V1 的 cold 不是真的冷啟動。** 40 次 V1 試驗都是該 process 的第一個請求，但 `boot_age_s` 的中位數是 36 秒（small）與 97 秒（big）：process 在請求到之前就已經啟動。V1 是從預先開好的實例池（約 15 台）分配 VM，所以 image 大小在這裡看不出影響。池子用光後的真冷啟動見下方 burst：small 約 3.6 s，1 GB 約 17.8 s。

**池子裡的 V2 比 V1 慢約 1.3 秒；池子用光後 V2 反而快很多。** V2 是從 snapshot 還原：`boot_age_s` 約 608 秒（等於建 snapshot 的時間點），同一個 runtime 的 session 幾乎都拿到同一個 `boot_token`（small 20 次裡 19 次、big 20 次全部），證實啟動階段產生的亂數會在不同 session 之間重複。

**MMDSv2：** 新建的 runtime 預設就是 `requireMMDSV2: true`，measure 沒有觸發補開的分支。`GetAgentRuntime` 不回傳 `platformVersion`（V2 也是 `null`），只能從行為判斷版本。

並行測試（`concurrent`，同一個 session 同時送 3 個各睡 20 秒的請求，每個變體 3 次）：

| 變體 | 結果 | 3 個請求的延遲 | 同一台 VM | `/ping` 期間 |
|------|------|---------------|-----------|-------------|
| wp1_cs_v1_img_pub（多執行緒） | 9/9 成功，沒有 409 | 都是 20.2–20.3 s，真的並行 | 是 | 每個請求期間收到 10 次（約 2 秒一次） |
| wp1_cs_v2_img_pub（多執行緒） | 9/9 成功，沒有 409 | 都是 20.2 s | 是 | 10 次 |
| wp1_cs_v1_img_pub_blk（單執行緒） | 9/9 成功 | 20 / 40 / 60 s，被排隊 | 2/3 次是；1 次第 3 個請求花 87 s，落在另一個 boot_token | 0 次（被卡住） |

長請求（同一個 session 送 1 個睡 180 秒的請求；這批 runtime 的閒置逾時是 60 秒，各 1 次）：

| 變體 | `/ping` 回什麼 | 結果 |
|------|---------------|------|
| wp1_cs_v1_img_pub_blk（單執行緒） | 被卡住 | 156.7 s 收到 `RuntimeClientError`，session 被終止 |
| wp1_cs_v1_img_pub（多執行緒） | `Healthy` | 246.8 s 收到 `RuntimeClientError`，session 被終止（前一次也被終止） |
| wp1_cs_v1_img_pub_busy（多執行緒，`PING_BUSY=1`） | 處理中回 `HealthyBusy` | 180.2 s 成功，期間 90 次 `/ping` |

**請求一旦超過閒置逾時，只有 `HealthyBusy` 能保住 session。** `/ping` 沒被卡、照常回 `Healthy` 也一樣會被當成閒置砍掉。正式環境的閒置逾時預設 15 分鐘，所以超過 15 分鐘的請求一定要回 `HealthyBusy`。

預喚醒（`prewarm`，先送 `{}` 不等回應，3 秒後送真正的請求，每個變體 20 次）：

| 變體 | 真正請求 p50 (ms) | p90 (ms) | 預喚醒請求 p50 (ms) |
|------|------------------|----------|---------------------|
| wp1_cs_v1_img_pub | 170 | 198 | 535 |
| wp1_cs_v2_img_pub | 196 | 231 | 1808 |
| wp1_cs_v1_bigimg_pub | 177 | 206 | 590 |
| wp1_cs_v2_bigimg_pub | 191 | 211 | 1772 |

80 次全部落在預喚醒開的同一台 VM，真正請求的延遲等於 warm。

Burst（同時送出 N 個新 session，SDK 不重試；`boot_age_s` 小於 5 秒算真冷啟動，其餘算來自池子；原始資料 `burst.csv`）：

| burst 變體 | 送出 | 成功 | 被 throttle | 實際速率 (/s) | 池子 n / p50 | 真冷啟動 n / p50 / p90 |
|-----------|------|------|-------------|---------------|-------------|------------------------|
| wp1_cs_v1_img_pub | 30 | 30 | 0 | 8.2 | 15 / 745 ms | 15 / 3617 ms / 3658 ms |
| wp1_cs_v1_img_pub | 100 | 100 | 0 | 17.0 | 15 / 722 ms | 85 / 3762 ms / 4177 ms |
| wp1_cs_v1_bigimg_pub | 60 | 60 | 0 | 3.3 | 15 / 1172 ms | 45 / 17828 ms / 17888 ms |
| wp1_cs_v2_img_pub | 30 | 30 | 0 | 12.4 | 30 / 1922 ms | 0 |
| wp1_cs_v2_bigimg_pub | 60 | 60 | 0 | 20.4 | 60 / 2130 ms | 0 |

- 100 個新 session 在約 1 秒內送出，0 次 throttle：1.6/s 的說法不成立；25/s 是持續速率還是上限，這個規模分辨不出來。
- 「實際速率」是成功數除以總耗時，被真冷啟動拖慢，不是平台限流。
- V2 一律從 snapshot 還原，不論並發量或 image 大小都在 2 秒左右。

## 更新版本時 session storage 會不會被清空（WP1 #5、#6）

用 `storage.py` 跑（runtime `wp1_ss_v1_img_pub`，掛 `sessionStorage` 在 `/mnt/ws`，閒置逾時 60 秒；用環境變數 `AGENT_VERSION` 產生新版本）。原始資料 `storage.csv`。

| 測試 | 操作 | 記憶體 | session storage 的檔案 |
|------|------|--------|-----------------------|
| idle | 寫入後 30 秒再呼叫 | 還在 | 還在 |
| idle | 寫入後 90 秒（超過閒置逾時）再呼叫 | 消失（新 VM） | 還在 |
| stop | 寫入 → `StopRuntimeSession` → 再呼叫 | 消失 | 還在 |
| update | 寫入 → 停止 → 更新到 version 2 → 透過 DEFAULT 再呼叫 | 消失 | **清空** |
| pinned | endpoint 固定指向 version 2 → 寫入 → 停止 → 更新到 version 3 → 透過固定 endpoint 再呼叫 | 消失 | **還在**，請求仍跑在 version 2 |

**結論：** 清空與否看「恢復 session 時用的版本」有沒有變，不是看 runtime 有沒有更新。用固定版本的 endpoint 部署，就可以在更新 runtime 時保住使用者的工作區。
