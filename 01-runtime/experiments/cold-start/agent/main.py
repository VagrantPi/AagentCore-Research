"""量測用的最小 agent：只依賴標準函式庫，不呼叫任何模型，專門量平台本身的開銷。

回傳的欄位用來判斷冷啟動與 V2 snapshot 行為：
- boot_token / boot_random：在啟動階段產生。V2 從同一份 snapshot 還原時，不同 session 會拿到相同的值
- request_token：在 handler 裡產生，任何情況下都應該不同
- first_request：這個 process 收到的第一個請求才是 true

並行測試（WP1 #8）用的欄位：
- payload 帶 `sleep` 秒數時，handler 會睡這麼久，模擬一個長請求
- inflight_at_start：這個請求開始時，同一個 process 裡有幾個請求正在處理（含自己）
- pings_during：這個請求處理期間收到幾次 /ping；0 代表 /ping 被卡住
- 環境變數 AGENT_MODE=blocking 時改用單執行緒 server，一次只能處理一個請求（對照組）
- 環境變數 PING_BUSY=1 時，有請求在處理就讓 /ping 回 HealthyBusy

Session storage 測試（WP1 #5、#6）用的欄位：
- payload 帶 `put` 時，把值存進記憶體，也寫到 SESSION_DIR/marker
- 每次都回傳 mem（記憶體裡的值）與 disk（marker 檔內容），沒有就是 null
- version：環境變數 AGENT_VERSION，用來分辨請求落在哪個 runtime 版本
"""

import json
import os
import random
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

BOOT_WALL = time.time()
BOOT_TOKEN = os.urandom(8).hex()
BOOT_RANDOM = random.random()
MODE = os.environ.get("AGENT_MODE", "threaded")
MARKER = os.path.join(os.environ.get("SESSION_DIR", "/mnt/ws"), "marker")
_lock = threading.Lock()
_mem = None
_served = 0
_pings = 0
_inflight = 0


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        global _pings
        if self.path == "/ping":
            with _lock:
                _pings += 1
                busy = _inflight > 0 and os.environ.get("PING_BUSY") == "1"
            self._send(200, {"status": "HealthyBusy" if busy else "Healthy"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        global _served, _inflight, _mem
        if self.path != "/invocations":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            payload = {}
        with _lock:
            _served += 1
            _inflight += 1
            first, inflight, pings0 = _served == 1, _inflight, _pings
        t0 = time.time()
        disk_error = None
        if "put" in payload:
            _mem = payload["put"]
            try:
                with open(MARKER, "w") as f:
                    f.write(str(payload["put"]))
            except OSError as e:
                disk_error = str(e)
        try:
            with open(MARKER) as f:
                disk = f.read()
        except OSError:
            disk = None
        time.sleep(float(payload.get("sleep", 0)))
        with _lock:
            _inflight -= 1
            pings_during = _pings - pings0
        self._send(200, {
            "boot_token": BOOT_TOKEN,
            "boot_random": BOOT_RANDOM,
            "request_token": os.urandom(8).hex(),
            "first_request": first,
            "boot_age_s": round(t0 - BOOT_WALL, 3),
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "mode": MODE,
            "inflight_at_start": inflight,
            "pings_during": pings_during,
            "handler_s": round(time.time() - t0, 3),
            "version": os.environ.get("AGENT_VERSION"),
            "mem": _mem,
            "disk": disk,
            "disk_error": disk_error,
        })

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer if MODE == "blocking" else ThreadingHTTPServer
    server(("0.0.0.0", 8080), Handler).serve_forever()
