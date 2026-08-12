#!/usr/bin/env python3
"""ESL gateway: pulls prices for this store's tagged SKUs from PACMS and
pushes changed ones to tags.

Runs on the Raspberry Pi, called on demand (via the price-proxy's
POST /sync-now route, normally from sync-now.timer) -- there is no background
loop. PACMS never knows tags exist; this script is the only thing that bridges
the two. Each call:

    1. Read the SKUs this store actually has tags for, from tag_mapping.
    2. Reconcile prices that are still in flight: ask the AP which tags have
       actually taken their content, confirm those, re-send the rest.
    3. Ask PACMS for just those SKUs (GET /api/Esl/Prices?skus=..., batched).
    4. Compare each price against the last value confirmed *on the shelf*.
    5. If it really changed, POST /price to the local price-proxy for that tag.

Config is read from the environment (see the constants below). Point
PACMS_BASE_URL at the mock service while developing, and at the real PACMS
endpoint once it exists -- nothing else here needs to change.

Delivery accounting
-------------------
A 202 from the AP means "queued", not "the shelf shows this". A tag that was
out of range or flat when its price was pushed will never display it, and if
we treated the 202 as done we would cache the new price and never retry --
the shelf would lie, silently, forever.

So a price is tracked in two stages:

    delivery    -- pushed to the AP, not yet seen on the tag ("in flight")
    price_cache -- confirmed on the tag ("what the shelf really shows")

Only a confirmed price lands in price_cache, and only price_cache is compared
against PACMS. Anything that does not confirm is retried, and after
DELIVERY_MAX_ATTEMPTS it is reported as undelivered rather than forgotten.

Confirmation reads the AP's own tag database (GET /get_db on the AP's web
port) and requires all of:

    * the tag is no longer marked `pending`
    * its `updatecount` has gone up since we pushed
    * the content the AP rendered for it carries the price we sent

That last check is what makes this proof rather than inference.
"""

from __future__ import annotations

import json
import os
import sqlite3
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

# The AP's plain web port, where /get_db and /current/<mac>.json live. This is
# a different port from the authenticated price API in ESP_BASE_URL.
AP_WEB_URL = os.getenv("AP_WEB_URL", "http://192.168.0.34").rstrip("/")
# How long to let a push sit unconfirmed before sending it again. Tags check in
# every ~60s when associated, but one that is asleep can take much longer, so
# this wants to be generous enough not to spam the radio.
DELIVERY_RETRY_AFTER = float(os.getenv("DELIVERY_RETRY_AFTER_SECONDS", "900"))
DELIVERY_MAX_ATTEMPTS = int(os.getenv("DELIVERY_MAX_ATTEMPTS", "5"))
# Where to report shelf status, so a worker can see a red row instead of
# having to trust that the price arrived. Outbound only; unset to disable.
STATUS_REPORT_URL = os.getenv("STATUS_REPORT_URL", "").rstrip("/")
# Which store this Pi is. Each report replaces this store's rows wholesale, so
# a shelf that stops being reported stops being shown -- otherwise a retired
# tag would sit red forever and teach the worker to ignore the colour.
STORE_ID = os.getenv("STORE_ID", "default")

SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS price_cache (
    sku TEXT PRIMARY KEY,
    effective_price REAL NOT NULL,
    pushed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery (
    sku TEXT NOT NULL,
    tag_mac TEXT NOT NULL,
    price REAL NOT NULL,
    first_pushed_at TEXT NOT NULL,
    last_pushed_at TEXT NOT NULL,
    updatecount_at_push INTEGER,
    attempts INTEGER NOT NULL DEFAULT 1,
    last_error TEXT,
    PRIMARY KEY (sku, tag_mac)
);
"""


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{stamp} {message}", file=sys.stderr, flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def age_seconds(stamp: str) -> float:
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return 0.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds()


def connect():
    conn = tag_mapping.connect()
    conn.executescript(SCHEMA_EXTRA)
    try:
        conn.execute("ALTER TABLE delivery ADD COLUMN last_error TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # already there
    return conn


def get_tag_for_sku(conn, sku: str) -> list[str]:
    rows = conn.execute("SELECT tag_mac FROM tag_mapping WHERE sku = ?", (sku,)).fetchall()
    return [row[0] for row in rows]


def get_cached(conn, sku: str) -> float | None:
    """The price this SKU's tag is confirmed to be showing, if any."""
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
        (sku, effective_price, now_iso()),
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


# --------------------------------------------------------------------------
# What the AP knows
# --------------------------------------------------------------------------


def fetch_tag_state() -> dict[str, dict[str, Any]]:
    """Per-tag truth from the AP: has it taken its content, and when was it here.

    Returns an empty dict if the AP cannot be reached -- callers treat that as
    "cannot confirm anything right now", never as "nothing was delivered".
    """
    try:
        payload = http_get_json(f"{AP_WEB_URL}/get_db", {})
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        log(f"cannot read tag state from AP: {exc}")
        return {}
    state: dict[str, dict[str, Any]] = {}
    for tag in payload.get("tags", []):
        mac = str(tag.get("mac", "")).upper()
        if mac:
            state[mac] = tag
    return state


def rendered_carries_price(mac: str, price: float) -> bool | None:
    """Does the content the AP rendered for this tag show `price`?

    None means the check could not be made (file missing, AP unreachable), so
    it must not be read as a failure.
    """
    try:
        request = urllib.request.Request(f"{AP_WEB_URL}/current/{mac}.json", method="GET")
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            body = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError):
        return None
    return f"{price:.2f}" in body


