#!/usr/bin/env python3
"""HTML 文件驗證：tag stack、bytes、cards、可見字元、中文字數、中英空格、簡體字。"""
import re
import sys
from html.parser import HTMLParser

VOID = {"meta", "link", "br", "hr", "img", "input"}
CJK = re.compile(r"[\u4e00-\u9fff]")
SIMP = re.compile(r"[个们这来对时会说学国东车马门问题见风长书]")
BOUNDARY = re.compile(r"[\u4e00-\u9fff][A-Za-z0-9]|[A-Za-z0-9][\u4e00-\u9fff]")


class Stack(HTMLParser):
    def __init__(self):
        super().__init__()
        self.open, self.err = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.open.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.open and self.open[-1] == tag:
            self.open.pop()
        elif tag in self.open:
            while self.open and self.open[-1] != tag:
                self.err.append("unclosed: " + self.open.pop())
            if self.open:
                self.open.pop()
        else:
            self.err.append("stray close: " + tag)


def check(path):
    src = open(path, encoding="utf-8").read()
    p = Stack()
    p.feed(src)
    body = src.split("</style>", 1)[1]
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", body)).strip()

    gaps = set()
    flat = re.sub(r"<[^>]+>", " ", body)
    for m in BOUNDARY.finditer(flat):
        gaps.add(flat[max(0, m.start() - 14):m.start() + 16].replace("\n", " "))
    simp = sorted(set(SIMP.findall(txt)))

    ok = not (p.open or p.err or simp)
    name = path.rsplit("/", 1)[-1]
    print(
        f"{name:38} stack:{p.open or '[]'} err:{p.err or 'none'} "
        f"bytes:{len(src.encode())} cards:{body.count(chr(34) + 'card')} "
        f"visible:{len(txt)} CJK:{len(CJK.findall(txt))} "
        f"nospace:{len(gaps)} simp:{simp} [{'ok' if ok else 'BAD'}]"
    )
    for g in sorted(gaps):
        print("    ..." + g + "...")
    return ok


if __name__ == "__main__":
    paths = sys.argv[1:] or sorted(
        __import__("glob").glob("doc/*.html")
    )
    sys.exit(0 if all(check(x) for x in paths) else 1)