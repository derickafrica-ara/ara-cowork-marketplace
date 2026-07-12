"""COND-8 personal "ships-dark" boundary skip (v0.4: dark = ZERO network, R22).

Original defect (v0.3.1): a personal-scope account (Gmail/iCloud) that is
allow-listed but has an EMPTY resolved known-senders list was still enumerated and
only then filtered. The boundary skip fixed that; under v0.4's IMAP transport the
guarantee is even stronger (Floyd R22): a ships-dark personal account triggers NO
IMAP transport call AT ALL — no Keychain read, no DNS, no connection, no auth.
(The Keychain read lives inside PersonalImapDriver.read_personal, so "driver never
invoked" structurally implies "Keychain never read".)

Proof strategy: FakePersonalImapDriver records every read_personal call; the dark
test also arms it to FAIL on any call — so if the boundary skip regressed, the
scan would degrade/raise and the assertions fail loudly.

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
from tests.fakes import FakePersonalImapDriver, FakeReadMailDriver  # noqa: E402

SINCE = "2026-07-11 06:00:00"

ARA_BIZ = "ARA Gmail Biz"
ARA_M365 = "ARA M365"
PERSONAL_ICLOUD = "Personal iCloud"
PERSONAL_GMAIL = "Personal Gmail"
ICLOUD_EMAIL = "derick@icloud.com"
GMAIL_EMAIL = "derick@gmail.com"


def _read_log(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _world():
    # Mail's account list: two ARA business accounts (AppleScript transport) + two
    # personal accounts (IMAP transport) discovered in the SAME Mail.app.
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
        PERSONAL_ICLOUD: {"email": ICLOUD_EMAIL, "messages": []},
        PERSONAL_GMAIL: {"email": GMAIL_EMAIL, "messages": []},
    }


def _imap_world():
    return {
        ICLOUD_EMAIL: [
            ("mom@family.net", "hi", "2026-07-11 07:10:00", "personal — must never be read dark"),
        ],
        GMAIL_EMAIL: [
            ("newsletter@promo.com", "Big sale", "2026-07-11 07:12:00", "personal promo"),
        ],
    }


class TestCond8PersonalShipsDark(unittest.TestCase):
    def setUp(self):
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

    # --- R22: empty known-senders => dark => ZERO IMAP transport calls ----------
    def test_personal_empty_known_senders_dark_zero_imap_calls(self):
        os.environ["APPLE_MAIL_READ_KNOWN_SENDERS"] = ""  # explicitly empty => dark

        # Arm the IMAP fake to FAIL on ANY call: if the boundary skip regressed and
        # a dark personal account reached the transport, the scan would degrade and
        # the assertions below would fail loudly.
        imap = FakePersonalImapDriver(
            _imap_world(),
            fail={ICLOUD_EMAIL: "network", GMAIL_EMAIL: "network"},
        )
        driver = FakeReadMailDriver(_world())
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log, imap_driver=imap)
        msgs = res["messages"]

        # R22 — the IMAP transport was NEVER invoked for a dark account: zero
        # connections, zero Keychain reads (the Keychain read lives inside
        # read_personal, which was never called).
        self.assertEqual(imap.read_calls, [],
                         "REGRESSION: a ships-dark personal account reached the "
                         "IMAP transport (network/Keychain would have been touched)")
        # And the AppleScript transport never saw them either.
        self.assertNotIn(PERSONAL_ICLOUD, driver.read_calls)
        self.assertNotIn(PERSONAL_GMAIL, driver.read_calls)

        # The ARA business accounts WERE read end-to-end and returned.
        self.assertEqual({m["account"] for m in msgs}, {ARA_BIZ, ARA_M365})
        self.assertEqual(len(msgs), 2)
        # Ships-dark is NOT a degradation — clean scan, status ok.
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["accounts_failed"], [])

        # COND-8 audit — the boundary decision is recorded.
        log = _read_log(self.log)
        resolved = next(e for e in log if e["event"] == "read_accounts_resolved")
        read_domains = {a["domain"] for a in resolved["read_accounts"]}
        dark_domains = {a["domain"] for a in resolved["skipped_personal_dark"]}
        self.assertEqual(read_domains, {"ara-data.com", "aradata.onmicrosoft.com"})
        self.assertIn("icloud.com", dark_domains)
        self.assertIn("gmail.com", dark_domains)
        # No IMAP connection audit events exist (nothing connected).
        self.assertNotIn("read_imap_connection", [e["event"] for e in log])

        # C1 discipline — the run-log never leaks a personal sender address.
        raw_log = json.dumps(log)
        self.assertNotIn("mom@family.net", raw_log)
        self.assertNotIn("newsletter@promo.com", raw_log)

    # --- populated known-senders => personal read via IMAP, filtered -------------
    def test_personal_with_known_senders_read_via_imap_and_filtered(self):
        os.environ["APPLE_MAIL_READ_KNOWN_SENDERS"] = "mom@family.net"

        imap = FakePersonalImapDriver(_imap_world())
        driver = FakeReadMailDriver(_world())
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log, imap_driver=imap)
        msgs = res["messages"]

        # The personal accounts ARE read now — via the IMAP transport.
        self.assertEqual(set(imap.read_calls), {ICLOUD_EMAIL, GMAIL_EMAIL})
        # ...and never via AppleScript (routing).
        self.assertNotIn(PERSONAL_ICLOUD, driver.read_calls)
        self.assertNotIn(PERSONAL_GMAIL, driver.read_calls)

        senders = {m["sender"] for m in msgs}
        self.assertIn("mom@family.net", senders)           # known -> kept
        self.assertNotIn("newsletter@promo.com", senders)  # unknown -> dropped
        # ARA business mail still comes through; clean read => ok.
        self.assertIn(ARA_BIZ, {m["account"] for m in msgs})
        self.assertEqual(res["status"], "ok")

        log = _read_log(self.log)
        resolved = next(e for e in log if e["event"] == "read_accounts_resolved")
        self.assertEqual(resolved["skipped_personal_dark"], [],
                         "ships-dark skip must not fire when known-senders is non-empty")

    # --- COND-8 fail-closed is unchanged ------------------------------------------
    def test_empty_allowlist_still_fail_closed(self):
        os.environ["APPLE_MAIL_READ_ALLOWED_ACCOUNTS"] = ""  # explicitly empty
        os.environ["APPLE_MAIL_READ_KNOWN_SENDERS"] = ""

        imap = FakePersonalImapDriver(
            _imap_world(), fail={ICLOUD_EMAIL: "network", GMAIL_EMAIL: "network"}
        )
        driver = FakeReadMailDriver(_world(), timeout_accounts=set(_world().keys()))
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log, imap_driver=imap)

        self.assertEqual(res["messages"], [], "empty allow-list must read NOTHING")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(driver.read_calls, [], "no account may be read when fail-closed")
        self.assertEqual(imap.read_calls, [], "no IMAP connection when fail-closed")
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
        res = read_apple_mail(
            SINCE,
            driver=FakeReadMailDriver(_world()),
            log_path=self.log,
            imap_driver=FakePersonalImapDriver(_imap_world()),
        )
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
        os.environ["APPLE_MAIL_READ_KNOWN_SENDERS"] = ""
        res = read_apple_mail(
            SINCE,
            driver=FakeReadMailDriver(_world()),
            log_path=self.log,
            imap_driver=FakePersonalImapDriver(_imap_world()),
        )
        round_tripped = json.loads(json.dumps(res))  # must not raise
        self.assertEqual(set(round_tripped), set(res))
        self.assertEqual(round_tripped["cutoff"], res["cutoff"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
