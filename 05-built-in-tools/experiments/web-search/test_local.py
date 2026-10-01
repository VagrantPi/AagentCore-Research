import subprocess
import sys

from citations import render

RESULTS = [
    {"text": "...", "url": "https://example.com/a", "title": "A 公司財報", "publishedDate": "2026-09-01"},
    {"text": "...", "title": "沒有 URL 的知識圖譜結果"},
]
ok = True
for name, answer, want_problems in [
    ("正常引用", "營收成長 12% [1]。", 0),
    ("引用沒有 URL 的結果", "營收成長 12% [1]，成立於 1999 年 [2]。", 1),
    ("引用不存在的編號", "營收成長 12% [3]。", 1),
    ("沒有標註來源", "營收成長 12%。", 1),
]:
    out, problems = render(answer, RESULTS)
    good = len(problems) == want_problems
    ok &= good
    print(f"{'✓' if good else '✗'} {name:<12} problems={problems}")
    if name == "正常引用":
        print("   " + out.replace("\n", "\n   "))
print()
for args in ["", "--cache-hit 0.3", "--search-rate 0.2 --queries 1.5"]:
    print("cost.py", args or "(預設)")
    subprocess.run([sys.executable, "cost.py", *args.split()], check=True)
print("\nALL PASS" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)
