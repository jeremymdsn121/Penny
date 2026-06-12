"""Caller for the unattended scan endpoint, run on a schedule by Render Cron.

The scans themselves live in the API (``POST /api/v1/cron/run-scans``, guarded by
the ``CRON_SECRET`` shared secret). This script is the thin client a scheduler
runs: it POSTs to that endpoint with the secret header, prints the JSON summary,
and exits non-zero on any failure so Render marks the run failed (and alerts).

Stdlib only — no dependency on the backend package — so the cron service stays
lean and can't break on an app import.

Env vars:
  CRON_TARGET_URL  full URL of the endpoint (default: the deployed API).
  CRON_SECRET      shared secret; sent as the X-Cron-Secret header. Required.
"""

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "https://api.poweredbypenny.com/api/v1/cron/run-scans"


def main() -> int:
    url = os.environ.get("CRON_TARGET_URL", DEFAULT_URL)
    secret = os.environ.get("CRON_SECRET", "")
    if not secret:
        print("CRON_SECRET is not set — refusing to call the endpoint.", file=sys.stderr)
        return 2

    req = urllib.request.Request(
        url,
        data=b"",  # POST with an empty body
        method="POST",
        headers={"X-Cron-Secret": secret, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8", "replace")
            print(f"{resp.status} {url}")
            print(body)
            return 0
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        print(f"HTTP {exc.code} from {url}: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Could not reach {url}: {exc.reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
