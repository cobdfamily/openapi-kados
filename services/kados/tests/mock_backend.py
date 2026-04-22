#!/usr/bin/env python3
"""Minimal OpenAPI-backend mock for the OpenAPIAdapter.

The KADOS container forwards every adapter call to
    POST {OPENAPI_BASE_URL}/protocols/kados/v1/methods/<method>/
with body { "method": "<method>", "data": { ...args } }
and expects  { "data": <value> } in return.

This script exposes that surface on a single port and
returns canned responses keyed by method name. It is
only intended for local testing; it has no persistence,
no rate limiting, and only recognizes the users listed
in VALID_USERS.

Run:
    python3 mock_backend.py            # default :5555
    MOCK_PORT=9000 python3 mock_backend.py

Point compose at it (from include/adapter/):
    OPENAPI_BASE_URL=http://host.docker.internal:5555 \\
        docker compose up -d
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


VALID_USERS = {
    "testuser": "testpass",
}

SESSION_TOKEN = "mock-session-token"


def route(method, data):
    """Return the `data` value that should appear in the
    wrapper `{ "data": ... }` response.
    """
    if method == "authenticate":
        username = data.get("username")
        password = data.get("password")
        ok = VALID_USERS.get(username) == password
        return {
            "authenticated": ok,
            "sessionToken": SESSION_TOKEN if ok else None,
            "user": username if ok else None,
        }
    if method == "startSession":
        return True
    if method == "stopSession":
        return True
    if method == "label":
        return {"text": "Mock label", "lang": "en"}
    if method in ("setProtocolVersion", "logSoapRequestAndResponse"):
        return None
    if method == "announcements":
        return []
    if method == "termsOfServiceAccepted":
        return True
    # Catch-all: return null so PHP decodes to null and the
    # adapter's caller falls back to whatever default makes
    # sense for the method's return contract.
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "KADOSMock/0.1"

    def do_POST(self):
        method_name = self._extract_method()
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = {}
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        result = route(method_name, data)
        body = json.dumps({"data": result}).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _extract_method(self):
        # Path looks like /protocols/kados/v1/methods/<name>/
        parts = [p for p in self.path.split("/") if p]
        if "methods" in parts:
            idx = parts.index("methods")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        return ""

    def log_message(self, fmt, *args):
        sys.stderr.write("[mock] " + (fmt % args) + "\n")


def main():
    port = int(os.environ.get("MOCK_PORT", "5555"))
    host = os.environ.get("MOCK_HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print("Mock OpenAPI backend listening on {}:{}".format(host, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
