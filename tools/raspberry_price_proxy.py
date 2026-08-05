#!/usr/bin/env python3
"""Raspberry Pi proxy for the ESP32-S3 OpenEPaperLink price API."""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import gateway


LISTEN_HOST = os.getenv("PRICE_PROXY_LISTEN", "127.0.0.1")
LISTEN_PORT = int(os.getenv("PRICE_PROXY_PORT", "8000"))
PUBLIC_API_TOKEN = os.getenv("PUBLIC_API_TOKEN", "")
ESP_API_TOKEN = os.getenv("ESP_API_TOKEN", "")
ESP_BASE_URL = os.getenv("ESP_BASE_URL", "http://192.168.0.24:8080").rstrip("/")
FORWARD_TIMEOUT = float(os.getenv("ESP_FORWARD_TIMEOUT", "15"))
MAX_BODY_BYTES = int(os.getenv("PRICE_PROXY_MAX_BODY_BYTES", "8192"))


class ProxyError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def require_config() -> None:
    missing = [
        name
        for name, value in (
            ("PUBLIC_API_TOKEN", PUBLIC_API_TOKEN),
            ("ESP_API_TOKEN", ESP_API_TOKEN),
            ("ESP_BASE_URL", ESP_BASE_URL),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required environment: {', '.join(missing)}")
    gateway.require_config()


_sync_lock = threading.Lock()


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise ProxyError(400, "invalid Content-Length") from exc
    if length <= 0:
        raise ProxyError(400, "request body is required")
    if length > MAX_BODY_BYTES:
        raise ProxyError(413, "request body is too large")

    try:
        payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProxyError(400, "request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ProxyError(400, "request body must be a JSON object")
    return payload


def forward_to_esp(path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    body = None
    headers = {"Authorization": f"Bearer {ESP_API_TOKEN}"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"{ESP_BASE_URL}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=FORWARD_TIMEOUT) as response:
            response_body = response.read().decode("utf-8", "replace")
            return response.status, parse_response_body(response_body)
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", "replace")
        return exc.code, parse_response_body(response_body)
    except urllib.error.URLError as exc:
        raise ProxyError(502, f"cannot reach ESP API: {exc.reason}") from exc


def parse_response_body(body: str) -> Any:
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}


class Handler(BaseHTTPRequestHandler):
    server_version = "OEPLPriceProxy/1.0"

    def authenticate(self) -> None:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {PUBLIC_API_TOKEN}"
        if not secrets.compare_digest(supplied, expected):
            raise ProxyError(401, "missing or invalid bearer token")

    def send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        try:
            self.authenticate()
            if self.path != "/health":
                raise ProxyError(404, "endpoint not found")
            esp_status, esp_payload = forward_to_esp("/health")
            self.send_json(
                200 if 200 <= esp_status < 300 else 502,
                {
                    "ok": 200 <= esp_status < 300,
                    "proxy": "price-proxy-v1",
                    "esp_status": esp_status,
                    "esp": esp_payload,
                },
            )
        except ProxyError as exc:
            self.send_json(exc.status, {"ok": False, "error": exc.message})

    def do_POST(self) -> None:
        try:
            self.authenticate()
            if self.path == "/price":
                payload = read_json_body(self)
                esp_status, esp_payload = forward_to_esp("/price", "POST", payload)
                self.send_json(
                    esp_status,
                    {
                        "ok": 200 <= esp_status < 300,
                        "proxy": "price-proxy-v1",
                        "esp_status": esp_status,
                        "esp": esp_payload,
                    },
                )
            elif self.path == "/sync-now":
                if not _sync_lock.acquire(blocking=False):
                    raise ProxyError(409, "sync already in progress")
                try:
                    conn = gateway.connect()
                    try:
                        summary = gateway.sync_once(conn)
                    finally:
                        conn.close()
                finally:
                    _sync_lock.release()
                self.send_json(200, {"ok": True, **summary})
            else:
                raise ProxyError(404, "endpoint not found")
        except ProxyError as exc:
            self.send_json(exc.status, {"ok": False, "error": exc.message})

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"{self.client_address[0]} - {format % args}\n")


def main() -> None:
    require_config()
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"price proxy listening on http://{LISTEN_HOST}:{LISTEN_PORT}")
    print(f"forwarding to {ESP_BASE_URL}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
