"""COND-5 max-availability across BOTH transports (v0.4): per-account failures
degrade; systemic/wipeout fails loud; capped is surfaced; a partial is never
presented as clean.

v0.4 routing (COND-8 v0.4): ARA business accounts read via the AppleScript
transport (FakeReadMailDriver); PERSONAL domains read via the direct-IMAP
transport (FakePersonalImapDriver). Account DISCOVERY still comes from Mail's
account list (list_accounts) for all four accounts.

Failure kinds (Ruling 2): AppleScript timeout/stall degrade the ARA account;
IMAP credential_missing / auth_failed / network / timeout degrade the personal
account. All ride accounts_failed -> marker -> banner. Zero accounts succeeded
=> wipeout raise. list_accounts failure => systemic raise.

Hermeticity: the known-senders FILE source is a temp file of FAKE domains (never
Derick's real 379-sender file); the marker is redirected to a temp dir; the IMAP
fake never touches network/Keychain/imaplib.
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
from read_core import ReadMailError, _write_scan_status, read_apple_mail  # noqa: E402
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
    """Mail's account list (drives discovery for ALL accounts) + the ARA
    accounts' AppleScript messages. Personal messages live in _imap_world()."""
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
    """The personal accounts' provider-side messages, keyed by account EMAIL."""
    return {
        ICLOUD_EMAIL: [
            ("known@family.net", "hi", "2026-07-11 07:10:00", "personal known"),
        ],
        GMAIL_EMAIL: [
            ("known@promo.com", "note", "2026-07-11 07:12:00", "personal known 2"),
        ],
    }


