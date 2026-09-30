# Guardrail 門檻校準工具

說明見 [guardrails-calibration.md](../../guardrails-calibration.md#選門檻用成本而不是用直覺)。

```bash
python3 calibrate.py sample.csv --cost-fp 1 --cost-fn 20
```

- 只用 Python 標準函式庫。
- `sample.csv` 是**合成的示範資料**（固定亂數種子產生），不是真實的 guardrail 分數，只用來示範工具怎麼用。
- 真實資料的來源：`LOG_ONLY` 期間 span 裡的分數，join 你自己的請求紀錄後，再做人工標註。
