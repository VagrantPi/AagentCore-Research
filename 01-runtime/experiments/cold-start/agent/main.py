"""量測用的最小 agent：只依賴標準函式庫，不呼叫任何模型，專門量平台本身的開銷。

回傳的欄位用來判斷冷啟動與 V2 snapshot 行為：
- boot_token / boot_random：在啟動階段產生。V2 從同一份 snapshot 還原時，不同 session 會拿到相同的值
- request_token：在 handler 裡產生，任何情況下都應該不同
- first_request：這個 process 收到的第一個請求才是 true
"""

import json
import os
import random
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOOT_WALL = time.time()
BOOT_TOKEN = os.urandom(8).hex()
BOOT_RANDOM = random.random()
_served = 0


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/ping":
            self._send(200, {"status": "Healthy"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        global _served
        if self.path != "/invocations":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        _served += 1
        self._send(200, {
            "boot_token": BOOT_TOKEN,
            "boot_random": BOOT_RANDOM,
            "request_token": os.urandom(8).hex(),
            "first_request": _served == 1,
            "boot_age_s": round(time.time() - BOOT_WALL, 3),
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
        })

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