class TestCond5GracefulDegradation(unittest.TestCase):
    def setUp(self):
        os.environ["APPLE_MAIL_READ_ALLOWED_ACCOUNTS"] = (
            "ara-data.com,aradata.onmicrosoft.com,gmail.com,me.com,icloud.com"
        )
        os.environ["APPLE_MAIL_READ_PERSONAL_DOMAINS"] = "gmail.com,me.com,icloud.com"
        # Mirror the DEPLOYED .mcp.json: env known-senders is EMPTY. The populated
        # FILE (below) is what actually governs production, and it wins over env.
        os.environ["APPLE_MAIL_READ_KNOWN_SENDERS"] = ""

        # Hermetic populated known-senders FILE of FAKE bare domains — models the
        # real 379-entry file WITHOUT reading a single real contact. Non-empty =>
        # the ships-dark skip does NOT fire => personal accounts ARE read (via the
        # IMAP transport fake).
        fd, self.senders_file = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("family.net,promo.com,acme.com,example.com")
        self._file_patch = mock.patch.object(config, "KNOWN_SENDERS_FILE", self.senders_file)
        self._file_patch.start()

        fd, self.log = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.remove(self.log)
        # Redirect the last-scan marker to a temp dir (never write the real dir).
        # The path is NON-overridable via env, so patch the module default; the
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
        for p in (self.senders_file, self.log, self.status):
            if os.path.exists(p):
                os.remove(p)
        if os.path.isdir(self.status_dir):
            os.rmdir(self.status_dir)

    def _run(self, driver=None, imap=None):
        driver = driver or FakeReadMailDriver(_world())
        imap = imap or FakePersonalImapDriver(_imap_world())
        return (
            read_apple_mail(SINCE, driver=driver, log_path=self.log, imap_driver=imap),
            driver,
            imap,
        )

    # --- v0.4 routing: ARA -> AppleScript transport, personal -> IMAP transport ---
    def test_transport_routing(self):
        res, driver, imap = self._run()
        # ARA accounts went through the AppleScript driver...
        self.assertEqual(set(driver.read_calls), {ARA_BIZ, ARA_M365})
        # ...and the personal accounts through the IMAP driver (by email).
        self.assertEqual(set(imap.read_calls), {ICLOUD_EMAIL, GMAIL_EMAIL})
        # All four accounts delivered.
        self.assertEqual(
            {m["account"] for m in res["messages"]},
            {ARA_BIZ, ARA_M365, PERSONAL_ICLOUD, PERSONAL_GMAIL},
        )
        self.assertEqual(res["status"], "ok")
        # R14: the connection audit event carries via + outcome, no content.
        conns = [e for e in _read_log(self.log) if e["event"] == "read_imap_connection"]
        self.assertEqual(len(conns), 2)
        self.assertTrue(all(e["outcome"] == "ok" and e["via"] == "imap" for e in conns))

    # --- deployed config: personal IMAP timeout degrades, never kills the scan ----
    def test_personal_imap_timeout_degrades_not_dies(self):
        # Prove the DEPLOYED mechanism: FILE source wins over the empty env var.
        senders, source = config.read_known_senders_with_source()
        self.assertEqual(source, "file", "file source must govern (deployed reality)")
        self.assertGreaterEqual(len(senders), 1)

        res, driver, imap = self._run(
            imap=FakePersonalImapDriver(_imap_world(), fail={ICLOUD_EMAIL: "timeout"})
        )
        self.assertIn(ICLOUD_EMAIL, imap.read_calls)  # transport was attempted
        # DEGRADED, not dead and NOT a silent success.
        self.assertEqual(res["status"], "partial")
        failed = {f["account"]: f for f in res["accounts_failed"]}
        self.assertIn(PERSONAL_ICLOUD, failed)
        self.assertEqual(failed[PERSONAL_ICLOUD]["kind"], "timeout")
        # Everything else STILL returned end-to-end.
        self.assertEqual(
            {m["account"] for m in res["messages"]},
            {ARA_BIZ, ARA_M365, PERSONAL_GMAIL},
        )
        events = [e["event"] for e in _read_log(self.log)]
        self.assertIn("read_account_degraded", events)

        # C1a WRITER: marker carries the partial + the account — no content (C1).
        with open(self.status, encoding="utf-8") as fh:
            marker = json.load(fh)
        self.assertEqual(marker["status"], "partial")
        self.assertIn(PERSONAL_ICLOUD, [f["account"] for f in marker["accounts_failed"]])
        raw_marker = json.dumps(marker)
        self.assertNotIn("known@family.net", raw_marker)
        self.assertNotIn("real ara body", raw_marker)

    # --- Ruling 2: credential_missing degrades VISIBLY (distinct from ships-dark) -
    def test_credential_missing_degrades_visibly(self):
        res, _, imap = self._run(
            imap=FakePersonalImapDriver(
                _imap_world(), fail={ICLOUD_EMAIL: "credential_missing"}
            )
        )
        self.assertEqual(res["status"], "partial")
        failed = {f["account"]: f for f in res["accounts_failed"]}
        self.assertEqual(failed[PERSONAL_ICLOUD]["kind"], "credential_missing")
        # The other personal account and both ARA accounts still delivered.
        self.assertEqual(
            {m["account"] for m in res["messages"]},
            {ARA_BIZ, ARA_M365, PERSONAL_GMAIL},
        )
        # R14: the failed connection is audit-logged with its outcome.
        conns = [e for e in _read_log(self.log) if e["event"] == "read_imap_connection"]
        self.assertIn("credential_missing", [e["outcome"] for e in conns])

    # --- Ruling 2: auth_failed and network degrade the same way -------------------
    def test_auth_and_network_failures_degrade(self):
        res, _, _ = self._run(
            imap=FakePersonalImapDriver(
                _imap_world(),
                fail={ICLOUD_EMAIL: "auth_failed", GMAIL_EMAIL: "network"},
            )
        )
        self.assertEqual(res["status"], "partial")
        kinds = {f["account"]: f["kind"] for f in res["accounts_failed"]}
        self.assertEqual(kinds[PERSONAL_ICLOUD], "auth_failed")
        self.assertEqual(kinds[PERSONAL_GMAIL], "network")
        self.assertEqual({m["account"] for m in res["messages"]}, {ARA_BIZ, ARA_M365})

    # --- ARA-business timeout ALSO degrades (max-availability, NOT hardfail) ------
    def test_ara_business_timeout_degrades_not_hardfail(self):
        res, _, _ = self._run(
            driver=FakeReadMailDriver(_world(), timeout_accounts={ARA_M365})
        )
        self.assertEqual(res["status"], "partial")
        failed = {f["account"]: f for f in res["accounts_failed"]}
        self.assertEqual(failed[ARA_M365]["kind"], "timeout")
        self.assertIn(ARA_BIZ, res["accounts_read"])

    # --- WS1: a PRE-TIMEOUT per-account STALL (rc!=0 / -1712) degrades -------------
    def test_per_account_stall_degrades(self):
        res, _, _ = self._run(
            driver=FakeReadMailDriver(_world(), error_accounts={ARA_M365})
        )
        self.assertEqual(res["status"], "partial")
        self.assertIn(ARA_M365, [f["account"] for f in res["accounts_failed"]])
        self.assertIn(ARA_BIZ, res["accounts_read"])
        degraded = [e for e in _read_log(self.log) if e["event"] == "read_account_degraded"]
        self.assertTrue(any(e.get("kind") == "stall" for e in degraded))

    # --- mixed transports: AppleScript stall + IMAP timeout both degrade ----------
    def test_mixed_transport_failures_both_degrade(self):
        res, _, _ = self._run(
            driver=FakeReadMailDriver(_world(), error_accounts={ARA_M365}),
            imap=FakePersonalImapDriver(_imap_world(), fail={ICLOUD_EMAIL: "timeout"}),
        )
        self.assertEqual(res["status"], "partial")
        failed = {f["account"] for f in res["accounts_failed"]}
        self.assertEqual(failed, {ARA_M365, PERSONAL_ICLOUD})
        # The survivors (one per transport) still return.
        self.assertEqual(
            {m["account"] for m in res["messages"]}, {ARA_BIZ, PERSONAL_GMAIL}
        )

    # --- wipeout floor: ALL accounts fail (across both transports) => RAISE -------
    def test_total_wipeout_raises(self):
        with self.assertRaises(ReadMailError) as ctx:
            self._run(
                driver=FakeReadMailDriver(
                    _world(), timeout_accounts={ARA_BIZ, ARA_M365}
                ),
                imap=FakePersonalImapDriver(
                    _imap_world(),
                    fail={ICLOUD_EMAIL: "timeout", GMAIL_EMAIL: "network"},
                ),
            )
        self.assertIn("no account returned", str(ctx.exception))

    # --- systemic: list_accounts failure still RAISES ------------------------------
    def test_systemic_list_accounts_failure_raises(self):
        with self.assertRaises(ReadMailError):
            self._run(driver=FakeReadMailDriver(_world(), list_accounts_error=True))

    # --- CAP (AppleScript/ARA path — R18 corollary: machinery KEPT) ----------------
    def test_ara_capped_flags_partial_not_silent(self):
        res, _, _ = self._run(
            driver=FakeReadMailDriver(_world(), saturated_accounts={ARA_BIZ})
        )
        self.assertEqual(res["status"], "partial", "capped scan must not look clean")
        self.assertIn(ARA_BIZ, [c["account"] for c in res["accounts_capped"]])
        # Capped != failed: the account WAS read and delivers what it read.
        self.assertIn(ARA_BIZ, res["accounts_read"])
        self.assertNotIn(ARA_BIZ, [f["account"] for f in res["accounts_failed"]])
        raw_log = json.dumps(_read_log(self.log))
        self.assertIn("read_account_capped", raw_log)

    # --- CAP (IMAP/personal path — R18 UID/byte bound rides the same machinery) ---
    def test_imap_capped_flags_partial_not_silent(self):
        res, _, _ = self._run(
            imap=FakePersonalImapDriver(
                _imap_world(), capped_accounts={ICLOUD_EMAIL}
            )
        )
        self.assertEqual(res["status"], "partial")
        self.assertIn(PERSONAL_ICLOUD, [c["account"] for c in res["accounts_capped"]])
        self.assertIn(PERSONAL_ICLOUD, res["accounts_read"])  # read, not failed
        # Its known-sender mail was still delivered.
        self.assertIn("known@family.net", {m["sender"] for m in res["messages"]})
        # C1: log carries counts, never message content.
        raw_log = json.dumps(_read_log(self.log))
        self.assertIn("read_account_capped", raw_log)
        self.assertNotIn("personal known", raw_log)

    # --- completeness: a known sender buried under newsletter noise is delivered --
    def test_buried_known_sender_is_delivered(self):
        imap_world = {
            ICLOUD_EMAIL: [
                ("news@newsletter.io", "Deal", "2026-07-11 07:20:00", "promo one"),
                ("noreply@receipts.com", "Receipt", "2026-07-11 07:19:00", "a receipt"),
                ("alerts@bank.example", "Alert", "2026-07-11 07:18:00", "an alert"),
                # the real one, buried beneath the noise:
                ("known@family.net", "hi there", "2026-07-11 07:10:00", "the real message"),
            ],
            GMAIL_EMAIL: [],
        }
        res, _, imap = self._run(imap=FakePersonalImapDriver(imap_world))
        senders = {m["sender"] for m in res["messages"]}
        self.assertIn("known@family.net", senders)          # buried known sender delivered
        self.assertNotIn("news@newsletter.io", senders)     # newsletter noise dropped
        self.assertNotIn("noreply@receipts.com", senders)
        # R17: the transport-level predicate saw the noise senders (and rejected
        # them BEFORE any body would be fetched by the real driver).
        self.assertIn("news@newsletter.io", imap.keep_calls)

    # --- C-WS2: personal accounts use the SAME cutoff as business (no widening) ---
    def test_personal_accounts_use_same_cutoff_as_business(self):
        _, driver, imap = self._run()
        for c in driver.read_cutoffs + imap.read_cutoffs:
            self.assertEqual(c, SINCE)
        self.assertEqual(len(imap.read_cutoffs), 2)  # both personal accounts

    # --- N-B: the marker path is NON-overridable (writer/reader cannot diverge) --
    def test_scan_status_path_not_env_overridable(self):
        env_dir = tempfile.mkdtemp()
        env_marker = os.path.join(env_dir, config.SCAN_STATUS_BASENAME)  # valid name
        os.environ["APPLE_MAIL_READ_SCAN_STATUS"] = env_marker
        try:
            self.assertEqual(config.read_scan_status_path(), self.status)
            self._run(
                imap=FakePersonalImapDriver(_imap_world(), fail={ICLOUD_EMAIL: "timeout"})
            )
            self.assertTrue(os.path.exists(self.status), "marker written to fixed path")
            self.assertFalse(os.path.exists(env_marker), "env path must NOT be written")
        finally:
            os.environ.pop("APPLE_MAIL_READ_SCAN_STATUS", None)
            if os.path.exists(env_marker):
                os.remove(env_marker)
            os.rmdir(env_dir)

    # --- N-C: clobber guard — a non-marker basename is NEVER written -------------
    def test_write_scan_status_refuses_non_marker_basename(self):
        bad = os.path.join(self.status_dir, "known-senders.txt")
        _write_scan_status("partial", [{"account": "X", "domain": "x"}], [], SINCE, bad)
        self.assertFalse(os.path.exists(bad),
                         "clobber guard must refuse a non-marker basename")
        good = os.path.join(self.status_dir, config.SCAN_STATUS_BASENAME)
        _write_scan_status("partial", [{"account": "X", "domain": "x"}], [], SINCE, good)
        self.assertTrue(os.path.exists(good))


if __name__ == "__main__":
    unittest.main(verbosity=2)
