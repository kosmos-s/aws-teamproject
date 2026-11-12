"""Orca-owner service: one fixed operation over a protected UNIX socket."""
import base64
import json
import os
import sys
import socketserver
import subprocess
from pathlib import Path
from urllib.parse import urlparse, parse_qs


class PairHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        if self.rfile.readline(16) != b"PAIR\n":
            return
        try:
            node = next(Path("/home/orca/.config/orca/orcad-artifacts/linux-x64-glibc/runtimes").glob("node-*/bin/node"))
            result = subprocess.run([str(node), "/opt/Orca/resources/app.asar.unpacked/out/cli/index.js", "pair", "--address", "127.0.0.1", "--json"],
                                    stdin=subprocess.DEVNULL, capture_output=True, timeout=20, check=True)
            output = json.loads(result.stdout)["result"]
            web = output["webClientUrl"]
            code = parse_qs(urlparse(web).fragment)["pairing"][0]
            if code.startswith("orca://"):
                code = parse_qs(urlparse(code).query)["code"][0]
            offer = json.loads(base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)))
            self.wfile.write(json.dumps(offer).encode())
        except Exception as error:
            print("Pair broker failure type:", type(error).__name__, file=sys.stderr, flush=True)
            if isinstance(error, subprocess.CalledProcessError):
                try:
                    failed = json.loads(error.stdout)
                    detail = failed.get("error", {})
                    print("Pair broker native error code:", detail.get("code") if isinstance(detail, dict) else "unstructured", file=sys.stderr, flush=True)
                except Exception:
                    text = error.stderr.decode(errors="replace")
                    print("Pair broker process status:", error.returncode, "sandbox_failure=", any(s in text.lower() for s in ["sandbox", "namespace", "no_new_privs"]), file=sys.stderr, flush=True)
            self.wfile.write(b'{"error":"Pairing unavailable"}')


def main():
    path = Path("/run/kosmos-orca-broker/pair.sock")
    path.unlink(missing_ok=True)
    with socketserver.UnixStreamServer(str(path), PairHandler) as server:
        os.chmod(path, 0o660)
        server.serve_forever()


if __name__ == "__main__":
    main()
