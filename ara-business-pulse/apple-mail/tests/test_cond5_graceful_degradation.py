"""COND-5 max-availability: per-account TIMEOUT degrades; systemic/wipeout fails loud.

This is the remediation Floyd required after the ships-dark skip proved
insufficient for the DEPLOYED state. Deployed reality: the hardcoded local file
~/.ara-business-pulse/known-senders.txt exists with 379 entries, so
read_known_senders_with_source() resolves source='file' and the env var (`""`)
is never consulted — the ships-dark skip CANNOT fire and the personal iCloud
inbox is still enumerated. If that enumeration times out, the OLD code killed the
whole scan.

Floyd's threat-model ruling: graceful degradation is COMPATIBLE with COND-5 as
long as a partial scan is NEVER presented as a clean success. So:
  - per-account read TIMEOUT  -> skip that ONE account, mark status "partial",
    keep the accounts that returned (Derick's MAX-AVAILABILITY choice: applies to
    ARA business accounts too, NOT a hard-fail).
  - ZERO accounts succeed (total wipeout) -> RAISE (fail loud).
  - SYSTEMIC / non-timeout error (list_accounts fails, per-account non-timeout
    error) -> RAISE (fail loud).

Hermeticity (N1): these tests exercise the FILE SOURCE — the exact mechanism that
governs production — using a temp file of FAKE domains. They NEVER read Derick's
real 379-sender file (config.KNOWN_SENDERS_FILE is patched to the temp file).
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
                ("known@family.net", "hi", "2026-07-11 07:10:00", "personal known"),
            ],
        },
        PERSONAL_GMAIL: {
            "email": "derick@gmail.com",
            "messages": [
                ("known@promo.com", "note", "2026-07-11 07:12:00", "personal known 2"),
            ],
        },
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

        # Hermetic populated known-senders FILE of FAKE bare domains (N1) — models
        # the real 379-entry file WITHOUT reading a single real contact. Non-empty
        # => the ships-dark skip does NOT fire => personal accounts ARE enumerated
        # (so they can time out, exactly like the live defect).
        fd, self.senders_file = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("family.net,promo.com,acme.com,example.com")
        self._file_patch = mock.patch.object(config, "KNOWN_SENDERS_FILE", self.senders_file)
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
        for p in (self.senders_file, self.log, self.status):
            if os.path.exists(p):
                os.remove(p)
        if os.path.isdir(self.status_dir):
            os.rmdir(self.status_dir)

    # --- R4-1 / N1 / N2: DEPLOYED file-source config + personal timeout ---------
    def test_file_source_populated_personal_timeout_degrades_not_dies(self):
        # Prove the DEPLOYED mechanism: FILE source wins over the empty env var.
        senders, source = config.read_known_senders_with_source()
        self.assertEqual(source, "file", "file source must govern (deployed reality)")
        self.assertGreaterEqual(len(senders), 1)

        # Personal iCloud times out (the live 90s-timeout defect), under a populated
        # known-senders file so the account is enumerated (not ships-dark).
        driver = FakeReadMailDriver(_world(), timeout_accounts={PERSONAL_ICLOUD})
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log)

        # The personal iCloud inbox WAS enumerated (proves this is the deployed,
        # non-dark path — the case the ships-dark skip alone did NOT cover).
        self.assertIn(PERSONAL_ICLOUD, driver.read_calls)

        # DEGRADED, not dead and NOT a silent success.
        self.assertEqual(res["status"], "partial")
        self.assertIn(PERSONAL_ICLOUD, [f["account"] for f in res["accounts_failed"]])

        # ARA business accounts STILL returned end-to-end.
        self.assertIn(ARA_BIZ, res["accounts_read"])
        self.assertIn(ARA_M365, res["accounts_read"])
        self.assertEqual(
            {m["account"] for m in res["messages"]}, {ARA_BIZ, ARA_M365, PERSONAL_GMAIL}
        )

        # The timeout is loudly logged (COND-5 audit; not swallowed).
        events = [e["event"] for e in _read_log(self.log)]
        self.assertIn("read_account_degraded", events)

        # C1a WRITER: the read core wrote the integrity marker (the structural
        # backstop's source of truth pulse-server reads) with the partial status +
        # the skipped account — and NO message content or sender address (C1).
        with open(self.status, encoding="utf-8") as fh:
            marker = json.load(fh)
        self.assertEqual(marker["status"], "partial")
        self.assertIn(PERSONAL_ICLOUD, [f["account"] for f in marker["accounts_failed"]])
        raw_marker = json.dumps(marker)
        self.assertNotIn("known@family.net", raw_marker)  # no sender address
        self.assertNotIn("known@promo.com", raw_marker)
        self.assertNotIn("real ara body", raw_marker)     # no message body

    # --- R4-2: ARA-business timeout ALSO degrades (max-availability, NOT hardfail) --
    def test_ara_business_timeout_degrades_not_hardfail(self):
        driver = FakeReadMailDriver(_world(), timeout_accounts={ARA_M365})
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log)

        # Per Derick's choice: an ARA-business timeout degrades, it does NOT raise.
        self.assertEqual(res["status"], "partial")
        self.assertIn(ARA_M365, [f["account"] for f in res["accounts_failed"]])
        # The other ARA account still returns.
        self.assertIn(ARA_BIZ, res["accounts_read"])

    # --- R4-3: total wipeout (zero succeed) still RAISES (fail-loud floor) -------
    def test_total_wipeout_raises(self):
        driver = FakeReadMailDriver(_world(), timeout_accounts=set(_world().keys()))
        with self.assertRaises(ReadMailError) as ctx:
            read_apple_mail(SINCE, driver=driver, log_path=self.log)
        self.assertIn("no account returned", str(ctx.exception))

    # --- R4-4a: systemic list_accounts failure still RAISES ----------------------
    def test_systemic_list_accounts_failure_raises(self):
        driver = FakeReadMailDriver(_world(), list_accounts_error=True)
        with self.assertRaises(ReadMailError):
            read_apple_mail(SINCE, driver=driver, log_path=self.log)

    # --- WS1: a PRE-TIMEOUT per-account STALL (rc!=0 / -1712) now DEGRADES --------
    def test_per_account_stall_degrades(self):
        # An account whose read_inbox errors before the 90s timeout (AppleEvent
        # -1712 / rc!=0) is per-account: degrade it (skip + partial), others return.
        driver = FakeReadMailDriver(_world(), error_accounts={ARA_M365})
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log)
        self.assertEqual(res["status"], "partial")
        self.assertIn(ARA_M365, [f["account"] for f in res["accounts_failed"]])
        self.assertIn(ARA_BIZ, res["accounts_read"])  # other accounts still return
        # Logged as a per-account degrade with kind="stall" (not fail-loud).
        degraded = [e for e in _read_log(self.log) if e["event"] == "read_account_degraded"]
        self.assertTrue(any(e.get("kind") == "stall" for e in degraded))

    # --- WS1: a TIMEOUT and a STALL both degrade per-account (mixed) --------------
    def test_timeout_and_stall_both_degrade(self):
        driver = FakeReadMailDriver(
            _world(), timeout_accounts={PERSONAL_ICLOUD}, error_accounts={ARA_M365}
        )
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log)
        self.assertEqual(res["status"], "partial")
        failed = {f["account"] for f in res["accounts_failed"]}
        self.assertEqual(failed, {PERSONAL_ICLOUD, ARA_M365})
        self.assertIn(ARA_BIZ, res["accounts_read"])  # the survivor still returns

    # --- WS1: ALL accounts stall (zero succeed) => still WIPEOUT => RAISE ---------
    def test_all_accounts_stall_wipeout_raises(self):
        driver = FakeReadMailDriver(_world(), error_accounts=set(_world().keys()))
        with self.assertRaises(ReadMailError) as ctx:
            read_apple_mail(SINCE, driver=driver, log_path=self.log)
        self.assertIn("no account returned", str(ctx.exception))

    # --- CAP: saturation is FLAGGED (partial + capped), never silently truncated --
    def test_capped_account_flags_partial_not_silent(self):
        # The read hit the per-account ceiling => older in-window mail may be unread.
        # It must be surfaced (status partial + accounts_capped), NOT reported clean.
        driver = FakeReadMailDriver(_world(), saturated_accounts={PERSONAL_ICLOUD})
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log)

        self.assertEqual(res["status"], "partial", "capped scan must not look clean")
        self.assertIn(PERSONAL_ICLOUD, [c["account"] for c in res["accounts_capped"]])
        # Capped != failed: the account WAS read and delivers what it read.
        self.assertIn(PERSONAL_ICLOUD, res["accounts_read"])
        self.assertNotIn(PERSONAL_ICLOUD, [f["account"] for f in res["accounts_failed"]])
        self.assertIn("known@family.net", {m["sender"] for m in res["messages"]})
        # Loudly logged; C1: no message content leaks into the log.
        raw_log = json.dumps(_read_log(self.log))
        self.assertIn("read_account_capped", raw_log)
        self.assertNotIn("personal known", raw_log)  # message body must not leak

    # --- CAP: a capped account alongside clean ones => partial, others intact ------
    def test_capped_and_clean_accounts_mix(self):
        driver = FakeReadMailDriver(_world(), saturated_accounts={PERSONAL_ICLOUD})
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log)
        self.assertEqual(res["status"], "partial")
        self.assertEqual([c["account"] for c in res["accounts_capped"]], [PERSONAL_ICLOUD])
        # The clean accounts still deliver their mail end-to-end.
        accts = {m["account"] for m in res["messages"]}
        self.assertIn(ARA_BIZ, accts)
        self.assertIn(ARA_M365, accts)
        self.assertIn(PERSONAL_GMAIL, accts)  # clean personal account unaffected

    # --- CAP/completeness: a known sender BURIED under newsletter noise is delivered
    def test_buried_known_sender_is_delivered(self):
        # read_core must NOT itself truncate to "N most recent": given a driver that
        # returns all in-window messages (newsletters + a buried known sender), the
        # known-sender message is delivered and the newsletters (unknown personal
        # senders) are dropped. (The AppleScript's newest-first completeness that
        # produces this list is live-only; this pins the read_core half.)
        world = {
            ARA_BIZ: {"email": "derick@ara-data.com", "messages": [
                ("client@acme.com", "Q3", "2026-07-11 07:00:00", "real ara body")]},
            PERSONAL_ICLOUD: {"email": "derick@icloud.com", "messages": [
                ("news@newsletter.io", "Deal", "2026-07-11 07:20:00", "promo one"),
                ("noreply@receipts.com", "Receipt", "2026-07-11 07:19:00", "a receipt"),
                ("alerts@bank.example", "Alert", "2026-07-11 07:18:00", "an alert"),
                # the real one, buried beneath the noise:
                ("known@family.net", "hi there", "2026-07-11 07:10:00", "the real message"),
            ]},
        }
        driver = FakeReadMailDriver(world)
        res = read_apple_mail(SINCE, driver=driver, log_path=self.log)
        senders = {m["sender"] for m in res["messages"]}
        self.assertIn("known@family.net", senders)          # buried known sender delivered
        self.assertNotIn("news@newsletter.io", senders)     # newsletter noise dropped
        self.assertNotIn("noreply@receipts.com", senders)

    # --- C-WS2: personal accounts use the SAME cutoff as business (no widening) ---
    def test_personal_accounts_use_same_cutoff_as_business(self):
        # The first-run 3-day personal window was dropped: ALL accounts — personal
        # and business — always read from the SAME passed cutoff (24h default on the
        # first run). No special-casing, no widening.
        driver = FakeReadMailDriver(_world())
        read_apple_mail(SINCE, driver=driver, log_path=self.log)
        cut = dict(zip(driver.read_calls, driver.read_cutoffs))
        for acct in (ARA_BIZ, ARA_M365, PERSONAL_ICLOUD, PERSONAL_GMAIL):
            self.assertEqual(cut[acct], SINCE)

    # --- N-B: the marker path is NON-overridable (writer/reader cannot diverge) --
    def test_scan_status_path_not_env_overridable(self):
        env_dir = tempfile.mkdtemp()
        env_marker = os.path.join(env_dir, config.SCAN_STATUS_BASENAME)  # valid name
        os.environ["APPLE_MAIL_READ_SCAN_STATUS"] = env_marker
        try:
            # The resolver ignores the env entirely (returns the fixed default,
            # here the patched temp marker) — so it can never diverge from the
            # reader, which also hard-codes the path.
            self.assertEqual(config.read_scan_status_path(), self.status)
            driver = FakeReadMailDriver(_world(), timeout_accounts={PERSONAL_ICLOUD})
            read_apple_mail(SINCE, driver=driver, log_path=self.log)
            self.assertTrue(os.path.exists(self.status), "marker written to fixed path")
            self.assertFalse(os.path.exists(env_marker), "env path must NOT be written")
        finally:
            os.environ.pop("APPLE_MAIL_READ_SCAN_STATUS", None)
            if os.path.exists(env_marker):
                os.remove(env_marker)
            os.rmdir(env_dir)

    # --- N-C: clobber guard — a non-marker basename is NEVER written -------------
    def test_write_scan_status_refuses_non_marker_basename(self):
        # A path that is NOT the dedicated marker (e.g. the known-senders file) must
        # never be written — the guard makes clobbering another file impossible.
        bad = os.path.join(self.status_dir, "known-senders.txt")
        _write_scan_status("partial", [{"account": "X", "domain": "x"}], [], SINCE, bad)
        self.assertFalse(os.path.exists(bad),
                         "clobber guard must refuse a non-marker basename")
        # ...while the real marker basename DOES get written.
        good = os.path.join(self.status_dir, config.SCAN_STATUS_BASENAME)
        _write_scan_status("partial", [{"account": "X", "domain": "x"}], [], SINCE, good)
        self.assertTrue(os.path.exists(good))


if __name__ == "__main__":
    unittest.main(verbosity=2)
