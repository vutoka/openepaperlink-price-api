#!/usr/bin/env python3
"""Build a tagDB file for the AP's POST /restore_db, for scale testing.

Why this exists
---------------
The one thing we cannot buy our way out of is not knowing how the system
behaves with a few hundred tags instead of three. Most of that risk is not in
the radio at all -- it is in the AP holding the records, in `/get_db` paging
them out, and in the gateway reading them back. All of that can be exercised
with tags that do not exist.

The AP stores its tag database as a JSON file that `loadDB` (tag_db.cpp:175)
parses, and `POST /restore_db` (web.cpp:1223) is the supported way to hand it
one. The format is an array of one-element arrays:

    [[{tag}],[{tag}],...]

which is exactly what `saveDB` (tag_db.cpp:154-168) writes, and the field
names match `fillNode`, so records read straight out of `GET /get_db` can be
fed back in unchanged.

The dangerous part
------------------
`/restore_db` calls `destroyDB()` before `loadDB()`. Whatever is not in the
file we upload is gone -- including `modecfgjson`, which is what tells a real
tag what to render. Losing it on a shelf tag means a blank shelf.

So this script never writes a file from scratch. It reads the live AP first
and carries every real record through verbatim; the synthetic tags are only
ever appended. Restoring the output therefore leaves the real tags exactly as
they are.

Usage
-----
    # 400 synthetic tags on top of whatever the AP currently knows
    python make_synthetic_tagdb.py --count 400 --out fake400.json

    # just the real tags, i.e. a restore-shaped backup
    python make_synthetic_tagdb.py --count 0 --out backup.json

    # upload it (or use the web UI's restore button)
    curl -F "file=@fake400.json" http://192.168.0.34/restore_db

Synthetic MACs use the 0xFF prefix so they are impossible to confuse with real
hardware and can be removed again by filtering on it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

AP_WEB_URL = "http://192.168.0.34"

# Real OpenEPaperLink MACs we have seen all start 0x0000 01/02. Synthetic ones
# start 0xFF so a glance at the tag list tells you which is which, and so
# --strip can find them again without a separate bookkeeping file.
SYNTHETIC_PREFIX = "FF"

# hwType 17 is the 2.9" tag our price API supports; anything else and the AP
# would refuse the push for a reason that has nothing to do with scale.
SYNTHETIC_HWTYPE = 17


def fetch_real_tags(base_url: str, timeout: float = 15.0) -> list[dict]:
    """Every record the AP currently holds, following `continu` to the end.

    `/get_db` caps a response at ~5000 bytes and reports where to resume in
    `continu`. Reading only the first page is the bug this whole exercise is
    about, so this function does not repeat it.
    """
    tags: list[dict] = []
    seen_macs: set[str] = set()
    pos = 0
    # The AP truncates ?pos= to a uint8_t (web.cpp:477), so positions above 255
    # silently wrap to 0. Guard the loop rather than spin forever.
    for _ in range(64):
        url = f"{base_url}/get_db?pos={pos}"
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))

        page = payload.get("tags", [])
        fresh = [t for t in page if str(t.get("mac", "")).upper() not in seen_macs]
        if not fresh:
            break
        for tag in fresh:
            seen_macs.add(str(tag.get("mac", "")).upper())
        tags.extend(fresh)

        nxt = payload.get("continu")
        if not nxt or int(nxt) <= pos:
            break
        pos = int(nxt)
        if pos > 255:
            print(
                f"  ! AP cannot be asked for position {pos}: /get_db truncates "
                f"?pos= to a uint8_t, so it would restart from 0. "
                f"Stopping at {len(tags)} tags.",
                file=sys.stderr,
            )
            break

    return tags


def synthetic_tag(index: int, now: int) -> dict:
    """One plausible tag record.

    The values matter less than their shape -- `loadDB` reads every field, and
    a record that parses is a record that occupies memory and JSON bytes,
    which is what we are measuring. `lastseen`/`nextcheckin` are set so the AP
    treats it as a tag that checked in recently rather than a dead one.
    """
    mac = f"{SYNTHETIC_PREFIX}0000{index:010X}"[:16].upper()
    return {
        "mac": mac,
        "hash": "00000000000000000000000000000000",
        "lastseen": now - 30,
        "nextupdate": 0,
        "nextcheckin": now + 60,
        "pending": 0,
        "alias": f"TEST-{index:04d}",
        "contentMode": 0,
        "LQI": 100,
        "RSSI": -60,
        "temperature": 22,
        "batteryMv": 2900,
        "hwType": SYNTHETIC_HWTYPE,
        "wakeupReason": 0,
        "capabilities": 0,
        "modecfgjson": "{}",
        "isexternal": False,
        "apip": "0.0.0.0",
        "rotate": 0,
        "lut": 0,
        "invert": 0,
        "updatecount": 1,
        "updatelast": now - 30,
        "ch": 11,
        "ver": 0,
    }


def write_db(path: str, records: list[dict]) -> int:
    """Write the [[{...}],[{...}]] shape loadDB expects and return byte size."""
    wrapped = [[record] for record in records]
    body = json.dumps(wrapped, indent=1)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return len(body.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=400,
                        help="how many synthetic tags to append (0 = backup only)")
    parser.add_argument("--out", default="synthetic_tagdb.json",
                        help="file to write")
    parser.add_argument("--ap", default=AP_WEB_URL,
                        help="AP web base URL")
    parser.add_argument("--offline", action="store_true",
                        help="do not contact the AP; write synthetic tags only. "
                             "Restoring such a file DESTROYS the real records.")
    parser.add_argument("--strip", action="store_true",
                        help="write only the real tags, dropping synthetic ones "
                             "(this is how you undo a scale test)")
    args = parser.parse_args()

    now = int(time.time())

    real: list[dict] = []
    if not args.offline:
        try:
            real = fetch_real_tags(args.ap)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"could not read the AP at {args.ap}: {exc}", file=sys.stderr)
            print("refusing to write a file that would wipe the real tags; "
                  "pass --offline if that is genuinely what you want.",
                  file=sys.stderr)
            return 1

    if args.strip:
        kept = [t for t in real
                if not str(t.get("mac", "")).upper().startswith(SYNTHETIC_PREFIX)]
        size = write_db(args.out, kept)
        print(f"wrote {len(kept)} real tags to {args.out} ({size} bytes)")
        print("restore this to remove the synthetic tags from the AP.")
        return 0

    synthetic = [synthetic_tag(i, now) for i in range(1, args.count + 1)]
    records = real + synthetic
    size = write_db(args.out, records)

    print(f"real tags carried through : {len(real)}")
    print(f"synthetic tags appended   : {len(synthetic)}")
    print(f"total records             : {len(records)}")
    print(f"file                      : {args.out} ({size} bytes)")
    if real:
        macs = ", ".join(str(t.get("mac")) for t in real)
        print(f"preserved: {macs}")
    else:
        print("! no real tags in this file -- restoring it wipes the AP's tag DB")
    print()
    print(f"upload with:  curl -F \"file=@{args.out}\" {args.ap}/restore_db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
