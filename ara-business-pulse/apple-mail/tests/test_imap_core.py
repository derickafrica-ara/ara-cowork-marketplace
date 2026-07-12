"""imap_core driver-level tests (hermetic — NEVER touches network, imaplib
sockets, or the real Keychain; `security` is stubbed to return a SENTINEL).

Build-gate coverage map (Floyd v0.4 spec):
  R1/R7  hardcoded hosts + Keychain services; security argv shape (absolute path,
         list argv, no shell, bounded timeout).
  R9     secret hygiene: the SENTINEL password appears in NO artifact — run-log,
         marker, results, or exception text (auth-failure message is FIXED).
  R11-13 verb allow-list via a recording fake connection: EXAMINE readonly=True,
         UID SEARCH/FETCH with BODY.PEEK only, LOGOUT in finally; no write verb.
  R15    SEARCH SINCE uses (cutoff date - 1 day), locale-independent format.
  R16    window filter uses INTERNALDATE, never the attacker-controlled Date:.
  R17    two-phase: bodies fetched ONLY for known-sender matches.
  R18    UID overflow -> newest N + capped=True.
  R19/21 socket timeout -> ImapTimeoutError; exactly ONE login attempt; logout
         always (even on failure).
  R24-27 per-message partial fetch bound; hostile fixtures (bad charset, RFC 2047
         display-name spoof, MIME part bomb, control chars) never crash.
"""

from __future__ import annotations

import json
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import imap_core  # noqa: E402
from imap_core import (  # noqa: E402
    ImapAuthError,
    ImapCredentialMissing,
    ImapTimeoutError,
    PersonalImapDriver,
    _rfc3501_since_date,
)

SENTINEL_PW = "SENTINEL-PW-a7f3e9"  # nosec — fake test credential
CUTOFF = "2026-07-11 06:00:00"
EMAIL = "derick@icloud.com"


def _hdr(from_, subject):
    return (f"From: {from_}\r\nSubject: {subject}\r\nDate: Sat, 11 Jul 2026 "
            "09:00:00 +0000\r\n\r\n").encode()


def _body(text, extra_headers=""):
    return (f"From: x\r\nContent-Type: text/plain; charset=utf-8\r\n{extra_headers}"
            f"\r\n{text}").encode()


def _internaldate(day=12):
    # Local-ish INTERNALDATE inside the window (cutoff is Jul 11 06:00).
    return f'INTERNALDATE "{day:02d}-Jul-2026 09:00:00 +0000"'


