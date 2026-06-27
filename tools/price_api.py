#!/usr/bin/env python3
"""Small REST API for sending product prices to OpenEPaperLink tags."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


DEFAULT_AP_URL = "http://192.168.0.24"
DEFAULT_LISTEN = "127.0.0.1"
DEFAULT_PORT = 8080


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def ap_request(
    ap_url: str,
    path: str,
    data: dict[str, str] | None = None,
    timeout: float = 10,
) -> str:
    body = None
    headers = {}
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = urllib.request.Request(
        f"{ap_url.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise ApiError(502, f"OpenEPaperLink AP returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(502, f"Cannot reach OpenEPaperLink AP: {exc.reason}") from exc


def get_tags(ap_url: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(ap_request(ap_url, "/get_db"))
    except json.JSONDecodeError as exc:
        raise ApiError(502, "OpenEPaperLink AP returned invalid tag data") from exc
    return payload.get("tags", [])


def normalize_mac(value: Any) -> str:
    mac = str(value or "").replace(":", "").replace("-", "").strip().upper()
    if len(mac) not in (12, 16) or any(char not in "0123456789ABCDEF" for char in mac):
        raise ApiError(400, "mac must contain 12 or 16 hexadecimal characters")
    return mac


def clean_text(value: Any, field: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ApiError(400, f"{field} is required")
    if len(text) > max_length:
        raise ApiError(400, f"{field} must be at most {max_length} characters")
    return text


def build_price_template(
    product: str,
    price: str,
    currency: str,
    note: str,
) -> list[dict[str, list[Any]]]:
    price_line = f"{price} {currency}".strip()
    template: list[dict[str, list[Any]]] = [
        {"box": [0, 0, 296, 128, 0]},
        {"textbox": [8, 5, 280, 34, product, "bahnschrift20", 1, 1, 0]},
        {"line": [8, 42, 288, 42, 1]},
        {"text": [288, 51, price_line, "bahnschrift70", 1, 2, 0]},
    ]
    if note:
        template.append({"text": [8, 112, note, "REFSAN12", 2, 0, 0]})
    return template


def send_price(ap_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    mac = normalize_mac(payload.get("mac"))
    product = clean_text(payload.get("product"), "product", 60)
    price = clean_text(payload.get("price"), "price", 20)
    currency = str(payload.get("currency", "RSD")).strip()[:10]
    note = str(payload.get("note", "")).strip()[:60]
    ttl = str(payload.get("ttl", 0))

    tags = get_tags(ap_url)
    tag = next((item for item in tags if item.get("mac", "").upper() == mac), None)
    if tag is None:
        raise ApiError(404, f"tag {mac} is not registered on the AP")
    if int(tag.get("hwType", -1)) != 17:
        raise ApiError(
            400,
            f"tag {mac} has hwType {tag.get('hwType')}; this layout currently supports hwType 17",
        )

    template = build_price_template(product, price, currency, note)
    result = ap_request(
        ap_url,
        "/jsonupload",
        {
            "mac": mac,
            "json": json.dumps(template, ensure_ascii=True, separators=(",", ":")),
            "ttl": ttl,
        },
    )
    return {
        "ok": True,
        "mac": mac,
        "product": product,
        "price": price,
        "currency": currency,
        "ap_response": result,
    }


class PriceApiHandler(BaseHTTPRequestHandler):
    server_version = "OEPLPriceAPI/1.0"

    @property
    def api_server(self) -> "PriceApiServer":
        return self.server  # type: ignore[return-value]

    def send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authenticate(self) -> None:
        expected = self.api_server.api_token
        if expected and self.headers.get("Authorization") != f"Bearer {expected}":
            raise ApiError(401, "missing or invalid bearer token")

    def do_GET(self) -> None:
        try:
            self.authenticate()
            if self.path == "/health":
                config = json.loads(ap_request(self.api_server.ap_url, "/get_ap_config"))
                self.send_json(
                    200,
                    {
                        "ok": config.get("apstate") == "1",
                        "ap_url": self.api_server.ap_url,
                        "ap_state": config.get("apstate"),
                    },
                )
                return
            if self.path == "/tags":
                self.send_json(200, {"tags": get_tags(self.api_server.ap_url)})
                return
            raise ApiError(404, "endpoint not found")
        except ApiError as exc:
            self.send_json(exc.status, {"ok": False, "error": exc.message})

    def do_POST(self) -> None:
        try:
            self.authenticate()
            if self.path != "/price":
                raise ApiError(404, "endpoint not found")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ApiError(400, "request body must be valid JSON") from exc
            if not isinstance(payload, dict):
                raise ApiError(400, "request body must be a JSON object")
            self.send_json(200, send_price(self.api_server.ap_url, payload))
        except ApiError as exc:
            self.send_json(exc.status, {"ok": False, "error": exc.message})

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"{self.address_string()} - {format % args}\n")


class PriceApiServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        ap_url: str,
        api_token: str,
    ):
        super().__init__(address, PriceApiHandler)
        self.ap_url = ap_url
        self.api_token = api_token


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ap-url", default=os.getenv("OEPL_AP_URL", DEFAULT_AP_URL))
    parser.add_argument("--listen", default=os.getenv("PRICE_API_LISTEN", DEFAULT_LISTEN))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PRICE_API_PORT", str(DEFAULT_PORT))),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = os.getenv("PRICE_API_TOKEN", "")
    server = PriceApiServer((args.listen, args.port), args.ap_url, token)
    print(f"Price API listening on http://{args.listen}:{args.port}")
    print(f"OpenEPaperLink AP: {args.ap_url}")
    if not token:
        print("Warning: PRICE_API_TOKEN is not set; requests are unauthenticated.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
