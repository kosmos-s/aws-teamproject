"""One-use, loopback-only redirect; never print the Orca pairing credential."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

pairing = json.loads((Path(__file__).resolve().parents[1] / ".local" / "pairing.json").read_text(encoding="utf-8"))
target = pairing["result"]["webClientUrl"]
if not target.startswith("http://127.0.0.1:6768/") or "\r" in target or "\n" in target:
    raise ValueError("Only the local, forwarded Orca URL is permitted")


class Redirect(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/connect":
            self.send_error(404)
            return
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.server.connected = True

    def log_message(self, *_):
        pass


server = HTTPServer(("127.0.0.1", 6770), Redirect)
server.timeout = 180
server.connected = False
print("One-use local pairing redirect ready.", flush=True)
while not server.connected:
    server.handle_request()
server.server_close()
