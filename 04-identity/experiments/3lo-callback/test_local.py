"""本機測試：正常流程、授權連結被轉傳給別人、重放、過期、沒登入。"""
import io
import sys

from app import PENDING_TTL, Store, make_app, on_auth_url


class FakeIdentityClient:
    def __init__(self):
        self.calls = []

    def complete_resource_token_auth(self, **kw):
        self.calls.append(kw)


def call(app, session_uri, sid=None):
    env = {"PATH_INFO": "/oauth2/callback", "QUERY_STRING": f"session_id={session_uri}", "wsgi.input": io.BytesIO()}
    if sid:
        env["HTTP_COOKIE"] = f"sid={sid}"
    out = {}
    body = b"".join(app(env, lambda status, headers: out.setdefault("status", status)))
    return out["status"].split()[0], body.decode()


def main():
    store, idc = Store(), FakeIdentityClient()
    app = make_app(store, idc)
    store.login_sessions = {"cookie-alice": "alice", "cookie-mallory": "mallory"}
    pushed = []
    push = lambda user, msg: pushed.append((user, msg))

    U1 = "urn:ietf:params:oauth:request_uri:aaa"
    U2 = "urn:ietf:params:oauth:request_uri:bbb"
    U3 = "urn:ietf:params:oauth:request_uri:ccc"
    on_auth_url(store, "alice", "https://idp.example/authorize?...", U1, push)
    on_auth_url(store, "alice", "https://idp.example/authorize?...", U2, push)
    on_auth_url(store, "alice", "https://idp.example/authorize?...", U3, push)
    store.pending[U3] = ("alice", store.pending[U3][1] - PENDING_TTL - 1)  # 模擬過期

    cases = [
        ("沒登入就打 callback", call(app, U1), "400", 0),
        ("mallory 拿到 alice 的授權連結", call(app, U2, "cookie-mallory"), "403", 0),
        ("alice 正常完成", call(app, U1, "cookie-alice"), "200", 1),
        ("同一個 session_id 重放", call(app, U1, "cookie-alice"), "400", 1),
        ("連結被轉傳後，alice 自己再用也失效（已被消耗）", call(app, U2, "cookie-alice"), "400", 1),
        ("超過 10 分鐘", call(app, U3, "cookie-alice"), "400", 1),
    ]
    ok = True
    for name, (status, body), want, want_calls in cases:
        good = status == want and len(idc.calls) == want_calls
        ok &= good
        print(f"{'✓' if good else '✗'} {name:<36} status={status} complete 呼叫次數={len(idc.calls)} {body}")
    print("推給前端的訊息數：", len(pushed))
    print("CompleteResourceTokenAuth 參數：", idc.calls)
    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
