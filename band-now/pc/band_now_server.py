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
