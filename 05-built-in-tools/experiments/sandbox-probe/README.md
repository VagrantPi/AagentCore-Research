# Code Interpreter 網路模式實測腳本

說明見 [code-interpreter-data-agent.md](../../code-interpreter-data-agent.md#網路模式)。

在 Sandbox、Public、VPC 三種模式的 code interpreter 各執行一次（用 `executeCode` 送入整個檔案內容），比較輸出：

- DNS、HTTPS（PyPI、一般網站、S3、STS）
- 憑證來源（環境變數、MMDS 端點；只檢查存在與否，不印出內容）
- `aws sts get-caller-identity`、`pip download`、磁碟空間、CPU 數、matplotlib 存圖

只用 Python 標準函式庫。撰寫時只在本機（macOS）跑過，確認腳本本身可以執行；**還沒有在 Code Interpreter 裡跑過**，三種模式的實際結果待填。**將由 [WP3](../../../91-work-packages/WP3-sandbox-egress.md) 實跑，結果回填到本檔。**