class FakeConn:
    """Recording imaplib-shaped connection: captures EVERY verb + args so tests
    can assert the emitted-verb set ⊆ the R11 allow-list."""

    def __init__(self, search_uids, phase1, bodies, login_fail=False,
                 fetch_timeout=False):
        self.calls: list[tuple] = []
        self._search_uids = search_uids      # bytes like b"1 2 3"
        self._phase1 = phase1                # list of imaplib-style fetch items
        self._bodies = bodies                # uid(str) -> raw rfc822 bytes
        self._login_fail = login_fail
        self._fetch_timeout = fetch_timeout
        self.logged_out = False
        self.login_attempts = 0
        self.last_login = None

    def login(self, user, password):
        self.calls.append(("LOGIN", user))
        self.login_attempts += 1
        self.last_login = (user, password)
        if self._login_fail:
            import imaplib
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] LOGIN failed")
        return "OK", [b"ok"]

    def select(self, mailbox, readonly=False):
        self.calls.append(("SELECT", mailbox, readonly))
        return "OK", [b"1"]

    def uid(self, command, *args):
        self.calls.append(("UID " + command.upper(),) + args)
        if command.upper() == "SEARCH":
            return "OK", [self._search_uids]
        if command.upper() == "FETCH":
            if self._fetch_timeout:
                raise socket.timeout("modeled fetch timeout")
            spec = args[-1]
            if "HEADER.FIELDS" in spec:      # phase 1
                return "OK", self._phase1
            uid = args[0]                     # phase 2 (single uid)
            raw = self._bodies.get(uid, b"")
            return "OK", [(f"1 (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw), b")"]
        raise AssertionError(f"unexpected UID command {command!r}")

    def logout(self):
        self.calls.append(("LOGOUT",))
        self.logged_out = True
        return "BYE", [b"bye"]


def _driver_with(conn):
    """PersonalImapDriver wired to the fake conn + SENTINEL keychain stub."""
    drv = PersonalImapDriver()
    patches = [
        mock.patch.object(drv, "_connect", return_value=conn),
        mock.patch.object(imap_core, "_keychain_password", return_value=SENTINEL_PW),
    ]
    return drv, patches


def _run_driver(conn, keep=lambda s: True):
    drv, patches = _driver_with(conn)
    for p in patches:
        p.start()
    try:
        return drv.read_personal(EMAIL, "icloud.com", CUTOFF, keep)
    finally:
        for p in patches:
            p.stop()


class TestKeychain(unittest.TestCase):
    # --- R7: argv shape — absolute path, list argv, shell=False, bounded timeout -
    def test_security_argv_shape(self):
        with mock.patch.object(imap_core.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=SENTINEL_PW + "\n")
            pw = imap_core._keychain_password("ara-business-pulse-imap-icloud", EMAIL)
        self.assertEqual(pw, SENTINEL_PW)
        args, kwargs = run.call_args
        self.assertEqual(
            args[0],
            ["/usr/bin/security", "find-generic-password",
             "-a", EMAIL, "-s", "ara-business-pulse-imap-icloud", "-w"],
        )
        self.assertFalse(kwargs.get("shell", False))
        self.assertLessEqual(kwargs["timeout"], 30)  # bounded (hung prompt degrades)

    def test_missing_item_raises_credential_missing(self):
        with mock.patch.object(imap_core.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=44, stdout="")
            with self.assertRaises(ImapCredentialMissing):
                imap_core._keychain_password("svc", EMAIL)

    def test_hung_prompt_degrades_not_hangs(self):
        with mock.patch.object(imap_core.subprocess, "run",
                               side_effect=imap_core.subprocess.TimeoutExpired("x", 10)):
            with self.assertRaises(ImapCredentialMissing):
                imap_core._keychain_password("svc", EMAIL)

    # --- R1/R7: endpoints + services are the hardcoded constants ----------------
    def test_hardcoded_endpoints_and_services(self):
        self.assertEqual(imap_core.IMAP_HOSTS["icloud.com"], ("imap.mail.me.com", 993))
        self.assertEqual(imap_core.IMAP_HOSTS["me.com"], ("imap.mail.me.com", 993))
        self.assertEqual(imap_core.IMAP_HOSTS["gmail.com"], ("imap.gmail.com", 993))
        self.assertEqual(imap_core.KEYCHAIN_SERVICES["icloud.com"],
                         "ara-business-pulse-imap-icloud")
        self.assertEqual(imap_core.KEYCHAIN_SERVICES["gmail.com"],
                         "ara-business-pulse-imap-gmail")


class TestReadOnlyAndVerbs(unittest.TestCase):
    def _happy_conn(self):
        phase1 = [
            (f"1 (UID 7 {_internaldate()} BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {{}}".encode(),
             _hdr("Mom <mom@family.net>", "hi")),
            b")",
        ]
        return FakeConn(b"7", phase1, {"7": _body("hello body")})

    # --- R11/R12/R13: verb allow-list, EXAMINE readonly, PEEK-only fetches -------
    def test_verb_allowlist_readonly_select_and_peek(self):
        conn = self._happy_conn()
        records, meta = _run_driver(conn)
        verbs = {c[0] for c in conn.calls}
        self.assertTrue(verbs <= {"LOGIN", "SELECT", "UID SEARCH", "UID FETCH", "LOGOUT"},
                        f"forbidden verb emitted: {verbs}")
        # R12 — read-only select.
        sel = next(c for c in conn.calls if c[0] == "SELECT")
        self.assertEqual(sel[1], "INBOX")
        self.assertTrue(sel[2], "EXAMINE (readonly=True) is mandatory")
        # R13 — every FETCH is a PEEK.
        fetch_specs = [c[-1] for c in conn.calls if c[0] == "UID FETCH"]
        self.assertTrue(all("BODY.PEEK[" in s for s in fetch_specs), fetch_specs)
        # R24 — phase-2 body fetch is partial-bounded.
        self.assertTrue(any(f"<0.{imap_core.IMAP_MAX_MESSAGE_BYTES}>" in s
                            for s in fetch_specs))
        # The record came through.
        self.assertEqual(len(records), 1)
        self.assertIn("mom@family.net", records[0][0])
        self.assertEqual(records[0][3], "hello body")

    # --- R21: logout ALWAYS (success and failure), exactly one login attempt -----
    def test_logout_in_finally_even_on_auth_failure(self):
        conn = FakeConn(b"", [], {}, login_fail=True)
        with self.assertRaises(ImapAuthError):
            _run_driver(conn)
        self.assertTrue(conn.logged_out, "LOGOUT must run in finally")
        self.assertEqual(conn.login_attempts, 1, "EXACTLY ONE login attempt (R21)")

    # --- R19: socket timeout mid-session degrades with timeout semantics ---------
    def test_fetch_timeout_maps_to_timeout_kind(self):
        conn = FakeConn(b"7", [], {}, fetch_timeout=True)
        with self.assertRaises(ImapTimeoutError):
            _run_driver(conn)
        self.assertTrue(conn.logged_out)


class TestQueryCorrectness(unittest.TestCase):
    # --- R15: day-granular SINCE over-fetches by one day, locale-independent -----
    def test_since_is_cutoff_minus_one_day(self):
        self.assertEqual(_rfc3501_since_date("2026-07-11 06:00:00"), "10-Jul-2026")
        self.assertEqual(_rfc3501_since_date("2026-01-01 00:00:00"), "31-Dec-2025")

    def test_search_uses_since_criteria(self):
        conn = FakeConn(b"", [], {})
        _run_driver(conn)
        search = next(c for c in conn.calls if c[0] == "UID SEARCH")
        self.assertIn("(SINCE 10-Jul-2026)", search[-1])

    # --- R16: INTERNALDATE governs the window; Date: header is ignored -----------
    def test_internaldate_filters_window_not_date_header(self):
        phase1 = [
            # OLD INTERNALDATE (before cutoff) but a crafted NEW Date: header ->
            # must be DROPPED (stale mail can't be smuggled in).
            (f'1 (UID 1 INTERNALDATE "01-Jan-2020 09:00:00 +0000" '
             f"BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {{}}".encode(),
             _hdr("a@x.com", "old-but-crafted-new-date")),
            # NEW INTERNALDATE but a crafted OLD Date: header -> must be KEPT.
            (f"1 (UID 2 {_internaldate()} BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {{}}".encode(),
             _hdr("b@y.com", "new-but-crafted-old-date")),
            b")",
        ]
        conn = FakeConn(b"1 2", phase1, {"2": _body("kept body")})
        records, meta = _run_driver(conn)
        subjects = [r[1] for r in records]
        self.assertEqual(subjects, ["new-but-crafted-old-date"])
        # Body was fetched ONLY for the in-window uid.
        body_fetches = [c for c in conn.calls
                        if c[0] == "UID FETCH" and "HEADER.FIELDS" not in c[-1]]
        self.assertEqual([c[1] for c in body_fetches], ["2"])

    # --- R17: unknown-sender bodies are NEVER downloaded --------------------------
    def test_two_phase_unknown_sender_body_never_fetched(self):
        phase1 = [
            (f"1 (UID 5 {_internaldate()} BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {{}}".encode(),
             _hdr("Known <known@family.net>", "keep me")),
            (f"1 (UID 6 {_internaldate()} BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {{}}".encode(),
             _hdr("News <news@newsletter.io>", "drop me")),
            b")",
        ]
        conn = FakeConn(b"5 6", phase1,
                        {"5": _body("known body"), "6": _body("newsletter body")})
        keep = lambda s: "known@family.net" in s
        records, _ = _run_driver(conn, keep=keep)
        self.assertEqual([r[1] for r in records], ["keep me"])
        body_fetches = [c for c in conn.calls
                        if c[0] == "UID FETCH" and "HEADER.FIELDS" not in c[-1]]
        self.assertEqual([c[1] for c in body_fetches], ["5"],
                         "unknown-sender body must never be downloaded (R17)")

    # --- R17 + hardening: RFC 2047 display-name spoof cannot fake a known sender --
    def test_rfc2047_display_name_spoof(self):
        # Display name decodes to text containing a known address; the REAL address
        # is the final <...> — the predicate sees the decoded header and the
        # existing discipline (last bracket pair) must reject the spoof.
        spoof = "=?utf-8?B?a25vd25AZmFtaWx5Lm5ldA==?= <evil@phish.com>"  # "known@family.net"
        phase1 = [
            (f"1 (UID 9 {_internaldate()} BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {{}}".encode(),
             _hdr(spoof, "spoofed")),
            b")",
        ]
        conn = FakeConn(b"9", phase1, {"9": _body("spoof body")})
        offered = []

        def keep(sender_text):
            offered.append(sender_text)
            # Reuse the REAL discipline: read_core._extract_sender_address takes
            # the LAST bracket pair -> evil@phish.com -> not known.
            from read_core import _extract_sender_address
            return _extract_sender_address(sender_text) == "known@family.net"

        records, _ = _run_driver(conn, keep=keep)
        self.assertEqual(records, [], "RFC 2047 spoof must not pass the predicate")
        self.assertTrue(offered and "evil@phish.com" in offered[0])

    # --- R18: UID overflow -> newest N + capped ----------------------------------
    def test_uid_overflow_processes_newest_and_flags_capped(self):
        many = list(range(1, imap_core.IMAP_MAX_UIDS_PER_ACCOUNT + 51))
        conn = FakeConn(" ".join(map(str, many)).encode(), [], {})
        records, meta = _run_driver(conn)
        self.assertTrue(meta["capped"])
        self.assertEqual(meta["total_uids"], len(many))
        self.assertEqual(meta["processed_uids"], imap_core.IMAP_MAX_UIDS_PER_ACCOUNT)
        # The phase-1 fetch asked for the NEWEST (highest) uids: it starts at 51
        # (uids 1..50 dropped) and ends at the newest.
        p1 = next(c for c in conn.calls if c[0] == "UID FETCH")
        self.assertTrue(p1[1].startswith("51,"), p1[1][:12])
        self.assertTrue(p1[1].endswith(str(many[-1])))


class TestParserHardening(unittest.TestCase):
    def _one_message_conn(self, body_bytes):
        phase1 = [
            (f"1 (UID 3 {_internaldate()} BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {{}}".encode(),
             _hdr("k@known.net", "subj")),
            b")",
        ]
        return FakeConn(b"3", phase1, {"3": body_bytes})

    # --- R25: malformed charset never crashes (errors='replace') -----------------
    def test_bad_charset_replaced_not_crash(self):
        bad = (b"From: k@known.net\r\nContent-Type: text/plain; charset=utf-8\r\n"
               b"\r\n\xff\xfe broken \xba\xad bytes")
        records, meta = _run_driver(self._one_message_conn(bad))
        self.assertEqual(len(records), 1)
        self.assertIn("broken", records[0][3])  # decoded with replacement, kept

    def test_unknown_charset_falls_back(self):
        weird = (b"From: k@known.net\r\nContent-Type: text/plain; charset=no-such-cs\r\n"
                 b"\r\nplain enough")
        records, _ = _run_driver(self._one_message_conn(weird))
        self.assertEqual(len(records), 1)
        self.assertIn("plain enough", records[0][3])

    # --- R26: MIME part bomb -> that message skipped, scan continues -------------
    def test_mime_part_bomb_skips_message(self):
        parts = "".join(
            f"--B\r\nContent-Type: text/plain\r\n\r\npart {i}\r\n"
            for i in range(imap_core.IMAP_MAX_MIME_PARTS + 10)
        )
        bomb = (b"From: k@known.net\r\n"
                b"Content-Type: multipart/mixed; boundary=B\r\n\r\n"
                + parts.encode() + b"--B--\r\n")
        records, meta = _run_driver(self._one_message_conn(bomb))
        self.assertEqual(records, [], "part bomb must be skipped, not parsed")
        self.assertEqual(meta["parse_skipped"], 1)

    # --- R26: attachments are never decoded; text/plain wins ---------------------
    def test_attachment_not_decoded_text_plain_extracted(self):
        m = (b"From: k@known.net\r\n"
             b"Content-Type: multipart/mixed; boundary=B\r\n\r\n"
             b"--B\r\nContent-Type: text/plain\r\n\r\nthe text part\r\n"
             b"--B\r\nContent-Type: application/octet-stream\r\n"
             b"Content-Transfer-Encoding: base64\r\n\r\nQkxPQg==\r\n"
             b"--B--\r\n")
        records, _ = _run_driver(self._one_message_conn(m))
        self.assertEqual(records[0][3].strip(), "the text part")
        self.assertNotIn("QkxPQg", records[0][3])

    # --- R27: control characters stripped from extracted fields ------------------
    def test_control_chars_stripped(self):
        m = (b"From: k@known.net\r\nContent-Type: text/plain\r\n"
             b"\r\nline\x1fone\x1dtwo\x00three")
        records, _ = _run_driver(self._one_message_conn(m))
        body = records[0][3]
        for ch in ("\x1f", "\x1d", "\x00"):
            self.assertNotIn(ch, body)
        self.assertIn("lineonetwothree", body.replace("\n", ""))


class TestSecretHygiene(unittest.TestCase):
    # --- R9: the SENTINEL never reaches any artifact ------------------------------
    def test_sentinel_never_in_results_logs_or_errors(self):
        # Success path: sentinel used for LOGIN (proving the plumbing) but absent
        # from records/meta.
        phase1 = [
            (f"1 (UID 7 {_internaldate()} BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {{}}".encode(),
             _hdr("k@known.net", "s")),
            b")",
        ]
        conn = FakeConn(b"7", phase1, {"7": _body("b")})
        records, meta = _run_driver(conn)
        self.assertEqual(conn.last_login, (EMAIL, SENTINEL_PW))  # plumbed to LOGIN
        blob = json.dumps({"records": records, "meta": meta})
        self.assertNotIn(SENTINEL_PW, blob)

        # Failure path: the auth error text is FIXED — no secret, no server echo.
        conn2 = FakeConn(b"", [], {}, login_fail=True)
        try:
            _run_driver(conn2)
            self.fail("expected ImapAuthError")
        except ImapAuthError as exc:
            self.assertNotIn(SENTINEL_PW, str(exc))
            self.assertNotIn("AUTHENTICATIONFAILED", str(exc))  # no server echo


if __name__ == "__main__":
    unittest.main(verbosity=2)
