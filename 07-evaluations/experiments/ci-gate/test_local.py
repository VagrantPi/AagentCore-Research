"""本機測試：用合成的 span 驗證 code_evaluator，用合成的結果驗證 gate。"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from code_evaluator import lambda_handler

HERE = Path(__file__).parent


def span(**attrs):
    return {"attributes": attrs}


def run_evaluator_cases():
    ok_event = {"schemaVersion": "1.0", "evaluationLevel": "SESSION", "evaluationTarget": None,
                "evaluationInput": {"sessionSpans": [
                    span(**{"gen_ai.tool.name": "OrderTarget___get_order"}),
                    span(**{"gen_ai.completion": "您的訂單已出貨"})]}}
    bad_event = {"schemaVersion": "1.0", "evaluationLevel": "SESSION", "evaluationTarget": None,
                 "evaluationInput": {"sessionSpans": [
                     span(**{"gen_ai.tool.name": "AdminTarget___delete_user"}),
                     {"attributes": {}, "events": [{"attributes": {"gen_ai.choice": {"text": "請聯絡 a.b@example.com 或 0912-345-678"}}}]}]}}
    cases = [
        ("正常 session", ok_event, "PASS"),
        ("違規 session", bad_event, "FAIL"),
        ("格式錯誤", {"evaluationInput": {}}, None),
    ]
    ok = True
    for name, ev, want in cases:
        out = lambda_handler(ev, None)
        got = out.get("label")
        mark = "✓" if got == want else "✗"
        ok &= got == want
        print(f"{mark} evaluator: {name:<10} -> {json.dumps(out, ensure_ascii=False)}")
    return ok


def run_gate_cases():
    thresholds = {"Builtin.Correctness": {"mean": 0.8, "min": 0.5}, "Custom.NoPII": {"min": 1.0}}
    good = [{"scenario": f"s{i}", "evaluator": "Builtin.Correctness", "value": v} for i, v in enumerate([0.9, 0.85, 1.0])]
    good += [{"scenario": f"s{i}", "evaluator": "Custom.NoPII", "value": 1.0} for i in range(3)]
    bad = good[:2] + [{"scenario": "s2", "evaluator": "Builtin.Correctness", "value": 0.3}] + good[3:]
    missing = [r for r in good if r["evaluator"] != "Custom.NoPII"]
    ok = True
    with tempfile.TemporaryDirectory() as d:
        t = Path(d, "t.json"); t.write_text(json.dumps(thresholds))
        for name, data, want in [("全部通過", good, 0), ("有一題很差", bad, 1), ("缺評估器結果", missing, 2)]:
            r = Path(d, "r.json"); r.write_text(json.dumps(data))
            p = subprocess.run([sys.executable, str(HERE / "gate.py"), str(r), str(t)], capture_output=True, text=True)
            mark = "✓" if p.returncode == want else "✗"
            ok &= p.returncode == want
            print(f"{mark} gate: {name:<8} exit={p.returncode}")
            for line in p.stdout.splitlines():
                print("     ", line)
    return ok


if __name__ == "__main__":
    ok = run_evaluator_cases() & run_gate_cases()
    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)
