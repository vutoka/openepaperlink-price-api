#!/usr/bin/env python3
"""Read the AP's live system counters (heap, tag count, DB size, PSRAM).

The AP only publishes these over its WebSocket (`wsSendSysteminfo`,
`web.cpp:256`) -- `/sysinfo` carries the static build facts and nothing about
runtime memory. Scale testing needs the runtime numbers, so this speaks just
enough of RFC 6455 to connect, read text frames, and pick out the `sys`
object. No dependency worth adding for a read-only probe.

Usage:
    python ap_stats.py                 # one reading
    python ap_stats.py --watch 60      # keep reading for 60 seconds
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import sys
import time
from urllib.parse import urlparse

from make_synthetic_tagdb import AP_WEB_URL


def connect(url: str, timeout: float) -> socket.socket:
    parsed = urlparse(url)
    host = parsed.hostname or "192.168.0.34"
    port = parsed.port or 80

    sock = socket.create_connection((host, port), timeout=timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    handshake = (
        f"GET /ws HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(handshake.encode())

    # Read until the end of the response headers.
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("AP closed the connection during handshake")
        buffer += chunk
    if b"101" not in buffer.split(b"\r\n", 1)[0]:
        raise ConnectionError(f"handshake refused: {buffer.split(chr(13).encode())[0]!r}")
    return sock


def read_frame(sock: socket.socket) -> str | None:
    """Return the payload of the next text frame, or None for anything else.

    Server-to-client frames are never masked, and the AP sends its status as
    small text frames, so the long-payload and mask paths stay simple.
    """
    header = sock.recv(2)
    if len(header) < 2:
        raise ConnectionError("connection closed")
    opcode = header[0] & 0x0F
    masked = bool(header[1] & 0x80)
    length = header[1] & 0x7F

    if length == 126:
        length = struct.unpack(">H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", sock.recv(8))[0]

    mask = sock.recv(4) if masked else b""

    payload = b""
    while len(payload) < length:
        chunk = sock.recv(length - len(payload))
        if not chunk:
            raise ConnectionError("connection closed mid-frame")
        payload += chunk

    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

    if opcode == 0x8:  # close
        raise ConnectionError("AP closed the websocket")
    if opcode != 0x1:  # not text
        return None
    return payload.decode("utf-8", "replace")


def read_sys(sock: socket.socket, deadline: float) -> dict | None:
    """Wait for the next frame carrying a `sys` object."""
    while time.time() < deadline:
        try:
            text = read_frame(sock)
        except (socket.timeout, TimeoutError):
            return None
        if not text:
            continue
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and "sys" in message:
            return message["sys"]
    return None


def show(sys_obj: dict) -> None:
    heap = sys_obj.get("heap")
    psfree = sys_obj.get("psfree")
    print(
        f"tagova={sys_obj.get('recordcount')}  "
        f"dbsize={sys_obj.get('dbsize')}  "
        f"heap={heap:,} B" .replace(",", ".") if heap else f"heap={heap}",
        end="",
    )
    print(
        f"  psram_free={psfree}  "
        f"littlefs_free={sys_obj.get('littlefsfree')}  "
        f"apstate={sys_obj.get('apstate')}  "
        f"runstate={sys_obj.get('runstate')}  "
        f"rssi={sys_obj.get('rssi')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ap", default=AP_WEB_URL)
    parser.add_argument("--watch", type=float, default=0,
                        help="keep reading for this many seconds")
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args()

    try:
        sock = connect(args.ap, args.timeout)
    except (OSError, ConnectionError) as exc:
        print(f"cannot reach the AP websocket: {exc}", file=sys.stderr)
        return 1
    sock.settimeout(args.timeout)

    try:
        deadline = time.time() + max(args.watch, args.timeout)
        first = read_sys(sock, deadline)
        if first is None:
            print("AP did not send a sys frame in time", file=sys.stderr)
            return 1
        show(first)

        if args.watch:
            stop = time.time() + args.watch
            while time.time() < stop:
                sys_obj = read_sys(sock, stop)
                if sys_obj is None:
                    break
                show(sys_obj)
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
