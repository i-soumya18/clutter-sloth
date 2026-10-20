"""A stand-in for Unsloth's OpenAI-compatible server, so the pipeline can be tested without a GPU."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REQUESTS: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._send({"data": [{"id": "mock-vlm"}]})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        msg = body["messages"][0]["content"]
        has_image = isinstance(msg, list)
        text = msg[0]["text"] if has_image else msg
        REQUESTS.append({"text": text, "image": has_image, "auth": self.headers.get("Authorization")})
        low = text.lower()
        # Judge only the file's own extracted text, never the category list in the prompt.
        body_text = low.split("text from the file:", 1)[1] if "text from the file:" in low else ""
        if "invoice" in body_text or "total due" in body_text:
            out = {"category": "Invoices & Receipts", "title": "Acme Corp invoice 1042: cloud hosting"}
        elif has_image:
            out = {"category": "Screenshots", "title": 'Terminal: build error <in> "main.py"'}
        elif "reply with exactly" in low:
            return self._send({"choices": [{"message": {"content": '{"ok": true}'}}]})
        else:
            out = {"category": "Documents", "title": "Weekly team meeting notes"}
        self._send({"choices": [{"message": {"content": "Sure!\n" + json.dumps(out)}}]})


def start(port: int = 0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
