# A/B test 樣本數與天數估算

說明見 [optimization-loop.md](../../optimization-loop.md#樣本數要自己算)。

```bash
python3 sample_size.py rate --p0 0.70 --p1 0.75 --treatment-share 0.2 --daily-sessions 2000 --sampling 1.0
python3 sample_size.py mean --sd 0.25 --mde 0.05 --daily-sessions 2000
```

雙尾檢定、常態近似；只用 Python 標準函式庫。
