#!/usr/bin/env python3
"""ESL gateway: pulls price changes from PACMS and pushes them to tags.

Runs entirely on the Raspberry Pi. PACMS never knows tags exist; this script
is the only thing that bridges the two. Each cycle:

    1. Pull products changed since the last cycle from PACMS (GET /api/Esl/Prices).
    2. For each one, look up which tag (if any) is paired with that SKU.
    3. Compare the effective price against the last value we actually pushed.
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
PROXY_TOKEN = os.getenv("PROXY_PUBLIC_TOKEN", "")
POLL_INTERVAL_SECONDS = int(os.getenv("GATEWAY_POLL_INTERVAL_SECONDS", "300"))
REQUEST_TIMEOUT = float(os.getenv("GATEWAY_REQUEST_TIMEOUT", "15"))

SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS price_cache (
    sku TEXT PRIMARY KEY,
    effective_price REAL NOT NULL,
    note TEXT,
    pushed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{stamp} {message}", file=sys.stderr, flush=True)


def connect():
    conn = tag_mapping.connect()
    conn.executescript(SCHEMA_EXTRA)
    return conn


def get_since(conn) -> str | None:
    row = conn.execute("SELECT value FROM sync_state WHERE key = 'last_since'").fetchone()
    return row[0] if row else None


def set_since(conn, value: str) -> None:
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES ('last_since', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (value,),
    )
    conn.commit()


def get_tag_for_sku(conn, sku: str) -> list[str]:
    rows = conn.execute("SELECT tag_mac FROM tag_mapping WHERE sku = ?", (sku,)).fetchall()
    return [row[0] for row in rows]


def get_cached(conn, sku: str) -> tuple[float, str] | None:
    row = conn.execute(
        "SELECT effective_price, note FROM price_cache WHERE sku = ?", (sku,)
    ).fetchone()
    return (row[0], row[1] or "") if row else None


def set_cached(conn, sku: str, effective_price: float, note: str) -> None:
    conn.execute(
        """
        INSERT INTO price_cache (sku, effective_price, note, pushed_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(sku) DO UPDATE SET
            effective_price = excluded.effective_price,
            note = excluded.note,
            pushed_at = excluded.pushed_at
        """,
        (sku, effective_price, note, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    conn.commit()


def effective_price_and_note(record: dict[str, Any]) -> tuple[float, str]:
    sale_price = record.get("salePrice")
    if sale_price is not None:
        return float(sale_price), "Akcija"
    return float(record["price"]), ""


def http_get_json(url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_changed_products(since: str | None) -> list[dict[str, Any]]:
    url = f"{PACMS_BASE_URL}/api/Esl/Prices"
    if since:
        url += f"?since={since}"
    headers = {"X-Api-Key": PACMS_API_KEY}
    return http_get_json(url, headers)


_last_push_at = 0.0
_MIN_PUSH_SPACING = 1.1  # ESP price API allows at most one request per second


def _throttle() -> None:
    global _last_push_at
    wait = _last_push_at + _MIN_PUSH_SPACING - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_push_at = time.monotonic()


def push_price(mac: str, title: str, effective_price: float, note: str) -> None:
    _throttle()
    payload = {
        "mac": mac,
        "product": title[:60],
        "price": f"{effective_price:.2f}",
        "currency": "RSD",
        "note": note,
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
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        log(f"  -> FAILED {mac}: HTTP {exc.code} {body}")
    except urllib.error.URLError as exc:
        log(f"  -> FAILED {mac}: cannot reach proxy ({exc.reason})")


def sync_once(conn) -> int:
    since = get_since(conn)
    log(f"pulling prices since={since or '(all)'}")
    try:
        products = fetch_changed_products(since)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        log(f"failed to fetch prices from PACMS: {exc}")
        return 0

    pushed = 0
    latest_modified = since
    for record in products:
        sku = record["sku"]
        modified_at = record.get("modifiedAt")
        if modified_at and (latest_modified is None or modified_at > latest_modified):
            latest_modified = modified_at

        effective_price, note = effective_price_and_note(record)
        cached = get_cached(conn, sku)
        if cached is not None and cached == (effective_price, note):
            continue  # ModifiedAt moved but the price itself didn't -- nothing to do

        tag_macs = get_tag_for_sku(conn, sku)
        if not tag_macs:
            set_cached(conn, sku, effective_price, note)
            continue

        log(f"price change for {sku}: {effective_price:.2f} RSD{' (Akcija)' if note else ''}")
        for mac in tag_macs:
            push_price(mac, record.get("title", sku), effective_price, note)
            pushed += 1
        set_cached(conn, sku, effective_price, note)

    if latest_modified:
        set_since(conn, latest_modified)
    return pushed


def require_config() -> None:
    if not PROXY_TOKEN:
        raise RuntimeError("PROXY_PUBLIC_TOKEN environment variable is required")


def main() -> None:
    require_config()
    once = "--once" in sys.argv
    conn = connect()
    try:
        if once:
            pushed = sync_once(conn)
            log(f"done, {pushed} tag update(s) pushed")
            return
        log(f"gateway loop starting, polling every {POLL_INTERVAL_SECONDS}s")
        while True:
            pushed = sync_once(conn)
            log(f"cycle done, {pushed} tag update(s) pushed")
            time.sleep(POLL_INTERVAL_SECONDS)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
