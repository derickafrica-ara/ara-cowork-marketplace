"""imap_core — the PERSONAL-account IMAP transport (COND-8 v0.4).

TRANSPORT ONLY (Floyd R28): this module fetches in-window, known-sender message
bytes for ONE named personal account directly from the provider over validated
TLS. It re-implements NO COND-8 logic — the allow-list boundary, ships-dark skip,
known-senders enforcement, audit logging, and marker write all stay in
read_core.read_apple_mail (the orchestrator), which routes personal domains here
and ARA domains to the AppleScript ReadMailDriver. The known-senders list itself
never enters this module: the orchestrator injects a `keep_sender(header_text)`
predicate (built from its own _extract_sender_address + sender_is_known — the
already-hardened display-name-spoof discipline, per R17).

Security posture (Floyd's spec, R-numbers refer to the v0.4 build spec):
  R1  Hosts/ports are HARDCODED module constants — never env/config/.mcp.json/
      scanned-content configurable.
  R2/R3/R4  Implicit TLS only: imaplib.IMAP4_SSL on 993 with
      ssl.create_default_context() (system trust store, certificate + hostname
      validation) and minimum_version=TLSv1_2. Never plain IMAP4, never STARTTLS,
      never CERT_NONE. The credential is transmitted ONLY inside the established
      validated session; a connect/TLS failure raises BEFORE login.
  R5  No certificate pinning — considered decision: the system trust store +
      hostname validation is the control; pinning a public provider's rotating
      leaf/intermediate certs would break on normal rotation.
  R6  No untrusted string ever composes an IMAP command: the mailbox is the
      hardcoded "INBOX", SEARCH criteria are self-generated from the validated
      cutoff, FETCH item names are hardcoded, and UIDs come from the server's own
      SEARCH response (digits, revalidated here).
  R7  Credential read from macOS Keychain via
      /usr/bin/security find-generic-password (absolute path, list argv,
      shell=False, bounded timeout). Service names hardcoded.
  R9  The secret exists in memory only for login; the reference is dropped after
      auth; it is never logged, never written, never placed in an exception
      message, never returned.
  R10 Accepted residuals (documented): a same-user process can read the Keychain
      item after Derick's "Always Allow" grant; Python strings are not
      zeroizable. That attacker already owns the session.
  R11–R13  Read-only by construction: the ONLY IMAP verbs this module can emit
      are LOGIN, CAPABILITY/NOOP (implicit via imaplib), EXAMINE (select
      readonly=True), UID SEARCH, UID FETCH (always BODY.PEEK — never sets
      \\Seen), LOGOUT. No STORE/COPY/APPEND/EXPUNGE/CREATE/DELETE/RENAME/SETACL
      exists anywhere in this code path.
  R15/R16  SEARCH SINCE is DAY-granular → we over-fetch by one day
      (cutoff_date − 1) and window-filter PRECISELY in Python on INTERNALDATE
      (server-assigned; the attacker-controlled Date: header is never used for
      windowing).
  R17  Two-phase fetch: phase 1 = INTERNALDATE + header-fields only (no body);
      known-sender selection; phase 2 = BODY.PEEK[] ONLY for known-sender
      matches. Bodies of unknown-sender personal mail are NEVER downloaded.
  R18  UID sanity cap per account; overflow processes the newest N and reports
      capped=True (the orchestrator surfaces it via accounts_capped).
  R19/R21  Explicit socket timeout on connect + a per-account wall-clock budget;
      EXACTLY ONE login attempt per scan (no retry → no lockout); LOGOUT in a
      finally block.
  R24–R27  Parser hardening: per-message and per-account byte caps (partial
      BODY.PEEK[]<0.N> fetch), stdlib email parsing with policy=default,
      errors="replace" decoding, text/plain (fallback text/html) only,
      attachments never decoded, MIME part-walk cap, control chars stripped.
      Per-message anomalies skip+count that message; response-level garbage
      degrades the account. Never crashes the scan.
"""

from __future__ import annotations

import datetime as _dt
import email
import email.policy
import imaplib
import re
import socket
import ssl
import subprocess
import time