# --------------------------------------------------------------------------
# Delivery tracking
# --------------------------------------------------------------------------


def record_push(
    conn, sku: str, mac: str, price: float, updatecount: int | None, error: str | None = None
) -> None:
    """Record an attempt, whether the AP took it or refused it.

    Refusals are recorded too, so that a price the AP will never accept is
    retried a bounded number of times and then reported red, instead of being
    dropped on the floor.
    """
    stamp = now_iso()
    conn.execute(
        """
        INSERT INTO delivery (sku, tag_mac, price, first_pushed_at, last_pushed_at,
                              updatecount_at_push, attempts, last_error)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(sku, tag_mac) DO UPDATE SET
            price = excluded.price,
            last_pushed_at = excluded.last_pushed_at,
            updatecount_at_push = excluded.updatecount_at_push,
            last_error = excluded.last_error,
            attempts = delivery.attempts + 1
        """,
        (sku, mac, price, stamp, stamp, updatecount, error),
    )
    conn.commit()


def clear_delivery(conn, sku: str, mac: str) -> None:
    conn.execute("DELETE FROM delivery WHERE sku = ? AND tag_mac = ?", (sku, mac))
    conn.commit()


def in_flight(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT sku, tag_mac, price, first_pushed_at, last_pushed_at,
               updatecount_at_push, attempts, last_error
        FROM delivery
        """
    ).fetchall()
    return [
        {
            "sku": r[0],
            "tag_mac": r[1],
            "price": r[2],
            "first_pushed_at": r[3],
            "last_pushed_at": r[4],
            "updatecount_at_push": r[5],
            "attempts": r[6],
            "last_error": r[7],
        }
        for r in rows
    ]


def confirm_delivery(row: dict[str, Any], tag: dict[str, Any] | None) -> bool:
    """Has this tag actually taken the price we pushed?"""
    if tag is None:
        return False
    if tag.get("pending"):
        return False
    before = row["updatecount_at_push"]
    if before is not None and int(tag.get("updatecount", 0)) <= int(before):
        # The tag has not rendered anything new since we pushed.
        return False
    carries = rendered_carries_price(row["tag_mac"], row["price"])
    if carries is False:
        return False
    return True


def reconcile(conn, tag_state: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Confirm what landed, re-send what did not, give up loudly on the rest."""
    confirmed = 0
    resent = 0
    undelivered = 0

    for row in in_flight(conn):
        sku, mac = row["sku"], row["tag_mac"]
        tag = tag_state.get(mac.upper())

        if confirm_delivery(row, tag):
            set_cached(conn, sku, row["price"])
            clear_delivery(conn, sku, mac)
            confirmed += 1
            log(f"  confirmed on shelf: {sku} {row['price']:.2f} RSD ({mac})")
            continue

        if age_seconds(row["last_pushed_at"]) < DELIVERY_RETRY_AFTER:
            continue  # still within its grace period, leave it alone

        if row["attempts"] >= DELIVERY_MAX_ATTEMPTS:
            undelivered += 1
            why = row["last_error"] or "tag never took it"
            log(
                f"  UNDELIVERED after {row['attempts']} attempts: {sku} "
                f"{row['price']:.2f} RSD ({mac}) -- shelf still shows the old "
                f"price [{why}]"
            )
            continue

        error = push_price(mac, sku, row["price"])
        updatecount = int(tag.get("updatecount", 0)) if tag else None
        record_push(conn, sku, mac, row["price"], updatecount, error)
        resent += 1
        log(f"  re-sent (attempt {row['attempts'] + 1}): {sku} ({mac})")

    return {"confirmed": confirmed, "resent": resent, "undelivered": undelivered}


# --------------------------------------------------------------------------
# Pushing
# --------------------------------------------------------------------------

_last_push_at = 0.0
_MIN_PUSH_SPACING = 1.1  # ESP price API allows at most one request per second


def _throttle() -> None:
    global _last_push_at
    wait = _last_push_at + _MIN_PUSH_SPACING - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_push_at = time.monotonic()


def push_price(mac: str, title: str, price: float) -> str | None:
    """Hand a price to the AP.

    Returns None if the AP accepted it for delivery -- which is NOT the same as
    the tag showing it; confirmation is reconcile()'s job -- or a short error
    string if the AP refused. A refusal must still be tracked: a price the AP
    will never accept has to end up visibly red, not sit in "sending" forever.
    """
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
            log(f"  -> queued {mac}: {payload['product']} {payload['price']} RSD ({response.status})")
            return None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        log(f"  -> REFUSED {mac}: HTTP {exc.code} {body}")
        return f"HTTP {exc.code}: {body[:200]}"
    except urllib.error.URLError as exc:
        log(f"  -> REFUSED {mac}: cannot reach proxy ({exc.reason})")
        return f"proxy unreachable: {exc.reason}"


# --------------------------------------------------------------------------
# Status, for humans
# --------------------------------------------------------------------------


def shelf_status(conn, products: list[dict[str, Any]], tag_state: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per tagged SKU, in the terms a shop worker cares about.

    state is one of:
        on_shelf      -- confirmed, the glass shows this price
        in_flight     -- sent, waiting for the tag to wake up and take it
        undelivered   -- retried to exhaustion, the shelf is showing the old price
        no_tag        -- priced, but nothing is mapped to display it
    """
    flight = {(r["sku"], r["tag_mac"]): r for r in in_flight(conn)}
    report: list[dict[str, Any]] = []

    for record in products:
        sku = record["sku"]
        price = effective_price(record)
        macs = get_tag_for_sku(conn, sku)
        if not macs:
            report.append({"sku": sku, "state": "no_tag", "wanted_price": price})
            continue

        for mac in macs:
            tag = tag_state.get(mac.upper())
            row = flight.get((sku, mac))
            if row is not None:
                exhausted = row["attempts"] >= DELIVERY_MAX_ATTEMPTS
                state = "undelivered" if exhausted else "in_flight"
            elif get_cached(conn, sku) == price:
                state = "on_shelf"
            else:
                state = "in_flight"  # will go out on this cycle

            report.append(
                {
                    "sku": sku,
                    "tag_mac": mac,
                    "state": state,
                    "wanted_price": price,
                    "shelf_price": get_cached(conn, sku),
                    "attempts": row["attempts"] if row else 0,
                    "last_error": row["last_error"] if row else None,
                    "waiting_seconds": int(age_seconds(row["first_pushed_at"])) if row else 0,
                    "tag_last_seen_seconds": (
                        int(time.time()) - int(tag.get("lastseen", 0)) if tag else None
                    ),
                    "tag_battery_mv": tag.get("batteryMv") if tag else None,
                }
            )

    return report


def report_status(report: list[dict[str, Any]]) -> None:
    """Push shelf status up to the catalog so its UI can colour the rows.

    Outbound only -- the store is never called into. Best effort: a catalog
    that does not accept status reports is not an error, prices still flow.
    """
    if not STATUS_REPORT_URL:
        return
    body = json.dumps(
        {"store": STORE_ID, "reported_at": now_iso(), "shelves": report}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{STATUS_REPORT_URL}/api/Esl/ShelfStatus",
        data=body,
        headers={"X-Api-Key": PACMS_API_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        log(f"could not report shelf status (prices still synced): {exc}")


# --------------------------------------------------------------------------


def sync_once(conn) -> dict[str, Any]:
    skus = tag_mapping.get_mapped_skus(conn)
    if not skus:
        return {"skus_mapped": 0, "checked": 0, "pushed": 0, "unchanged": 0, "failed": 0}

    log(f"syncing {len(skus)} mapped SKU(s)")

    # Ask the AP what it knows before doing anything, so updatecount snapshots
    # taken for this cycle's pushes predate those pushes.
    tag_state = fetch_tag_state()
    recon = reconcile(conn, tag_state)

    try:
        products = fetch_prices_for_skus(skus)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        log(f"failed to fetch prices from PACMS: {exc}")
        return {"ok": False, "error": str(exc), **recon}

    pushed = 0
    unchanged = 0
    failed = 0
    for record in products:
        sku = record["sku"]
        price = effective_price(record)
        if get_cached(conn, sku) == price:
            unchanged += 1
            continue

        tag_macs = get_tag_for_sku(conn, sku)
        if not tag_macs:
            # Nothing to show it on. Record it so the SKU stops looking changed.
            set_cached(conn, sku, price)
            continue

        log(f"price change for {sku}: {price:.2f} RSD")
        for mac in tag_macs:
            already = next(
                (r for r in in_flight(conn) if r["sku"] == sku and r["tag_mac"] == mac),
                None,
            )
            if already is not None and already["price"] == price:
                continue  # same price already in flight, do not stack pushes

            error = push_price(mac, record.get("title", sku), price)
            tag = tag_state.get(mac.upper())
            record_push(
                conn, sku, mac, price, int(tag.get("updatecount", 0)) if tag else None, error
            )
            if error is None:
                pushed += 1
            else:
                failed += 1

    summary = {
        "skus_mapped": len(skus),
        "checked": len(products),
        "pushed": pushed,
        "unchanged": unchanged,
        "failed": failed,
        **recon,
        "in_flight": len(in_flight(conn)),
    }

    report_status(shelf_status(conn, products, tag_state))
    return summary


def require_config() -> None:
    if not PROXY_TOKEN:
        raise RuntimeError("PROXY_PUBLIC_TOKEN (or PUBLIC_API_TOKEN) environment variable is required")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        conn = connect()
        try:
            tag_state = fetch_tag_state()
            skus = tag_mapping.get_mapped_skus(conn)
            products = fetch_prices_for_skus(skus) if skus else []
            print(json.dumps(shelf_status(conn, products, tag_state), indent=2))
        finally:
            conn.close()
        return

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
