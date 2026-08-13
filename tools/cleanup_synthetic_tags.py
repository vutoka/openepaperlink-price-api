#!/usr/bin/env python3
"""Remove the synthetic tags a scale test left in the AP's database.

`make_synthetic_tagdb.py` loads fabricated tags into the AP so the software
can be exercised at store scale without owning hundreds of tags. They have to
come back out afterwards, or the tag list fills with records that will never
check in and a real dead tag stops standing out.

Restoring a clean database would be the obvious way, but `/restore_db` is not
usable for this: an interrupted upload leaves `fsMutex` taken and every later
restore silently does nothing while still answering 200. And a reboot does not
help either -- the AP autosaves its database to flash every five minutes
(`main.cpp:39`) and reloads it on boot (`main.cpp:143`), so synthetic records
survive a power cycle.

What does work is the per-tag delete the web UI uses, `POST /tag_cmd` with
`cmd=del` (`web.cpp:583`). No reboot, no reflash, no interruption to the
shelves.

Only MACs carrying the `FF` prefix that `make_synthetic_tagdb.py` assigns are
touched. `cmd=purge` (`web.cpp:594`) would be one call instead of many, but it
deletes everything not seen in 24 hours, which would take real tags that are
merely idle -- so it is deliberately not used.

Usage:
    python cleanup_synthetic_tags.py            # show what would go
    python cleanup_synthetic_tags.py --delete   # actually delete
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from make_synthetic_tagdb import AP_WEB_URL, SYNTHETIC_PREFIX, fetch_real_tags

# The AP's price API rate-limits and its web handlers are single-threaded;
# deleting several hundred records back to back is not worth the risk of
# starving the radio task, and this runs rarely.
DELETE_PAUSE = 0.4

# An AP carrying a few dozen tags it can never reach gets slow and loses
# packets -- contentRunner keeps trying to render for records that will never
# check in. Which is the state this script exists to clean up, so it has to
# work over exactly that flaky link rather than assume a healthy one.
ATTEMPTS = 4
HTTP_TIMEOUT = 30.0


def delete_tag(base_url: str, mac: str) -> str | None:
    """Delete one record. Returns None on success or a short error string.

    Deleting is idempotent from our side -- a MAC that is already gone answers
    "mac not found" with a 200 -- so retrying a timeout is safe.
    """
    body = urllib.parse.urlencode({"mac": mac, "cmd": "del"}).encode("utf-8")
    last = "nije pokusano"
    for attempt in range(ATTEMPTS):
        request = urllib.request.Request(
            f"{base_url}/tag_cmd",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                response.read()
                return None
        except urllib.error.HTTPError as exc:
            return f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = str(exc)
            time.sleep(1.0 + attempt)
    return last


def fetch_with_retry(base_url: str):
    """fetch_real_tags, but tolerant of the flakiness described above."""
    last: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            return fetch_real_tags(base_url, timeout=HTTP_TIMEOUT)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last = exc
            time.sleep(2.0 + 2 * attempt)
    raise last if last else RuntimeError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ap", default=AP_WEB_URL, help="AP web base URL")
    parser.add_argument("--delete", action="store_true",
                        help="actually delete; without it this only reports")
    args = parser.parse_args()

    try:
        tags = fetch_with_retry(args.ap)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"cannot read the AP at {args.ap}: {exc}", file=sys.stderr)
        return 1

    synthetic = [t for t in tags
                 if str(t.get("mac", "")).upper().startswith(SYNTHETIC_PREFIX)]
    real = [t for t in tags
            if not str(t.get("mac", "")).upper().startswith(SYNTHETIC_PREFIX)]

    print(f"u bazi AP-a: {len(tags)} tagova "
          f"({len(real)} pravih, {len(synthetic)} sintetickih)")

    if not synthetic:
        print("nema sta da se brise.")
        return 0

    if not args.delete:
        print("\nobrisalo bi se:")
        for tag in synthetic:
            print(f"  {tag['mac']}  alias={tag.get('alias','')}")
        print("\npokreni ponovo sa --delete da se stvarno obrise.")
        return 0

    print()
    failed: list[tuple[str, str]] = []
    for tag in synthetic:
        mac = str(tag["mac"]).upper()
        error = delete_tag(args.ap, mac)
        if error:
            failed.append((mac, error))
            print(f"  GRESKA {mac}: {error}")
        else:
            print(f"  obrisan {mac}")
        time.sleep(DELETE_PAUSE)

    # Read the database back rather than trusting the responses: the AP has
    # more than one endpoint that answers 200 without having done anything.
    print()
    after = fetch_with_retry(args.ap)
    left = [t for t in after
            if str(t.get("mac", "")).upper().startswith(SYNTHETIC_PREFIX)]
    print(f"posle brisanja: {len(after)} tagova, od toga {len(left)} sintetickih")

    for tag in after:
        print(f"  {tag['mac']}  hwType={tag.get('hwType')} "
              f"mode={tag.get('contentMode')} cfg={tag.get('modecfgjson','')[:50]}")

    if failed or left:
        print(f"\nNIJE CISTO: {len(failed)} gresaka, {len(left)} preostalih",
              file=sys.stderr)
        return 1

    print("\nCisto. Sacekaj 5 minuta da autosave (main.cpp:39) upise ovo u "
          "fles, pa proveri jos jednom -- do tada bi reboot vratio stare zapise.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
