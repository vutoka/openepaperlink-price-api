#!/usr/bin/env python3
"""Manage the tag_mac -> sku mapping used by the ESL gateway.

The mapping is tag-centric, not shelf-centric: if a product moves shelves and
its tag moves with it, nothing here needs to change. Only re-pair when a
*different* tag should show a given SKU.

Usage:
    python tools/tag_mapping.py add <tag_mac> <sku> [--note "text"]
    python tools/tag_mapping.py remove <tag_mac>
    python tools/tag_mapping.py list
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.getenv("GATEWAY_DB_PATH", os.path.join(os.path.dirname(__file__), "gateway.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS tag_mapping (
    tag_mac TEXT PRIMARY KEY,
    sku TEXT NOT NULL,
    paired_at TEXT NOT NULL,
    note TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    return conn


def cmd_add(args: argparse.Namespace) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO tag_mapping (tag_mac, sku, paired_at, note)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(tag_mac) DO UPDATE SET
                sku = excluded.sku,
                paired_at = excluded.paired_at,
                note = excluded.note
            """,
            (args.tag_mac, args.sku, now_iso(), args.note),
        )
    print(f"paired {args.tag_mac} -> {args.sku}")


def cmd_remove(args: argparse.Namespace) -> None:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM tag_mapping WHERE tag_mac = ?", (args.tag_mac,))
    if cursor.rowcount == 0:
        print(f"no mapping found for {args.tag_mac}")
    else:
        print(f"removed mapping for {args.tag_mac}")


def cmd_list(_args: argparse.Namespace) -> None:
    with connect() as conn:
        rows = conn.execute(
            "SELECT tag_mac, sku, paired_at, note FROM tag_mapping ORDER BY paired_at"
        ).fetchall()
    if not rows:
        print("no mappings yet")
        return
    for tag_mac, sku, paired_at, note in rows:
        suffix = f"  # {note}" if note else ""
        print(f"{tag_mac}  ->  {sku}   (paired {paired_at}){suffix}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="pair a tag with a SKU (or repair it)")
    add_parser.add_argument("tag_mac")
    add_parser.add_argument("sku")
    add_parser.add_argument("--note", default=None)
    add_parser.set_defaults(func=cmd_add)

    remove_parser = subparsers.add_parser("remove", help="remove a tag's mapping")
    remove_parser.add_argument("tag_mac")
    remove_parser.set_defaults(func=cmd_remove)

    list_parser = subparsers.add_parser("list", help="list all mappings")
    list_parser.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
