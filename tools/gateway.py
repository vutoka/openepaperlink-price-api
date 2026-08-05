#!/usr/bin/env python3
"""ESL gateway: pulls prices for this store's tagged SKUs from PACMS and
pushes changed ones to tags.

Runs on the Raspberry Pi, called on demand (via the price-proxy's
POST /sync-now route, or directly for manual testing over SSH) -- there is
no background loop. PACMS never knows tags exist; this script is the only
thing that bridges the two. Each call:

    1. Read the SKUs this store actually has tags for, from tag_mapping.
    2. Ask PACMS for just those SKUs (GET /api/Esl/Prices?skus=..., batched).
    3. Compare each price against the last value actually pushed.
    4. If it really changed, POST /price to the local price-proxy for that tag.

Config is read from the environment (see the *_ constants below). Point
PACMS_BASE_URL at the mock service while developing, and at the real PACMS
endpoint once it exists -- nothing else here needs to change.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

import tag_mapping

PACMS_BASE_URL = os.getenv("PACMS_BASE_URL", "http://127.0.0.1:9000").rstrip("/")
PACMS_API_KEY = os.getenv("PACMS_API_KEY", "dev-mock-key")
PROXY_BASE_URL = os.getenv("PRICE_PROXY_URL", "http://127.0.0.1:8000").rstrip("/")
PROXY_TOKEN = os.getenv("PROXY_PUBLIC_TOKEN") or os.getenv("PUBLIC_API_TOKEN", "")
REQUEST_TIMEOUT = float(os.getenv("GATEWAY_REQUEST_TIMEOUT", "15"))
SKU_BATCH_SIZE = int(os.getenv("GATEWAY_SKU_BATCH_SIZE", "100"))

SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS price_cache (
    sku TEXT PRIMARY KEY,
    effective_price REAL NOT NULL,
    pushed_at TEXT NOT NULL
);
"""


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{stamp} {message}", file=sys.stderr, flush=True)


def connect():
    conn = tag_mapping.connect()
    conn.executescript(SCHEMA_EXTRA)
    return conn


def get_tag_for_sku(conn, sku: str) -> list[str]:
    rows = conn.execute("SELECT tag_mac FROM tag_mapping WHERE sku = ?", (sku,)).fetchall()
    return [row[0] for row in rows]


def get_cached(conn, sku: str) -> float | None:
    row = conn.execute(
        "SELECT effective_price FROM price_cache WHERE sku = ?", (sku,)
    ).fetchone()
    return row[0] if row else None


def set_cached(conn, sku: str, effective_price: float) -> None:
    conn.execute(
        """
        INSERT INTO price_cache (sku, effective_price, pushed_at)
        VALUES (?, ?, ?)
        ON CONFLICT(sku) DO UPDATE SET
            effective_price = excluded.effective_price,
            pushed_at = excluded.pushed_at
        """,
        (sku, effective_price, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    conn.commit()


def effective_price(record: dict[str, Any]) -> float:
    return float(record["price"])


def http_get_json(url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_prices_for_skus(skus: list[str], batch_size: int = SKU_BATCH_SIZE) -> list[dict[str, Any]]:
    headers = {"X-Api-Key": PACMS_API_KEY}
    products: list[dict[str, Any]] = []
    for start in range(0, len(skus), batch_size):
        batch = skus[start : start + batch_size]
        url = f"{PACMS_BASE_URL}/api/Esl/Prices?skus={','.join(batch)}"
        products.extend(http_get_json(url, headers))
    return products


_last_push_at = 0.0
_MIN_PUSH_SPACING = 1.1  # ESP price API allows at most one request per second


def _throttle() -> None:
    global _last_push_at
    wait = _last_push_at + _MIN_PUSH_SPACING - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_push_at = time.monotonic()


def push_price(mac: str, title: str, price: float) -> bool:
    _throttle()
    payload = {
        "mac": mac,
        "product": title[:60],
        "price": f"{price:.2f}",
        "currency": "RSD",
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{PROXY_BASE_URL}/price",
        data=body,
        headers={
            "Authorization": f"Bearer {PROXY_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            response.read()
            log(f"  -> pushed {mac}: {payload['product']} {payload['price']} RSD ({response.status})")
            return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        log(f"  -> FAILED {mac}: HTTP {exc.code} {body}")
        return False
    except urllib.error.URLError as exc:
        log(f"  -> FAILED {mac}: cannot reach proxy ({exc.reason})")
        return False


def sync_once(conn) -> dict[str, Any]:
    skus = tag_mapping.get_mapped_skus(conn)
    if not skus:
        return {"skus_mapped": 0, "checked": 0, "pushed": 0, "unchanged": 0, "failed": 0}

    log(f"syncing {len(skus)} mapped SKU(s)")
    try:
        products = fetch_prices_for_skus(skus)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        log(f"failed to fetch prices from PACMS: {exc}")
        return {"ok": False, "error": str(exc)}

    pushed = 0
    unchanged = 0
    failed = 0
    for record in products:
        sku = record["sku"]
        price = effective_price(record)
        cached = get_cached(conn, sku)
        if cached is not None and cached == price:
            unchanged += 1
            continue

        tag_macs = get_tag_for_sku(conn, sku)
        if not tag_macs:
            set_cached(conn, sku, price)
            continue

        log(f"price change for {sku}: {price:.2f} RSD")
        all_ok = True
        for mac in tag_macs:
            ok = push_price(mac, record.get("title", sku), price)
            if ok:
                pushed += 1
            else:
                failed += 1
                all_ok = False
        if all_ok:
            set_cached(conn, sku, price)

    return {
        "skus_mapped": len(skus),
        "checked": len(products),
        "pushed": pushed,
        "unchanged": unchanged,
        "failed": failed,
    }


def require_config() -> None:
    if not PROXY_TOKEN:
        raise RuntimeError("PROXY_PUBLIC_TOKEN (or PUBLIC_API_TOKEN) environment variable is required")


def main() -> None:
    require_config()
    conn = connect()
    try:
        summary = sync_once(conn)
        log(f"done: {summary}")
        print(json.dumps(summary))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
