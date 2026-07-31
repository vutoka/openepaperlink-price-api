#!/usr/bin/env python3
"""Mock PACMS ESL price endpoint, for developing the gateway without the real CMS.

Mirrors the endpoint proposed in the PACMS context doc:

    GET /api/Esl/Prices?since=<ISO8601>&page=<int>&size=<int>
    GET /api/Esl/Prices?skus=<sku1>,<sku2>,...

Auth is a shared X-Api-Key header, matching how PACMS API keys work.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


LISTEN_HOST = os.getenv("MOCK_PACMS_LISTEN", "127.0.0.1")
LISTEN_PORT = int(os.getenv("MOCK_PACMS_PORT", "9000"))
API_KEY = os.getenv("MOCK_PACMS_API_KEY", "dev-mock-key")
DEFAULT_PAGE_SIZE = 1000

_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_since(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# In-memory catalog. Seeded with a handful of tool-store-style items so the
# gateway has something realistic to pull and diff against.
_catalog: dict[str, dict[str, Any]] = {
    sku: record
    for sku, record in (
        (
            "BOSCH-GSB13RE",
            {
                "sku": "BOSCH-GSB13RE",
                "barcode": "3165140617703",
                "title": "Bosch GSB 13 RE udarna busilica",
                "price": 8990.00,
                "salePrice": None,
                "stock": 12,
                "modifiedAt": now_iso(),
            },
        ),
        (
            "MAK-9558NB",
            {
                "sku": "MAK-9558NB",
                "barcode": "0088381727450",
                "title": "Makita 9558NB ugaona brusilica 125mm",
                "price": 7490.00,
                "salePrice": 6490.00,
                "stock": 5,
                "modifiedAt": now_iso(),
            },
        ),
        (
            "DEWALT-DCD778",
            {
                "sku": "DEWALT-DCD778",
                "barcode": "5035048729414",
                "title": "DeWalt DCD778 akumulatorska busilica 18V",
                "price": 15990.00,
                "salePrice": None,
                "stock": 3,
                "modifiedAt": now_iso(),
            },
        ),
        (
            "STANLEY-FMHT1",
            {
                "sku": "STANLEY-FMHT1",
                "barcode": "3253560016114",
                "title": "Stanley FatMax metar 5m",
                "price": 1290.00,
                "salePrice": None,
                "stock": 40,
                "modifiedAt": now_iso(),
            },
        ),
        (
            "BOSCH-PST700",
            {
                "sku": "BOSCH-PST700",
                "barcode": "3165140581905",
                "title": "Bosch PST 700 E ubodna testera",
                "price": 6290.00,
                "salePrice": 5490.00,
                "stock": 8,
                "modifiedAt": now_iso(),
            },
        ),
    )
}


def sanitized_sale_price(price: float, sale_price: float | None) -> float | None:
    if sale_price is None or sale_price <= 0 or sale_price >= price:
        return None
    return sale_price


def serialize(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "sku": record["sku"],
        "barcode": record["barcode"],
        "title": record["title"],
        "price": record["price"],
        "salePrice": sanitized_sale_price(record["price"], record["salePrice"]),
        "stock": record["stock"],
        "modifiedAt": record["modifiedAt"],
    }


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "MockPACMS/1.0"

    def authenticate(self) -> None:
        supplied = self.headers.get("X-Api-Key", "")
        if not secrets.compare_digest(supplied, API_KEY):
            raise ApiError(401, "missing or invalid X-Api-Key")

    def send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError(400, "invalid Content-Length") from exc
        if length <= 0:
            raise ApiError(400, "request body is required")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, "request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ApiError(400, "request body must be a JSON object")
        return payload

    def handle_list_prices(self, query: dict[str, list[str]]) -> None:
        with _lock:
            records = list(_catalog.values())

        if "skus" in query:
            wanted = {s.strip() for s in query["skus"][0].split(",") if s.strip()}
            records = [r for r in records if r["sku"] in wanted]

        if "since" in query:
            try:
                since = parse_since(query["since"][0])
            except ValueError as exc:
                raise ApiError(400, "since must be ISO8601") from exc
            records = [r for r in records if parse_since(r["modifiedAt"]) > since]

        records.sort(key=lambda r: r["modifiedAt"])

        page = int(query.get("page", ["0"])[0])
        size = int(query.get("size", [str(DEFAULT_PAGE_SIZE)])[0])
        start = page * size
        page_records = records[start : start + size]

        self.send_json(200, [serialize(r) for r in page_records])

    def handle_mock_set_price(self) -> None:
        payload = self.read_json_body()
        sku = payload.get("sku")
        if not sku or sku not in _catalog:
            raise ApiError(404, f"unknown sku: {sku!r}")

        with _lock:
            record = _catalog[sku]
            if "price" in payload:
                record["price"] = float(payload["price"])
            if "salePrice" in payload:
                sp = payload["salePrice"]
                record["salePrice"] = None if sp is None else float(sp)
            record["modifiedAt"] = now_iso()
            result = serialize(record)

        self.send_json(200, {"ok": True, "updated": result})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            self.authenticate()
            if parsed.path == "/health":
                self.send_json(200, {"ok": True, "service": "mock-pacms", "products": len(_catalog)})
            elif parsed.path == "/api/Esl/Prices":
                self.handle_list_prices(query)
            else:
                raise ApiError(404, "endpoint not found")
        except ApiError as exc:
            self.send_json(exc.status, {"ok": False, "error": exc.message})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            self.authenticate()
            if parsed.path == "/api/Esl/_mock/set-price":
                self.handle_mock_set_price()
            else:
                raise ApiError(404, "endpoint not found")
        except ApiError as exc:
            self.send_json(exc.status, {"ok": False, "error": exc.message})

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"{self.client_address[0]} - {format % args}\n")


def main() -> None:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"mock PACMS listening on http://{LISTEN_HOST}:{LISTEN_PORT}")
    print(f"X-Api-Key: {API_KEY}")
    print(f"seeded {len(_catalog)} products")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