# --------------------------------------------------------------------------- #
# R1 — hardcoded endpoints. R7 — hardcoded Keychain service names.
# NOT configurable via env, config files, .mcp.json, or scanned content.
# --------------------------------------------------------------------------- #
IMAP_HOSTS: dict[str, tuple[str, int]] = {
    "me.com": ("imap.mail.me.com", 993),
    "icloud.com": ("imap.mail.me.com", 993),
    "gmail.com": ("imap.gmail.com", 993),
}
KEYCHAIN_SERVICES: dict[str, str] = {
    "me.com": "ara-business-pulse-imap-icloud",
    "icloud.com": "ara-business-pulse-imap-icloud",
    "gmail.com": "ara-business-pulse-imap-gmail",
}
SECURITY_BIN = "/usr/bin/security"          # absolute path (R7)
KEYCHAIN_TIMEOUT_SECONDS = 10.0             # hung Keychain prompt degrades (R7)

# R19 — budgets. Connect timeout applies to the socket (all ops inherit it);
# the account budget is a wall-clock guard checked between phases.
IMAP_CONNECT_TIMEOUT_SECONDS = 15.0
IMAP_ACCOUNT_BUDGET_SECONDS = 30.0

# R18 — result-set sanity bound (overflow -> newest N + capped).
IMAP_MAX_UIDS_PER_ACCOUNT = 1000

# R24 — byte caps: per-message partial fetch bound + per-account total.
IMAP_MAX_MESSAGE_BYTES = 1_000_000
IMAP_MAX_ACCOUNT_BYTES = 25_000_000

# R26 — MIME part-walk cap (nesting/part bombs -> skip that message).
IMAP_MAX_MIME_PARTS = 100

# Locale-independent RFC 3501 date (never %b — locale-dependent).
_RFC3501_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_UID_RE = re.compile(rb"UID (\d+)")


class PersonalImapError(RuntimeError):
    """Base per-account IMAP failure. `kind` feeds accounts_failed (Ruling 2).

    Messages are FIXED strings (plus host/duration metadata) — never interpolate
    server responses or secrets (R9)."""

    kind = "network"

    def __init__(self, message: str, host: str = "", duration: float = 0.0):
        super().__init__(message)
        self.host = host
        self.duration = duration


class ImapCredentialMissing(PersonalImapError):
    kind = "credential_missing"


class ImapAuthError(PersonalImapError):
    kind = "auth_failed"


class ImapNetworkError(PersonalImapError):
    kind = "network"


class ImapTimeoutError(PersonalImapError):
    kind = "timeout"


class _MimePartsExceeded(Exception):
    """Internal: message exceeded IMAP_MAX_MIME_PARTS (skip that message, R26)."""


