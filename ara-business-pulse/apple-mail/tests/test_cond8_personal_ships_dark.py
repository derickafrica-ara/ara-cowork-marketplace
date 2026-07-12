"""COND-8 personal "ships-dark" boundary skip — the regression this fix removes.

Defect (v0.3.1): a personal-scope account (Gmail/iCloud) that is allow-listed but
has an EMPTY resolved known-senders list was still ENUMERATED by read_inbox() and
only THEN filtered in Python. On a large iCloud inbox the enumeration exceeds the
90s ReadMailDriver timeout -> ReadMailError (COND-5 fail-loud) -> the WHOLE scan
dies before it ever reaches the ARA mailboxes.

Fix: skip such an account AT THE ACCOUNT BOUNDARY (like a non-allow-listed
account) — driver.read_inbox() is never called for it — so it cannot time out.

Proof strategy: FakeReadMailDriver records every account read_inbox() is called
on (`read_calls`), and can be told to raise a modeled timeout for the personal
accounts. So a green run proves the personal inbox was never touched AND that the
scan still completes for the ARA accounts.

Hermeticity: read_known_senders_with_source() reads a HARDCODED local file first
(~/.ara-business-pulse/known-senders.txt). Tests patch config.KNOWN_SENDERS_FILE
to a non-existent path so the machine's real file can never leak into the run and
the "empty known-senders" state is deterministic.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from read_core import read_apple_mail  # noqa: E402
from tests.fakes import FakeReadMailDriver  # noqa: E402

SINCE = "2026-07-11 06:00:00"

ARA_BIZ = "ARA Gmail Biz"
ARA_M365 = "ARA M365"
PERSONAL_ICLOUD = "Personal iCloud"
PERSONAL_GMAIL = "Personal Gmail"


def _read_log(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _world():
    # Two ARA business accounts (full-inbox scope) + two personal accounts
    # (Gmail + iCloud, known-senders scope) in the SAME Mail.app.
    return {
        ARA_BIZ: {
            "email": "derick@ara-data.com",
            "messages": [
                ("client@acme.com", "Q3 numbers", "2026-07-11 07:00:00", "real ara body one"),
            ],
        },
        ARA_M365: {
            "email": "derick@aradata.onmicrosoft.com",
            "messages": [
                ("vendor@example.com", "Invoice 42", "2026-07-11 07:05:00", "real ara body two"),
            ],
        },
        PERSONAL_ICLOUD: {
            "email": "derick@icloud.com",
            "messages": [
                ("mom@family.net", "hi", "2026-07-11 07:10:00", "personal — must never be enumerated"),
            ],
        },
        PERSONAL_GMAIL: {
            "email": "derick@gmail.com",
            "messages": [
                ("newsletter@promo.com", "Big sale", "2026-07-11 07:12:00", "personal promo"),
            ],
        },
    }


class TestCond8PersonalShipsDark(unittest.TestCase):
    def setUp(self):
        # v0.3.1 shipping config: ARA + personal domains allow-listed; Gmail/iCloud
        # are personal-scope.
        os.environ["APPLE_MAIL_READ_ALLOWED_ACCOUNTS"] = (
            "ara-data.com,aradata.onmicrosoft.com,gmail.com,me.com,icloud.com"
        )
        os.environ["APPLE_MAIL_READ_PERSONAL_DOMAINS"] = "gmail.com,me.com,icloud.com"
        # Neutralize the hardcoded local known-senders FILE so tests control the
        # known-senders state purely via the env var (file source -> absent).
        self._file_patch = mock.patch.object(
            config, "KNOWN_SENDERS_FILE", "/nonexistent/ara-tests/known-senders.txt"
        )
        self._file_patch.start()
        fd, self.log = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.remove(self.log)
        # Redirect the last-scan marker to a temp dir (never write the real dir).
        # The path is NON-overridable via env now, so patch the module default; the
        # basename MUST be the real marker name (the N-C clobber guard refuses others).
        self.status_dir = tempfile.mkdtemp()
        self.status = os.path.join(self.status_dir, config.SCAN_STATUS_BASENAME)
        self._status_patch = mock.patch.object(config, "DEFAULT_SCAN_STATUS_FILE", self.status)
        self._status_patch.start()

    def tearDown(self):
        for var in (
            "APPLE_MAIL_READ_ALLOWED_ACCOUNTS",
            "APPLE_MAIL_READ_PERSONAL_DOMAINS",
            "APPLE_MAIL_READ_KNOWN_SENDERS",
        ):
            os.environ.pop(var, None)
        self._file_patch.stop()
        self._status_patch.stop()
        if os.path.exists(self.log):
            os.remove(self.log)
        if os.path.exists(self.status):
            os.remove(self.status)
        if os.path.isdir(self.status_dir):
            os.rmdir(self.status_dir)

    # --- SC1 + SC2 + SC3: empty known-senders => personal skipped at boundary ---
    def test_personal_empty_known_senders_skipped_at_boundary_not_enumerated(self):
        os.environ["APPLE_MAIL_READ_KNOWN_SENDERS"] = ""  # explicitly empty => dark

        # If the boundary skip regressed and a personal inbox WERE enumerated, the
        # modeled timeout would raise and kill the whole scan (reproducing the bug).
        driver = FakeReadMailDriver(
            _world(), timeout_accounts={PERSONAL_ICLOUD, PERSONAL_GMAIL}
        )
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log)
        msgs = res["messages"]

        # SC1 — read_inbox() was NEVER called for either personal account.
        self.assertNotIn(PERSONAL_ICLOUD, driver.read_calls,
                         "REGRESSION: personal iCloud inbox was enumerated")
        self.assertNotIn(PERSONAL_GMAIL, driver.read_calls,
                         "REGRESSION: personal Gmail inbox was enumerated")

        # SC2 — the ARA business accounts WERE read end-to-end and returned.
        self.assertIn(ARA_BIZ, driver.read_calls)
        self.assertIn(ARA_M365, driver.read_calls)
        self.assertEqual({m["account"] for m in msgs}, {ARA_BIZ, ARA_M365})
        self.assertEqual(len(msgs), 2)
        for m in msgs:
            self.assertNotIn("personal", m["body"])
        # Ships-dark is NOT a degradation — no account timed out, so status is ok.
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["accounts_failed"], [])

        # SC3 (COND-8 audit) — the boundary decision is recorded: personal accounts
        # under skipped_personal_dark, ARA accounts under read_accounts.
        log = _read_log(self.log)
        resolved = next(e for e in log if e["event"] == "read_accounts_resolved")
        read_domains = {a["domain"] for a in resolved["read_accounts"]}
        dark_domains = {a["domain"] for a in resolved["skipped_personal_dark"]}
        self.assertEqual(read_domains, {"ara-data.com", "aradata.onmicrosoft.com"})
        self.assertIn("icloud.com", dark_domains)
        self.assertIn("gmail.com", dark_domains)

        # C1 discipline — the run-log never leaks a personal sender address.
        raw_log = json.dumps(log)
        self.assertNotIn("mom@family.net", raw_log)
        self.assertNotIn("newsletter@promo.com", raw_log)

    # --- regression guard: non-empty known-senders path is UNCHANGED ------------
    def test_personal_with_known_senders_still_enumerated_and_filtered(self):
        # A populated known-senders list turns the personal path on; the skip must
        # NOT fire, the personal inbox IS enumerated, and the per-message filter
        # keeps known senders / drops unknown ones (the intended feature).
        os.environ["APPLE_MAIL_READ_KNOWN_SENDERS"] = "mom@family.net"

        driver = FakeReadMailDriver(_world())  # no modeled timeout: reads allowed
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log)
        msgs = res["messages"]

        # The personal accounts ARE enumerated now (skip does not fire).
        self.assertIn(PERSONAL_ICLOUD, driver.read_calls)
        self.assertIn(PERSONAL_GMAIL, driver.read_calls)

        senders = {m["sender"] for m in msgs}
        self.assertIn("mom@family.net", senders)         # known -> kept
        self.assertNotIn("newsletter@promo.com", senders)  # unknown -> dropped
        # ARA business mail still comes through; clean read (no timeouts) => ok.
        self.assertIn(ARA_BIZ, {m["account"] for m in msgs})
        self.assertEqual(res["status"], "ok")

        log = _read_log(self.log)
        resolved = next(e for e in log if e["event"] == "read_accounts_resolved")
        self.assertEqual(resolved["skipped_personal_dark"], [],
                         "ships-dark skip must not fire when known-senders is non-empty")

    # --- COND-8 fail-closed is unchanged by this fix ----------------------------
    def test_empty_allowlist_still_fail_closed(self):
        os.environ["APPLE_MAIL_READ_ALLOWED_ACCOUNTS"] = ""  # explicitly empty
        os.environ["APPLE_MAIL_READ_KNOWN_SENDERS"] = ""

        # timeout on every account: if anything were read, the scan would blow up.
        driver = FakeReadMailDriver(
            _world(), timeout_accounts=set(_world().keys())
        )
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log)

        self.assertEqual(res["messages"], [], "empty allow-list must read NOTHING")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(driver.read_calls, [], "no account may be read when fail-closed")
        # Fail-closed short-circuits BEFORE even enumerating accounts.
        self.assertEqual(driver.list_accounts_calls, 0)
        events = [e["event"] for e in _read_log(self.log)]
        self.assertIn("read_fail_closed", events)

    # --- N1: the documented return dict-shape contract (in-process smoke) --------
    def test_read_returns_documented_dict_shape(self):
        # Closes the return-contract shape at the read core. NOTE: the end-to-end
        # MCP serialization over the live SDK (server.py -> FastMCP) is NOT covered
        # here (the read suite runs without the MCP SDK) — that remains a documented
        # install/first-run follow-up.
        os.environ["APPLE_MAIL_READ_KNOWN_SENDERS"] = ""  # ships dark, clean read
        driver = FakeReadMailDriver(_world())
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log)
        self.assertEqual(
            set(res),
            {"status", "messages", "accounts_read", "accounts_failed",
             "accounts_capped", "accounts_skipped_dark", "cutoff"},
        )
        self.assertIn(res["status"], ("ok", "partial"))
        self.assertIsInstance(res["messages"], list)
        self.assertIsInstance(res["accounts_read"], list)
        self.assertIsInstance(res["accounts_failed"], list)
        self.assertIsInstance(res["accounts_skipped_dark"], list)

    # --- WS4: the result is JSON-serializable (closes the MCP-serialization risk) -
    def test_read_result_is_json_serializable(self):
        # The MCP layer serializes the return value to JSON. A non-serializable
        # field would only surface over the wire; assert round-trip here so it can't.
        os.environ["APPLE_MAIL_READ_KNOWN_SENDERS"] = ""
        driver = FakeReadMailDriver(_world())
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log)
        round_tripped = json.loads(json.dumps(res))  # must not raise
        self.assertEqual(set(round_tripped), set(res))
        self.assertEqual(round_tripped["cutoff"], res["cutoff"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
