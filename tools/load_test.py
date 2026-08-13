#!/usr/bin/env python3
"""Push N price updates through the whole chain and time every one of them.

Why cycle updates over three tags instead of testing four hundred
--------------------------------------------------------------------
Everything about a 400-tag store has now been measured except what happens
when 400 real price changes actually travel the chain: catalog -> Pi -> S3 ->
C6 -> glass, with real rendering and real radio. Synthetic tag records never
transmit, so they cannot answer that. Buying 400 tags to find out is the
expensive path; sending 400 updates round-robin to the three real tags is not.

What makes it a fair test is `newproto.cpp:166`:

    if ((nextCheckin & 0x8000) == 0 && wsClientCount() && (config.stopsleep == 1))
        nextCheckin = 0;

With a WebSocket client attached and `stopsleep` at its default of 1, the AP
tells tags not to sleep. Three tags then behave as a continuously available
queue of work -- which is exactly how several hundred staggered tags present
themselves to the AP, since some tag is always awake. So this script holds a
WebSocket open for its whole run. Without it the run would measure sleep
timers, not throughput.

Read the result with its bias in mind:

  * pessimistic on total time -- one tag cannot take two updates at once,
    where 400 separate tags would be serviced back to back
  * optimistic on reliability -- three transmitters never fight for the
    channel the way hundreds do

Collisions remain the one thing only real hardware can answer.

Runs on the Pi: `price-proxy` listens on 127.0.0.1, so /sync-now is not
reachable from anywhere else.

    sudo bash -c 'set -a; . /etc/price-proxy.env; set +a; python3 load_test.py --count 100'
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import statistics
import struct
import sys
import threading
import time
import urllib.error
import urllib.request

AP = os.getenv("AP_WEB_URL", "http://192.168.0.34").rstrip("/")
AP_HOST = AP.split("//", 1)[-1].split(":")[0]
PROXY = os.getenv("PRICE_PROXY_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.getenv("PUBLIC_API_TOKEN") or os.getenv("PROXY_PUBLIC_TOKEN", "")
CATALOG = os.getenv("PACMS_BASE_URL", "http://192.168.0.30:9000").rstrip("/")
API_KEY = os.getenv("PACMS_API_KEY", "dev-mock-key")

# sku, mac, the price to put back when the run finishes
TARGETS = [
    ("BOSCH-GSB13RE", "000001811E293B37", 8499.00),
    ("MAK-9558NB", "00000181500F3B39", 5000.00),
    ("DEWALT-DCD778", "0000018152583B39", 14499.00),
]

CONFIRM_TIMEOUT = 180.0
POLL = 0.4
# The AP's price API allows one request a second (web.cpp:93) and answers 429
# above that. gateway.py already spaces its pushes; anything else must too.
RESTORE_SPACING = 2.0


# --------------------------------------------------------------------------
# Minimal WebSocket client -- its only jobs are to keep the tags awake and to
# report free heap while the run is in progress.
# --------------------------------------------------------------------------


class ApSocket(threading.Thread):
    daemon = True

    def __init__(self, host: str):
        super().__init__()
        self.host = host
        self.latest: dict = {}
        self.alive = False
        self._stop = threading.Event()
        self.sock: socket.socket | None = None

    def connect(self) -> None:
        sock = socket.create_connection((self.host, 80), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(
            f"GET /ws HTTP/1.1\r\nHost: {self.host}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("closed during handshake")
            buf += chunk
        if b"101" not in buf.split(b"\r\n", 1)[0]:
            raise ConnectionError("handshake refused")
        self.sock = sock
        self.alive = True

    def _send(self, opcode: int, payload: bytes = b"") -> None:
        # Client frames must be masked.
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        header = bytes([0x80 | opcode, 0x80 | len(payload)])
        self.sock.sendall(header + mask + masked)

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                if self.sock is None:
                    self.connect()
                header = self.sock.recv(2)
                if len(header) < 2:
                    raise ConnectionError("closed")
                opcode = header[0] & 0x0F
                masked = bool(header[1] & 0x80)
                length = header[1] & 0x7F
                if length == 126:
                    length = struct.unpack(">H", self.sock.recv(2))[0]
                elif length == 127:
                    length = struct.unpack(">Q", self.sock.recv(8))[0]
                maskbytes = self.sock.recv(4) if masked else b""
                payload = b""
                while len(payload) < length:
                    part = self.sock.recv(length - len(payload))
                    if not part:
                        raise ConnectionError("closed mid-frame")
                    payload += part
                if masked:
                    payload = bytes(b ^ maskbytes[i % 4] for i, b in enumerate(payload))

                if opcode == 0x9:  # ping -- answer or the AP drops us
                    self._send(0xA, payload)
                elif opcode == 0x8:
                    raise ConnectionError("server closed")
                elif opcode == 0x1:
                    try:
                        msg = json.loads(payload.decode("utf-8", "replace"))
                    except json.JSONDecodeError:
                        continue
                    if isinstance(msg, dict) and "sys" in msg:
                        self.latest = msg["sys"]
            except Exception:
                # Reconnect: dropping the socket would let the tags fall
                # asleep and quietly change what the run is measuring.
                self.alive = False
                try:
                    if self.sock:
                        self.sock.close()
                except Exception:
                    pass
                self.sock = None
                time.sleep(2)

    def stop(self) -> None:
        self._stop.set()
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass


# --------------------------------------------------------------------------


def tag_record(mac: str) -> dict:
    with urllib.request.urlopen(f"{AP}/get_db?mac={mac}", timeout=20) as r:
        tags = json.loads(r.read().decode("utf-8", "replace")).get("tags", [])
    return tags[0] if tags else {}


def rendered_carries(mac: str, price: float) -> bool:
    try:
        with urllib.request.urlopen(f"{AP}/current/{mac}.json", timeout=20) as r:
            return f"{price:.2f}" in r.read().decode("utf-8", "replace")
    except Exception:
        return False


def set_catalog_price(sku: str, price: float) -> None:
    body = json.dumps({"price": price}).encode()
    req = urllib.request.Request(
        f"{CATALOG}/api/Esl/Products/{sku}",
        data=body,
        headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def sync_now() -> dict:
    req = urllib.request.Request(
        f"{PROXY}/sync-now",
        data=b"",
        headers={"Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--restore-only", action="store_true",
                    help="skip the run, just put the original prices back")
    args = ap.parse_args()

    if not TOKEN:
        print("no proxy token in the environment", file=sys.stderr)
        return 1

    if args.restore_only:
        return restore()

    ws = ApSocket(AP_HOST)
    ws.start()
    time.sleep(3)
    print(f"websocket: {'povezan' if ws.alive else 'NIJE povezan -- tagovi ce spavati'}")

    before = {mac: int(tag_record(mac).get("updatecount", 0)) for _, mac, _ in TARGETS}
    batt_before = {mac: tag_record(mac).get("batteryMv") for _, mac, _ in TARGETS}
    heap_start = ws.latest.get("heap")
    print(f"pocetni heap: {heap_start}")
    print(f"pocetne baterije: {batt_before}")
    print()

    # Updates go out in rounds, one round changing every mapped SKU and
    # pushing them with a single /sync-now -- which is what a real morning
    # does. Confirming one tag before starting the next would add a
    # serialisation that no store has, and turns a throughput measurement
    # into a latency one: a first pass built that way reported 20s per update
    # against a measured 3.9s of radio time, all of it waiting.
    times: list[float] = []
    round_times: list[float] = []
    failures = 0
    updates_done = 0
    t_run = time.time()
    rounds = (args.count + len(TARGETS) - 1) // len(TARGETS)

    for r in range(rounds):
        remaining = args.count - updates_done
        batch = TARGETS[: min(len(TARGETS), remaining)]
        prices = {sku: round(base + 1 + r % 400, 2) for sku, _, base in batch}

        t_round = time.time()
        before_counts = {mac: int(tag_record(mac).get("updatecount", 0)) for _, mac, _ in batch}

        try:
            for sku, _, _ in batch:
                set_catalog_price(sku, prices[sku])
            sync_now()
        except Exception as exc:
            print(f"runda {r+1:3d}  GRESKA pri slanju: {exc}")
            failures += len(batch)
            updates_done += len(batch)
            continue

        pending = {mac: sku for sku, mac, _ in batch}
        done: dict[str, float] = {}
        while pending and time.time() - t_round < CONFIRM_TIMEOUT:
            time.sleep(POLL)
            for mac in list(pending):
                rec = tag_record(mac)
                if int(rec.get("updatecount", 0)) > before_counts[mac] and not rec.get("pending"):
                    if rendered_carries(mac, prices[pending[mac]]):
                        done[mac] = time.time() - t_round
                        del pending[mac]

        dt_round = time.time() - t_round
        round_times.append(dt_round)
        times.extend(done.values())
        failures += len(pending)
        updates_done += len(batch)

        heap = ws.latest.get("heap")
        state = " ".join(f"{m[-6:]}={done[m]:.0f}s" for m in done)
        miss = " ".join(f"{m[-6:]}=NIJE" for m in pending)
        print(f"runda {r+1:3d} ({updates_done:4d}/{args.count})  {dt_round:6.1f}s  "
              f"{state} {miss}  heap={heap}")

    total = time.time() - t_run
    print()
    print("=" * 62)
    print(f"azuriranja: {args.count}  potvrdjeno: {len(times)}  neuspelo: {failures}")
    print(f"ukupno vreme: {total/60:.1f} min")
    if times:
        per_update = total / max(len(times), 1)
        print(f"latencija po azuriranju: prosek {statistics.mean(times):.1f}s  "
              f"median {statistics.median(times):.1f}s  "
              f"najbrze {min(times):.1f}s  najsporije {max(times):.1f}s")
        print(f"runda ({len(TARGETS)} taga paralelno): prosek "
              f"{statistics.mean(round_times):.1f}s")
        print(f"propusnost: {per_update:.1f}s po potvrdjenom azuriranju")
        print(f"  -> 400 azuriranja: {400*per_update/60:.0f} min")
        print("  (gornja granica: tri taga ne mogu da preuzimaju paralelno "
              "koliko bi 400 njih)")
    heap_end = ws.latest.get("heap")
    print(f"heap: {heap_start} -> {heap_end}", end="")
    if heap_start and heap_end:
        print(f"  (razlika {heap_end - heap_start:+d} B)")
    else:
        print()

    after = {mac: tag_record(mac) for _, mac, _ in TARGETS}
    print("\nbaterije i brojaci posle:")
    for _, mac, _ in TARGETS:
        rec = after[mac]
        print(f"  {mac}  batteryMv {batt_before[mac]} -> {rec.get('batteryMv')}  "
              f"updatecount {before[mac]} -> {rec.get('updatecount')}")

    ws.stop()
    print()
    return restore()


def restore() -> int:
    print("vracanje polaznih cena:")
    for sku, mac, base in TARGETS:
        try:
            set_catalog_price(sku, base)
            print(f"  {sku} <- {base:.2f} RSD")
        except Exception as exc:
            print(f"  {sku} GRESKA: {exc}")
        time.sleep(RESTORE_SPACING)
    try:
        result = sync_now()
        print(f"  sync: {result}")
    except Exception as exc:
        print(f"  sync GRESKA: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
