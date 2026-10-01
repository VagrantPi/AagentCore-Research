import sys

from url_guard import is_allowed

ALLOW = {"example.com", "*.example.com", "intranet.corp.local"}
CASES = [
    ("https://example.com/orders", True),
    ("https://shop.example.com/cart", True),
    ("https://EXAMPLE.COM./x", True),                    # 大小寫、結尾的點
    ("https://example.com.evil.io/login", False),        # 字串包含
    ("https://evilexample.com/", False),                 # endswith
    ("https://evil.io/?next=https://example.com", False),# 出現在 query
    ("https://example.com@evil.io/", False),             # userinfo
    ("http://example.com/", False),                      # 非 https
    ("javascript:alert(1)", False),
    ("file:///etc/passwd", False),
    ("https://exаmple.com/", False),                     # 西里爾字母 а（同形異義字）
    ("https://intranet.corp.local/report", True),
]


def main():
    ok = True
    for url, want in CASES:
        got, why = is_allowed(url, ALLOW)
        good = got == want
        ok &= good
        print(f"{'✓' if good else '✗'} {'允許' if got else '拒絕'} {url:<45} {why}")
    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
