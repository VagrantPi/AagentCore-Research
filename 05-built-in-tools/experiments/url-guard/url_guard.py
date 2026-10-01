"""瀏覽器 agent 的導覽白名單檢查：在 agent 呼叫 page.goto() 或點擊連結之前先檢查目標 URL。

常見的寫錯方式（都會被這裡擋下）：
  - 用 "example.com" in url 判斷 → https://example.com.evil.io、https://evil.io/?r=example.com 都會通過
  - 用 endswith("example.com") → https://evilexample.com 會通過
  - 沒處理 userinfo → https://example.com@evil.io 實際連到 evil.io
  - 沒處理大小寫、結尾的點、國際化網域（punycode）
"""
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"https"}


def normalize_host(host):
    host = (host or "").strip().rstrip(".").lower()
    try:
        return host.encode("idna").decode("ascii")   # 國際化網域轉成 punycode 再比對
    except UnicodeError:
        return None


def is_allowed(url, allowlist):
    """allowlist 範例：{"example.com", "*.example.com"}；"*." 代表所有子網域（不含本身）"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False, "無法解析"
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        return False, f"scheme {parts.scheme!r} 不允許"
    if parts.username is not None or parts.password is not None:
        return False, "URL 含有帳號密碼（userinfo），常被用來偽裝網域"
    host = normalize_host(parts.hostname)
    if not host:
        return False, "主機名稱無效"
    for rule in allowlist:
        rule = rule.lower()
        if rule.startswith("*."):
            base = normalize_host(rule[2:])
            if host.endswith("." + base):
                return True, f"符合 {rule}"
        elif host == normalize_host(rule):
            return True, f"符合 {rule}"
    return False, f"{host} 不在白名單"
