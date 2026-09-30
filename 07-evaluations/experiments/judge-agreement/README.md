# LLM 評審與人工標註的一致性分析

說明見 [judge-calibration.md](../../judge-calibration.md#校準流程)。

```bash
python3 agreement.py sample.csv
```

- 輸入欄位：`session_id, human, <評審1>, <評審2>, ..., response_chars`，判定值為 0/1。
- `sample.csv` 是**合成資料**（固定亂數種子），刻意設計成「內建評審偏寬鬆、偏好長回覆」，只用來示範工具怎麼用。
