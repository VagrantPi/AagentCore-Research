# 實驗：Runtime 冷啟動與 session 建立速率

> 狀態：**實驗工具已完成，尚未在 AWS 上實跑。** 撰寫時的環境沒有 AWS 憑證，下方的結果表是空的，跑完後再補上。
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
python bench.py burst --variant cs_v1_img_pub --sessions 60 --concurrency 30
python bench.py burst --variant cs_v1_zip_pub --sessions 60 --concurrency 30
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

> 待實測後補上。

| 變體 | n | cold p50 (ms) | cold p90 (ms) | warm p50 (ms) | 不重複的 boot_token 數 | 等待 READY 的時間 (s) |
|------|---|---------------|---------------|---------------|-----------------------|----------------------|
| cs_v1_img_pub | | | | | | |
| cs_v2_img_pub | | | | | | |
| … | | | | | | |

| burst 變體 | 送出 | 成功 | 被 throttle | 實際速率 (/s) |
|-----------|------|------|-------------|---------------|
| cs_v1_img_pub | | | | |
| cs_v1_zip_pub | | | | |

## 可以順便驗證的：更新版本時 session storage 會不會被清空

這題與 [coding agent 架構](../../coding-agent-architecture.md)相關。官方文件寫「更新 runtime 版本時，session storage 會被清空」，但**沒有說明「prod endpoint 仍然指向舊版本」的情況會怎麼樣**。

驗證方式：手動替其中一個變體加上 `filesystemConfigurations=[{"sessionStorage": {"mountPath": "/mnt/ws"}}]`，建立一個固定指向 V1 的 endpoint，寫入檔案，然後更新 runtime（產生 V2），再透過固定的那個 endpoint 恢復原本的 session，看檔案還在不在。這需要改寫 agent，讓它能讀寫檔案，目前不在 `bench.py` 的範圍內。
