"""Exercise the demo server through its process and HTTP interfaces."""

import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "app" / "server.py"


def environment(mode=None, port="8080"):
    env = os.environ.copy()
    env.pop("CHECKOUT_MODE", None)
    env["PORT"] = str(port)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if mode is not None:
        env["CHECKOUT_MODE"] = mode
    return env


class StartupTests(unittest.TestCase):
    def test_missing_or_invalid_mode_exits_before_port_validation(self):
        for mode in (None, "", "invalid-demo-mode", "private-sentinel-\nvalue"):
            with self.subTest(mode=mode):
                result = subprocess.run(
                    [sys.executable, "-B", str(SERVER)],
                    env=environment(mode, "not-a-port"),
                    capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(result.returncode, 64, result.stderr)
                self.assertEqual(result.stdout, "")
                lines = result.stderr.splitlines()
                self.assertEqual(len(lines), 1)
                entry = json.loads(lines[0])
                self.assertEqual(entry["level"], "error")
                self.assertEqual(entry["event"], "startup_validation_failed")
                self.assertEqual(entry["setting"], "CHECKOUT_MODE")
                self.assertNotIn("private-sentinel", result.stderr)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.process = subprocess.Popen(
            [sys.executable, "-B", str(SERVER)],
            env=environment("normal", self.port),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.stop_server)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.fail("Healthy server exited before accepting HTTP")
            try:
                self.request("GET", "/healthz")
                return
            except OSError:
                time.sleep(0.02)
        self.fail("Healthy server did not start within five seconds")

    def stop_server(self):
        self.process.terminate()
        stdout, stderr = self.process.communicate(timeout=5)
        self.assertNotIn("private-sentinel", stdout + stderr)

    def request(self, method, path, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_health_readiness_and_fixed_synthetic_checkout(self):
        expected = {
            "/healthz": {"status": "ok"},
            "/readyz": {"status": "ready"},
            "/api/checkout": {"status": "ok", "checkout": "synthetic", "total": 42},
        }
        for path, payload in expected.items():
            with self.subTest(path=path):
                status, headers, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "application/json")
                self.assertEqual(int(headers["Content-Length"]), len(body))
                self.assertEqual(json.loads(body), payload)

    def test_query_does_not_change_response_or_leak_into_logs(self):
        _, _, body = self.request(
            "GET", "/api/checkout?private-sentinel=query",
            {"Authorization": "Bearer private-sentinel-header"},
        )
        self.assertEqual(json.loads(body)["checkout"], "synthetic")
        self.assertNotIn(b"private-sentinel", body)

    def test_unknown_route_returns_fixed_json_404(self):
        status, _, body = self.request("GET", "/private-sentinel-path")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body), {"error": "not_found"})

    def test_head_has_get_status_and_length_without_body(self):
        for path in ("/healthz", "/api/checkout", "/unknown"):
            with self.subTest(path=path):
                get_status, get_headers, _ = self.request("GET", path)
                status, headers, body = self.request("HEAD", path)
                self.assertEqual(status, get_status)
                self.assertEqual(headers["Content-Length"], get_headers["Content-Length"])
                self.assertEqual(body, b"")

    def test_unsupported_method_does_not_echo_or_log_request(self):
        status, _, body = self.request("POST", "/private-sentinel-path")
        self.assertEqual(status, 501)
        self.assertNotIn(b"private-sentinel", body)


if __name__ == "__main__":
    unittest.main()
