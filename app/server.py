"""Synthetic checkout fixture; standard library only, with no persistent state."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys


RESPONSES = {
    "/healthz": {"status": "ok"},
    "/readyz": {"status": "ready"},
    "/api/checkout": {"status": "ok", "checkout": "synthetic", "total": 42},
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # The base handler logs raw paths and request lines. Keep them private.
        pass

    def respond(self, status, payload):
        body = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        payload = RESPONSES.get(self.path.partition("?")[0])
        if payload is None:
            self.respond(404, {"error": "not_found"})
        else:
            self.respond(200, payload)

    def do_HEAD(self):
        self.do_GET()

    def send_error(self, code, message=None, explain=None):
        # Default error pages can echo arbitrary methods or malformed requests.
        self.close_connection = True
        self.respond(code, {"error": "http_error"})


def main():
    if os.environ.get("CHECKOUT_MODE") != "normal":
        print(json.dumps({
            "level": "error",
            "event": "startup_validation_failed",
            "setting": "CHECKOUT_MODE",
            "message": "CHECKOUT_MODE must be normal",
        }), file=sys.stderr, flush=True)
        return 64

    port = int(os.environ.get("PORT", "8080"))
    with ThreadingHTTPServer(("0.0.0.0", port), Handler) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
