#!/usr/bin/env python3
"""WS4 — install / first-run smoke: read_apple_mail returns the documented dict
shape and is JSON-serializable.

Closes the MCP-serialization verification gap Floyd flagged: the MCP layer
serializes the tool's return value to JSON, so a non-serializable field would only
surface over the wire. This smoke asserts the shape + a json round-trip.

It runs WITHOUT the live MCP SDK and WITHOUT touching Apple Mail (a tiny in-process
fake driver stands in) and WITHOUT writing the real scan-status marker or run-log
(both redirected to a temp dir). Exit 0 = PASS, 1 = FAIL.

Run at install / first run:
    python3 ara-business-pulse/scripts/smoke_read_shape.py

The first REAL pulse run additionally exercises the live server.py -> FastMCP path
against Apple Mail; this smoke is the fast, offline pre-check.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APPLE_MAIL = os.path.normpath(os.path.join(HERE, "..", "apple-mail"))
sys.path.insert(0, APPLE_MAIL)

os.environ.setdefault("APPLE_MAIL_READ_ALLOWED_ACCOUNTS", "ara-data.com")
os.environ["APPLE_MAIL_READ_KNOWN_SENDERS"] = ""  # deterministic; personal ships dark

from read_core import MailAccount, ReadMailDriver, read_apple_mail  # noqa: E402

DOCUMENTED_KEYS = {
    "status", "messages", "accounts_read", "accounts_failed", "accounts_capped",
    "accounts_skipped_dark", "cutoff",
}


class _FakeDriver(ReadMailDriver):
    """Stand-in for Apple Mail — one ARA account, one message. No osascript.
    read_inbox returns (records, saturated) — the current driver contract."""

    def list_accounts(self):  # type: ignore[override]
        return [MailAccount(name="ARA", email="derick@ara-data.com")]

    def read_inbox(self, account_name, cutoff):  # type: ignore[override]
        return [("client@ara-data.com", "Subject", "2026-07-11 07:00:00", "body text")], False


def main() -> int:
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

    # Confirm the MCP tool module is importable where the SDK is installed (the
    # live serialization path); absence is fine offline — the shape is validated.
    try:
        import server  # noqa: F401
        print("[info] MCP tool module imports (SDK present).")
    except Exception as exc:  # SDK not installed in this env
        print(f"[info] MCP SDK not importable here ({exc.__class__.__name__}); "
              "shape validated via read_core.")

    print("PASS: read_apple_mail returns the documented, JSON-serializable shape."
          if ok else "SMOKE FAILED.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
