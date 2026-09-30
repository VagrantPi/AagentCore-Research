"""3LO callback 端點的參考實作（只用標準函式庫的 WSGI）。

重點是 session binding 的三個檢查：
  1. 授權 URL 是「發給誰」的：Agent 端拿到 authorizationUrl 與 sessionUri 時，
     記下 sessionUri → 發起的使用者（pending 表，10 分鐘過期，跟 AgentCore 的有效期一致）
  2. 回來的是誰：callback 只從「瀏覽器自己的登入 session（cookie）」取得使用者，
     不從任何遠端快取或 query string 取得（官方明確要求）
  3. 兩者一致才呼叫 CompleteResourceTokenAuth；不一致就什麼都不做並記錄

AgentCore 會把瀏覽器導回 allowedResourceOauth2ReturnUrls 裡的 URL，帶上 ?session_id=<sessionUri>。
真實環境把 FakeIdentityClient 換成 boto3.client("bedrock-agentcore")。
"""
import json
import time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

PENDING_TTL = 600  # 秒；AgentCore 的授權 URL 與 session 有效期為 10 分鐘


class Store:
    """示範用的記憶體儲存。正式環境請換成有 TTL 的共享儲存（例如 DynamoDB、Redis）。"""

    def __init__(self):
        self.login_sessions = {}  # cookie sid -> user_id（你的應用程式自己的登入狀態）
        self.pending = {}         # sessionUri -> (user_id, issued_at)
        self.audit = []

    def remember_pending(self, session_uri, user_id, now=None):
        self.pending[session_uri] = (user_id, now or time.time())

    def pop_pending(self, session_uri, now=None):
        item = self.pending.pop(session_uri, None)  # 用一次就刪：防止重放
        if not item:
            return None
        user_id, issued = item
        if (now or time.time()) - issued > PENDING_TTL:
            return None
        return user_id


def on_auth_url(store, user_id, authorization_url, session_uri, push):
    """Agent 端拿到 authorizationUrl 時呼叫：記下發起者，再把 URL 推給前端（串流、WebSocket 或輪詢）。"""
    store.remember_pending(session_uri, user_id)
    push(user_id, {"type": "authorization_required", "authorization_url": authorization_url})


def make_app(store, identity_client):
    def app(environ, start_response):
        if environ.get("PATH_INFO") != "/oauth2/callback":
            start_response("404 Not Found", [("Content-Type", "text/plain")])
            return [b"not found"]

        qs = parse_qs(environ.get("QUERY_STRING", ""))
        session_uri = (qs.get("session_id") or [None])[0]
        cookie = SimpleCookie(environ.get("HTTP_COOKIE", ""))
        sid = cookie["sid"].value if "sid" in cookie else None
        browser_user = store.login_sessions.get(sid)      # 檢查 2：只信任瀏覽器自己的登入狀態

        def done(status, msg, event):
            store.audit.append({"event": event, "session_uri": session_uri, "browser_user": browser_user})
            start_response(status, [("Content-Type", "application/json; charset=utf-8")])
            return [json.dumps({"message": msg}, ensure_ascii=False).encode()]

        if not session_uri or not browser_user:
            return done("400 Bad Request", "請先登入後再完成授權", "rejected_no_login")

        initiator = store.pop_pending(session_uri)       # 檢查 1：這個授權是發給誰的
        if initiator is None:
            return done("400 Bad Request", "授權連結已失效，請回到對話重新開始", "rejected_unknown_or_expired")
        if initiator != browser_user:                    # 檢查 3：不一致就不完成
            return done("403 Forbidden", "這個授權連結不是發給目前登入的帳號", "rejected_user_mismatch")

        identity_client.complete_resource_token_auth(
            sessionUri=session_uri, userIdentifier={"userId": browser_user})
        return done("200 OK", "授權完成，可以回到對話了", "completed")

    return app
