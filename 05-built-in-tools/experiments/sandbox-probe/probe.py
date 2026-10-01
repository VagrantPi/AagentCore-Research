"""在 Code Interpreter 的 session 裡執行，實測 Sandbox / Public / VPC 三種網路模式的實際行為。

用法：把這個檔案的內容當成 executeCode 的程式碼送進去（或 writeFiles 後用 executeCommand 執行），
      在三種網路模式的 code interpreter 各跑一次，比較輸出。
只用 Python 標準函式庫；每項測試 5 秒逾時，失敗只記錄、不中斷。
"""
import json
import os
import socket
import ssl
import subprocess
import urllib.request

TIMEOUT = 5


def try_dns(host):
    try:
        return "ok " + socket.gethostbyname(host)
    except Exception as e:
        return f"fail {type(e).__name__}"


def try_https(url):
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT, context=ssl.create_default_context()) as r:
            return f"ok {r.status}"
    except urllib.error.HTTPError as e:   # 拿到 HTTP 錯誤碼也代表網路通
        return f"ok(http {e.code})"
    except Exception as e:
        return f"fail {type(e).__name__}"


def try_cmd(cmd):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return ("ok " if p.returncode == 0 else f"fail rc={p.returncode} ") + (p.stdout or p.stderr).strip()[:120]
    except Exception as e:
        return f"fail {type(e).__name__}"


def main():
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    results = {
        "dns: pypi.org": try_dns("pypi.org"),
        f"dns: s3.{region}.amazonaws.com": try_dns(f"s3.{region}.amazonaws.com"),
        "https: pypi.org": try_https("https://pypi.org/simple/"),
        "https: example.com": try_https("https://example.com/"),
        f"https: s3.{region}": try_https(f"https://s3.{region}.amazonaws.com/"),
        f"https: sts.{region}": try_https(f"https://sts.{region}.amazonaws.com/"),
        # 憑證從哪裡來：環境變數？metadata 端點？（只檢查是否存在，不印出內容）
        "env: AWS_ACCESS_KEY_ID set": str(bool(os.environ.get("AWS_ACCESS_KEY_ID"))),
        "env: AWS_CONTAINER_CREDENTIALS_FULL_URI set": str(bool(os.environ.get("AWS_CONTAINER_CREDENTIALS_FULL_URI"))),
        # 官方說明：execution role 的憑證透過 MMDS（同 EC2 的 169.254.169.254）提供，沙箱裡的任何程式都讀得到
        "http: 169.254.169.254 (MMDS)": try_https("http://169.254.169.254/latest/meta-data/"),
        "cmd: aws sts get-caller-identity": try_cmd("aws sts get-caller-identity --query Arn --output text"),
        "cmd: pip download (不安裝)": try_cmd("pip download --disable-pip-version-check --no-deps -d /tmp/p six -q"),
        "disk: / free (GB)": try_cmd("df -k / | tail -1 | awk '{printf \"%.1f\", $4/1048576}'"),
        "cpu count": str(os.cpu_count()),
        "matplotlib savefig": try_cmd("python3 -c \"import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as p; p.plot([1,2]); p.savefig('/tmp/probe.png'); print('saved')\""),
    }
    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
