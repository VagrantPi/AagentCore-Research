"""Memory 的月費與檢索速率估算。

計費依官方定價頁（2026-10）：
  短期記憶  $0.25 / 1,000 次 CreateEvent（一次呼叫算一個 event，不論帶幾則訊息）
  長期儲存  $0.75 / 1,000 筆 record / 月（built-in）；$0.25（override 或 self-managed，模型費另計）
  長期檢索  $0.50 / 1,000 次 RetrieveMemoryRecords
寫入次數依 Strands AgentCoreMemorySessionManager 的實測行為（bedrock-agentcore 1.24.0）：
  batch_size=1：每則訊息一次 CreateEvent；一般回合 2 次；每多一次工具呼叫多 2 次（toolUse + toolResult），
                有工具呼叫或狀態變動的回合另加 1 次 agent state
  batch_size>1：每次 invocation 約 2 次（訊息一批 + 狀態一批）
檢索：每個「使用者文字回合」對每個 namespace 各一次
"""
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mau", type=int, default=10000, help="每月活躍使用者")
    ap.add_argument("--sessions", type=float, default=8, help="每人每月 session 數")
    ap.add_argument("--turns", type=float, default=6, help="每個 session 的使用者回合數")
    ap.add_argument("--tool-calls", type=float, default=1, help="每回合平均工具呼叫次數")
    ap.add_argument("--namespaces", type=int, default=2, help="每回合檢索的 namespace 數（0 = 不自動檢索）")
    ap.add_argument("--batch", action="store_true", help="開啟 batch_size>1")
    ap.add_argument("--records-per-user", type=float, default=30, help="每個使用者累積的長期 record 數")
    ap.add_argument("--storage-rate", type=float, default=0.75, help="0.75 built-in；0.25 override/self-managed")
    ap.add_argument("--peak-factor", type=float, default=5, help="尖峰流量 / 平均流量")
    a = ap.parse_args()

    turns = a.mau * a.sessions * a.turns
    if a.batch:
        per_turn = 2
    else:
        per_turn = 2 + 2 * a.tool_calls + (1 if a.tool_calls > 0 else 0)
    events = turns * per_turn + a.mau * a.sessions * 2      # 新 session 另有 SESSION + AGENT 兩個 blob
    retrievals = turns * a.namespaces
    records = a.mau * a.records_per_user

    stm, ltm, ret = events / 1000 * 0.25, records / 1000 * a.storage_rate, retrievals / 1000 * 0.50
    avg_tps = retrievals / (30 * 86400)
    print(f"使用者回合：{turns:,.0f}／月；每回合 CreateEvent {per_turn:g} 次")
    print(f"短期記憶  {events:>14,.0f} events      ${stm:>10,.2f}")
    print(f"長期儲存  {records:>14,.0f} records     ${ltm:>10,.2f}")
    print(f"長期檢索  {retrievals:>14,.0f} retrievals  ${ret:>10,.2f}")
    print(f"合計                                ${stm + ltm + ret:>10,.2f}／月（不含 override 的模型費）")
    print(f"檢索速率：平均 {avg_tps:.2f} TPS、尖峰約 {avg_tps * a.peak_factor:.2f} TPS（預設配額 30 TPS，整個帳號共用）")


if __name__ == "__main__":
    main()