def _keychain_password(service: str, account: str) -> str:
    """Read one app-specific password from the macOS Keychain (R7).

    Absolute binary path, list argv, shell=False, bounded timeout. Any failure —
    missing item, non-zero rc, empty output, or a HUNG Keychain prompt — raises
    ImapCredentialMissing (degrade, never hang or crash the scan). The value is
    returned to the caller for LOGIN only and never logged (R9).
    """
    try:
        proc = subprocess.run(
            [SECURITY_BIN, "find-generic-password", "-a", account, "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
            check=False,
            shell=False,  # explicit: never a shell string
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        raise ImapCredentialMissing(
            f"Keychain item unavailable for service {service!r} "
            "(prompt timed out or security tool unavailable)"
        ) from exc
    if proc.returncode != 0 or not proc.stdout.strip():
        # rc!=0 = item not found / access denied. NEVER include stderr (R9 —
        # keep any Keychain detail out of logs/exceptions).
        raise ImapCredentialMissing(
            f"Keychain item missing for service {service!r} "
            "(store it with: security add-generic-password — see README)"
        )
    return proc.stdout.strip()


def _rfc3501_since_date(cutoff: str) -> str:
    """R15: SEARCH SINCE is DAY-granular and TZ-fuzzy — over-fetch by ONE day
    (safe direction; the precise window filter happens on INTERNALDATE in
    _read_session). Input is the orchestrator's already-validated cutoff
    ("YYYY-MM-DD HH:MM:SS"); output is locale-independent DD-Mon-YYYY (R6: the
    criteria string is self-generated, no untrusted input)."""
    d = _dt.datetime.strptime(cutoff, "%Y-%m-%d %H:%M:%S").date() - _dt.timedelta(days=1)
    return f"{d.day:02d}-{_RFC3501_MONTHS[d.month - 1]}-{d.year}"


def _cutoff_epoch(cutoff: str) -> float:
    return _dt.datetime.strptime(cutoff, "%Y-%m-%d %H:%M:%S").timestamp()


def _internaldate_epoch(meta: bytes):
    """Server-assigned INTERNALDATE (R16) -> local epoch, or None if unparseable.
    Uses stdlib imaplib.Internaldate2tuple (returns a LOCAL struct_time)."""
    try:
        tt = imaplib.Internaldate2tuple(meta)
        return time.mktime(tt) if tt else None
    except Exception:
        return None


def _strip_ctrl(text: str, keep_newlines: bool = False) -> str:
    """R27: strip control characters (parity with the AppleScript stripCtrl —
    including the US/GS framing bytes) from extracted fields. Bodies keep
    \\t/\\n/\\r; single-line fields keep nothing below 0x20."""
    keep = "\t\n\r" if keep_newlines else ""
    return "".join(ch for ch in text if ch >= " " or ch in keep)


def _decode_header(msg, name: str) -> str:
    """Defensive RFC 2047 header decode (R25): policy=default auto-decodes;
    any malformed-header error yields '' rather than a crash."""
    try:
        return str(msg[name] or "")
    except Exception:
        return ""


def _extract_text(msg) -> str:
    """R26: extract text/plain (fallback: text/html passed through as text —
    DATA under COND-1, never rendered here). Attachments are never decoded and
    never written anywhere. Walk is capped (part bombs -> _MimePartsExceeded ->
    caller skips that message). R25: charset decode errors='replace'; unknown
    charsets fall back to utf-8; nothing here can crash the scan."""
    plain: str | None = None
    html_text: str | None = None
    walked = 0
    for part in msg.walk():
        walked += 1
        if walked > IMAP_MAX_MIME_PARTS:
            raise _MimePartsExceeded()
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue  # attachments/other parts: never decoded (R26)
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            payload = None
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except (LookupError, ValueError):
            text = payload.decode("utf-8", errors="replace")
        if ctype == "text/plain" and plain is None:
            plain = text
        elif ctype == "text/html" and html_text is None:
            html_text = text
    if plain is not None:
        return plain
    return html_text or ""


class PersonalImapDriver:
    """The ONE choke point for all IMAP interaction (R11) — mirrors the
    ReadMailDriver seam so tests inject a fake (FakePersonalImapDriver, R29).

    Verb allow-list this class may emit: LOGIN, EXAMINE (select readonly=True),
    UID SEARCH, UID FETCH (BODY.PEEK only), LOGOUT (+ imaplib's implicit
    CAPABILITY greeting). Nothing else exists in this code path (R11–R13).
    """

    def read_personal(
        self,
        account_email: str,
        domain: str,
        cutoff: str,
        keep_sender,
    ) -> tuple[list[tuple[str, str, str, str]], dict]:
        """Fetch in-window, known-sender messages for ONE personal account.

        Args:
            account_email: the account's address (from Mail's account list) —
                           the Keychain -a value and the IMAP LOGIN user.
            domain:        allow-listed personal domain (routes host + service).
            cutoff:        validated "YYYY-MM-DD HH:MM:SS" (orchestrator-supplied).
            keep_sender:   predicate(header_text) -> bool, injected by the
                           orchestrator (its _extract_sender_address +
                           sender_is_known — R17). This module never sees the
                           known-senders list itself (R28).

        Returns (records, meta): records are (sender, subject, date, body)
        tuples — the same shape as the AppleScript path, feeding the UNCHANGED
        downstream pipeline; date is the INTERNALDATE-derived local timestamp
        (R16), never the Date: header. meta = {host, duration, total_uids,
        processed_uids, bodies_fetched, parse_skipped, capped}.

        Raises PersonalImapError subclasses per Ruling 2 (credential_missing /
        auth_failed / network / timeout) — the orchestrator degrades the account.
        """
        host_port = IMAP_HOSTS.get(domain)
        service = KEYCHAIN_SERVICES.get(domain)
        if host_port is None or service is None:
            # Defensive: routing should never send an unmapped domain here.
            raise ImapNetworkError(f"no hardcoded IMAP endpoint for domain {domain!r}")
        host, port = host_port

        # R7 — credential AFTER the orchestrator's ships-dark boundary (a dark
        # account never reaches this call: zero network, zero Keychain — R22).
        password = _keychain_password(service, account_email)

        t0 = time.monotonic()

        def _elapsed() -> float:
            return time.monotonic() - t0

        def _check_budget() -> None:
            if _elapsed() > IMAP_ACCOUNT_BUDGET_SECONDS:
                raise ImapTimeoutError(
                    f"per-account IMAP budget ({IMAP_ACCOUNT_BUDGET_SECONDS:.0f}s) "
                    "exceeded",
                    host=host,
                    duration=_elapsed(),
                )

        # R2/R3 — implicit TLS with full validation; TLS >= 1.2.
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2

        conn = None
        try:
            try:
                conn = self._connect(host, port, ctx)
            except (socket.timeout, TimeoutError) as exc:
                raise ImapTimeoutError(
                    "IMAP connect timed out", host=host, duration=_elapsed()
                ) from exc
            except (ssl.SSLError, socket.gaierror, ConnectionError, OSError) as exc:
                # R4: TLS/connect failure => the credential was NEVER transmitted.
                raise ImapNetworkError(
                    f"IMAP connect/TLS failure: {exc.__class__.__name__}",
                    host=host,
                    duration=_elapsed(),
                ) from exc

            # R21 — EXACTLY ONE login attempt; no retry (lockout protection).
            try:
                conn.login(account_email, password)
            except (socket.timeout, TimeoutError) as exc:
                raise ImapTimeoutError(
                    "IMAP login timed out", host=host, duration=_elapsed()
                ) from exc
            except imaplib.IMAP4.error as exc:
                # R9: FIXED message — never interpolate the server response.
                raise ImapAuthError(
                    "IMAP LOGIN rejected by server (auth failed; check the "
                    "app-specific password in the Keychain)",
                    host=host,
                    duration=_elapsed(),
                ) from exc
            finally:
                password = None  # R9: drop the reference right after auth.

            try:
                records, meta = self._read_session(
                    conn, cutoff, keep_sender, _check_budget
                )
            except PersonalImapError as exc:
                exc.host = exc.host or host
                exc.duration = exc.duration or _elapsed()
                raise
            except (socket.timeout, TimeoutError) as exc:
                raise ImapTimeoutError(
                    "IMAP operation timed out", host=host, duration=_elapsed()
                ) from exc
            except imaplib.IMAP4.error as exc:
                raise ImapNetworkError(
                    f"IMAP protocol failure: {exc.__class__.__name__}",
                    host=host,
                    duration=_elapsed(),
                ) from exc

            meta.update({"host": host, "duration": round(_elapsed(), 3)})
            return records, meta
        finally:
            # R21 — session ALWAYS torn down.
            if conn is not None:
                try:
                    conn.logout()
                except Exception:
                    pass

    # -- seams (kept tiny so tests can stub the network without monkeypatching
    #    the module-level imaplib) ------------------------------------------- #
    def _connect(self, host: str, port: int, ctx: ssl.SSLContext):
        """R2: IMAP4_SSL only — implicit TLS on 993 with the validated context
        and an explicit socket timeout (R19). Never IMAP4/STARTTLS."""
        return imaplib.IMAP4_SSL(
            host, port, ssl_context=ctx, timeout=IMAP_CONNECT_TIMEOUT_SECONDS
        )

    # -- the read session (post-auth) ---------------------------------------- #
    def _read_session(
        self, conn, cutoff: str, keep_sender, check_budget
    ) -> tuple[list[tuple[str, str, str, str]], dict]:
        # R12 — EXAMINE (read-only select): FETCH can never set \Seen.
        status, _ = conn.select("INBOX", readonly=True)
        if status != "OK":
            raise ImapNetworkError("IMAP EXAMINE INBOX failed")

        # R15 — day-granular SINCE with a one-day defensive over-fetch (R6: the
        # criteria string is entirely self-generated).
        status, data = conn.uid("SEARCH", None, f"(SINCE {_rfc3501_since_date(cutoff)})")
        if status != "OK" or not data:
            raise ImapNetworkError("IMAP UID SEARCH failed")
        raw_uids = data[0].split() if data[0] else []
        # R6 — revalidate: UIDs must be pure digits (server-supplied, but bound
        # them anyway before they re-enter a command string).
        uids = [u.decode("ascii") for u in raw_uids if u.isdigit()]
        total_uids = len(uids)

        # R18 — sanity cap: process the NEWEST N (UIDs ascend with arrival).
        capped = False
        if total_uids > IMAP_MAX_UIDS_PER_ACCOUNT:
            uids = uids[-IMAP_MAX_UIDS_PER_ACCOUNT:]
            capped = True

        meta = {
            "total_uids": total_uids,
            "processed_uids": len(uids),
            "bodies_fetched": 0,
            "parse_skipped": 0,
            "capped": capped,
        }
        if not uids:
            return [], meta

        check_budget()

        # ---- Phase 1 (R17): INTERNALDATE + header fields ONLY — no bodies. ----
        # NOTE (flagged deviation from R17's letter, for Floyd): the spec names
        # ENVELOPE; this uses BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] —
        # still metadata-only (zero body bytes), still PEEK (no flags), but
        # parsed by the SAME hardened stdlib email parser as phase 2 instead of
        # a hand-rolled ENVELOPE s-expression parser (which would be NEW,
        # unreviewed parsing surface). Rationale in the hand-back; swap is
        # localized if Floyd prefers ENVELOPE.
        status, data = conn.uid(
            "FETCH",
            ",".join(uids),
            "(INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])",
        )
        if status != "OK":
            raise ImapNetworkError("IMAP phase-1 header FETCH failed")

        cutoff_epoch = _cutoff_epoch(cutoff)
        candidates: list[tuple[str, str, str, float]] = []  # (uid, sender, subject, epoch)
        for item in data or []:
            if not (isinstance(item, tuple) and len(item) >= 2):
                continue  # framing filler (b')') — not a message
            meta_bytes, header_bytes = item[0], item[1]
            try:
                m_uid = _UID_RE.search(meta_bytes)
                if not m_uid:
                    meta["parse_skipped"] += 1
                    continue
                uid = m_uid.group(1).decode("ascii")
                epoch = _internaldate_epoch(meta_bytes)
                if epoch is None:
                    # R16: no server date => cannot window-filter => skip+count
                    # (per-message anomaly, Ruling 2).
                    meta["parse_skipped"] += 1
                    continue
                if epoch <= cutoff_epoch:
                    continue  # outside the precise window (over-fetch trimmed)
                hdr = email.message_from_bytes(
                    bytes(header_bytes or b""), policy=email.policy.default
                )
                sender = _strip_ctrl(_decode_header(hdr, "From"))
                subject = _strip_ctrl(_decode_header(hdr, "Subject"))
            except Exception:
                meta["parse_skipped"] += 1
                continue
            # R17 — known-senders selection BEFORE any body fetch, via the
            # orchestrator-injected predicate (unknown bodies never downloaded).
            if not keep_sender(sender):
                continue
            candidates.append((uid, sender, subject, epoch))

        check_budget()

        # ---- Phase 2 (R17): bodies for KNOWN-SENDER matches only. -------------
        records: list[tuple[str, str, str, str]] = []
        fetched_bytes = 0
        for uid, sender, subject, epoch in candidates:
            check_budget()
            if fetched_bytes >= IMAP_MAX_ACCOUNT_BYTES:
                # R24 — per-account byte budget exhausted: surface as capped
                # (incomplete, never silent) and stop fetching.
                meta["capped"] = True
                break
            # R24 — per-message partial fetch bound; R13 — PEEK never sets flags.
            status, data = conn.uid(
                "FETCH", uid, f"(BODY.PEEK[]<0.{IMAP_MAX_MESSAGE_BYTES}>)"
            )
            if status != "OK":
                raise ImapNetworkError("IMAP phase-2 body FETCH failed")
            body_bytes = b""
            for item in data or []:
                if isinstance(item, tuple) and len(item) >= 2:
                    body_bytes = bytes(item[1] or b"")
                    break
            fetched_bytes += len(body_bytes)
            try:
                msg = email.message_from_bytes(body_bytes, policy=email.policy.default)
                body = _strip_ctrl(_extract_text(msg), keep_newlines=True)
            except _MimePartsExceeded:
                meta["parse_skipped"] += 1  # R26: part bomb -> skip that message
                continue
            except Exception:
                meta["parse_skipped"] += 1  # R25: malformed message -> skip
                continue
            date_str = _dt.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")
            records.append((sender, subject, date_str, body))
            meta["bodies_fetched"] += 1

        return records, meta
