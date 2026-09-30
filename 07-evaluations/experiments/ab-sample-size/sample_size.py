"""A/B test 的樣本數與實驗天數估算（雙尾檢定，常態近似）。

AgentCore 的 A/B test 以「session」為單位分流，指標來自 online 評估器的分數。
服務端沒有公布檢定方法、最小樣本數、停止規則，所以要自己事先算好再開跑。

用法：
  # 指標是 0/1（例如 GoalSuccessRate 二值化），基準通過率 0.70，想偵測提升到 0.75
  python sample_size.py rate --p0 0.70 --p1 0.75
  # 指標是連續分數，標準差 0.25，想偵測 0.05 的差異
  python sample_size.py mean --sd 0.25 --mde 0.05
  共同參數：--alpha 0.05 --power 0.8 --treatment-share 0.2 --daily-sessions 2000 --sampling 1.0
"""
import argparse
import math
from statistics import NormalDist

Z = NormalDist().inv_cdf


def n_rate(p0, p1, alpha, power):
    za, zb = Z(1 - alpha / 2), Z(power)
    pbar = (p0 + p1) / 2
    num = (za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) ** 2
    return math.ceil(num / (p1 - p0) ** 2)


def n_mean(sd, mde, alpha, power):
    za, zb = Z(1 - alpha / 2), Z(power)
    return math.ceil(2 * (za + zb) ** 2 * sd ** 2 / mde ** 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["rate", "mean"])
    ap.add_argument("--p0", type=float); ap.add_argument("--p1", type=float)
    ap.add_argument("--sd", type=float); ap.add_argument("--mde", type=float)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--power", type=float, default=0.8)
    ap.add_argument("--treatment-share", type=float, default=0.5, help="實驗組流量比例（對照組 = 1 - 這個值）")
    ap.add_argument("--daily-sessions", type=float, default=None)
    ap.add_argument("--sampling", type=float, default=1.0, help="online 評估的抽樣比例")
    a = ap.parse_args()

    n = n_rate(a.p0, a.p1, a.alpha, a.power) if a.kind == "rate" else n_mean(a.sd, a.mde, a.alpha, a.power)
    print(f"每組至少需要 {n} 個「有評分的」session（alpha={a.alpha}, power={a.power}）")
    if a.daily_sessions:
        # 瓶頸在流量較小的那一組
        per_day = a.daily_sessions * a.sampling * min(a.treatment_share, 1 - a.treatment_share)
        days = math.ceil(n / per_day)
        print(f"每天 {a.daily_sessions:.0f} 個 session、評估抽樣 {a.sampling:.0%}、實驗組 {a.treatment_share:.0%}"
              f" → 小組每天 {per_day:.0f} 個 → 約 {days} 天")


if __name__ == "__main__":
    main()
