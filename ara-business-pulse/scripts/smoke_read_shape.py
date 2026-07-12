#!/usr/bin/env python3
"""WS4 — install / first-run smoke for the apple-mail read path.

DEFAULT (offline) mode closes the MCP-serialization gap: read_apple_mail returns
the documented dict shape and is JSON-serializable (the MCP layer serializes the
return to JSON, so a non-serializable field would only surface over the wire). It
runs WITHOUT the live MCP SDK and WITHOUT touching Apple Mail (a tiny in-process
fake) and WITHOUT writing the real marker/run-log (temp dir).

--live mode (Derick runs this post-publish; NEEDS real Mail + TCC) is the cap's
ordering/completeness/SPEED probe (R-SAFE):
  * SPEED — times a real read; the ~90s per-account timeout should be gone.
  * ORDERING/COMPLETENESS — prints messages-by-account; if newest-end detection were
    wrong, personal accounts would read OLD messages and return ZERO recent mail, so
    a personal account showing 0 (when recent mail exists) flags an ordering problem.
  * No per-account timeout (accounts_failed empty) is the primary PASS signal.
It uses a recent (3-day) cutoff and temp marker/log paths (never the real marker).

Run:
    python3 ara-business-pulse/scripts/smoke_read_shape.py            # offline
    python3 ara-business-pulse/scripts/smoke_read_shape.py --live     # on Derick's Mac

Exit 0 = PASS, 1 = FAIL/CHECK.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
APPLE_MAIL = os.path.normpath(os.path.join(HERE, "..", "apple-mail"))
sys.path.insert(0, APPLE_MAIL)

from read_core import MailAccount, ReadMailDriver, read_apple_mail  # noqa: E402

DOCUMENTED_KEYS = {
    "status", "messages", "accounts_read", "accounts_failed", "accounts_capped",
    "accounts_skipped_dark", "cutoff",
}


class _FakeDriver(ReadMailDriver):
    """Stand-in for Apple Mail — one ARA account, one message. No osascript.
    read_inbox returns (records, examined, saw_out_of_window, total)."""

    def list_accounts(self):  # type: ignore[override]
        return [MailAccount(name="ARA", email="derick@ara-data.com")]

    def read_inbox(self, account_name, cutoff):  # type: ignore[override]
        recs = [("client@ara-data.com", "Subject", "2026-07-11 07:00:00", "body text")]
        return recs, len(recs), True, len(recs)  # examined, saw_out_of_window, total


def offline() -> int:
    os.environ.setdefault("APPLE_MAIL_READ_ALLOWED_ACCOUNTS", "ara-data.com")
    os.environ["APPLE_MAIL_READ_KNOWN_SENDERS"] = ""  # deterministic; personal dark
    tmp = tempfile.mkdtemp()
    res = read_apple_mail(
        "2026-07-11 06:00:00",
        driver=_FakeDriver(),
        log_path=os.path.join(tmp, "log.jsonl"),
        status_path=os.path.join(tmp, "last-scan-status.json"),  # never the real marker
    )
    ok = True
    if set(res) != DOCUMENTED_KEYS:
        print(f"FAIL: keys {sorted(set(res))} != {sorted(DOCUMENTED_KEYS)}")
        ok = False
    try:
        json.loads(json.dumps(res))  # serialization round-trip (the MCP-wire check)
    except (TypeError, ValueError) as exc:
        print(f"FAIL: result is not JSON-serializable: {exc}")
        ok = False
    try:
        import server  # noqa: F401
        print("[info] MCP tool module imports (SDK present).")
    except Exception as exc:
        print(f"[info] MCP SDK not importable here ({exc.__class__.__name__}); "
              "shape validated via read_core.")
    print("PASS: read_apple_mail returns the documented, JSON-serializable shape."
          if ok else "SMOKE FAILED.")
    return 0 if ok else 1


def live() -> int:
    """Real read against Apple Mail — SPEED + ordering/completeness (R-SAFE)."""
    since = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    tmp = tempfile.mkdtemp()
    t0 = time.monotonic()
    res = read_apple_mail(  # real ReadMailDriver; temp paths => no real marker/log
        since,
        log_path=os.path.join(tmp, "log.jsonl"),
        status_path=os.path.join(tmp, "last-scan-status.json"),
    )
    elapsed = time.monotonic() - t0
    by_acct = Counter(m["account"] for m in res["messages"])
    print(f"[live] elapsed={elapsed:.1f}s  status={res['status']}  since={since}")
    print(f"[live] accounts_read   = {res['accounts_read']}")
    print(f"[live] accounts_failed = {[f['account'] for f in res['accounts_failed']]}")
    print(f"[live] accounts_capped = {[c['account'] for c in res['accounts_capped']]}")
    print(f"[live] messages_by_account = {dict(by_acct)}  (total {len(res['messages'])})")
    print("[live] ORDERING/COMPLETENESS: a personal account showing 0 messages when "
          "you expect recent known-sender mail would indicate a newest-end/ordering "
          "problem — eyeball the per-account counts above.")
    # Primary PASS: no per-account read timed out or stalled (the 90s bug is gone).
    ok = not res["accounts_failed"]
    print("PASS: real read completed with no per-account timeout/stall." if ok else
          "CHECK: a per-account read failed (timeout/stall) — see accounts_failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(live() if "--live" in sys.argv[1:] else offline())
