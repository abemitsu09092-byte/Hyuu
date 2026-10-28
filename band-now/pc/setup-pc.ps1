# 今やる1つ：PC側の窓口を入れる（PowerShellに貼るだけ）
$d = "$env:USERPROFILE\dev\band-now"
New-Item -ItemType Directory -Force $d | Out-Null
@'
"""今やる1つ をスマホに渡す小さな窓口（PCで常に動かしておく）。

締め切り箱の「今やる1つ.md」の中身を http://<PC>:8765/now.txt で返すだけ。
Tailscale（100.64.0.0/10）とこのPC自身からしか受け付けない。
"""
import ipaddress
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

NOW_FILE = Path(os.environ.get(
    "BAND_NOW_FILE",
    Path.home() / "dev" / "obsidian" / "締め切り箱" / "今やる1つ.md",
))
PORT = int(os.environ.get("BAND_NOW_PORT", "8765"))
ALLOWED = [ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("127.0.0.0/8")]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        ip = ipaddress.ip_address(self.client_address[0])
        if not any(ip in net for net in ALLOWED):
            self.send_error(403)
            return
        if self.path.split("?")[0] != "/now.txt":
            self.send_error(404)
            return
        try:
            body = NOW_FILE.read_text(encoding="utf-8-sig").encode("utf-8")
        except FileNotFoundError:
            body = b""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
'@ | Set-Content -Encoding UTF8 "$d\band_now_server.py"

# 締め切り箱に「今やる1つ.md」が無ければ作る（Jarvisがここを書き換える）
$box = "$env:USERPROFILE\dev\obsidian\締め切り箱"
New-Item -ItemType Directory -Force $box | Out-Null
if (-not (Test-Path "$box\今やる1つ.md")) { "水を一杯飲む" | Set-Content -Encoding UTF8 "$box\今やる1つ.md" }

# PC起動時に自動で動かす（スタートアップに置く）
$pyw = Join-Path (Split-Path (Get-Command python).Source) "pythonw.exe"
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\band-now-server.lnk")
$lnk.TargetPath = $pyw
$lnk.Arguments = "`"$d\band_now_server.py`""
$lnk.Save()

# Tailscaleからだけ通す（管理者の確認が1回出ます）
Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -Command New-NetFirewallRule -DisplayName band-now -Direction Inbound -Protocol TCP -LocalPort 8765 -RemoteAddress 100.64.0.0/10 -Action Allow'

# 今すぐ起動して確かめる
Start-Process $pyw "`"$d\band_now_server.py`""
Start-Sleep 2
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/now.txt).Content
