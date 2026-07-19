# Changelog — ara-business-pulse

## 0.4.3

Config + docs only — recipient-domain allow-list widened to named client domains
(Derick's decision, 2026-07-18). No validation-logic change.

- **What.** `APPLE_MAIL_DRAFT_ALLOWED_DOMAINS` (`.mcp.json` env) widened from
  `ara-data.com` to `ara-data.com,falkecorp.com,falkehoa.com` — the two Falke
  client domains, as an explicit NAMED-domain list (no wildcard, no "allow all").
  Contract text updated to match (tool docstring, SKILL.md, README,
  reference/config.md). The **from-account (sender) allow-list is UNCHANGED** —
  drafts still compose only from the ARA business accounts. The **code
  fail-closed default is UNCHANGED** (`ara-data.com` only): a deployment that
  loses or empties its env narrows back to ARA-only, never widens.
- **Why.** Client-bound drafts (e.g. to mfalke@falkecorp.com) were correctly
  refused by the ARA-only list; Derick wants client-bound drafts stageable in
  his Mail. Verified live 2026-07-18: the refusal fired fail-closed as designed
  before this change.
- **Threat considerations.** Widening recipients raises the value of a prompt
  injection that composes a convincing client-bound draft (tool inputs may
  originate from injection-capable scanned content). Accepted because the
  structural control holds: the tool can ONLY `save` a draft — it cannot send;
  a human must open Mail and click Send on exactly the body that was staged
  (BODY-CLEAN — no marker/banner is possible in the draft body by design, so
  human review of the draft itself IS the control). Defense in depth around it:
  named-domain list only (lookalike/subdomain/suffix domains refused — exact
  match), fail-closed code default preserved, from-account list untouched,
  every attempt (created or rejected) audit-logged with full recipients in the
  run-log, and the skill's COND-1 rule still forbids content-directed drafting.
  Per Floyd's gate condition C-1, the skill REQUIRES the digest to name
  client-bound drafts explicitly, per domain ("2 drafts staged to falkecorp.com
  — review before sending") — the extra-care review surface BODY-CLEAN forbids
  inside the draft itself.
- **Go-live / restart (read this or the widen appears broken).** The env is
  fixed at MCP-server spawn from the INSTALLED plugin's `.mcp.json` — a running
  server keeps the old ARA-only list until it respawns. The change takes effect
  only after the full chain: commit → push to the marketplace remote → update
  the installed plugin to 0.4.3 → **restart the session / reload plugins** so
  the apple-mail server respawns with the new env. Until then, client-bound
  drafts are still (correctly) refused.

## 0.4.2

Fix — comment-close leak in the digest template: nested `-->` inside doc
comments terminated the enclosing HTML comment early, leaking template
commentary into rendered output. Docs/template only; no tool or
validation-logic change. (Commit `4c1b8da`; entry backfilled at 0.4.3.)

## 0.4.1

P1 fix — `parseISO` month-rollover bug (Floyd gate delta 5): date arithmetic
around month boundaries could produce a wrong cutoff. No security-contract
change. (Commit `ef56c51`; entry backfilled at 0.4.3.)

## 0.4.0

Personal mail moves to direct provider IMAP (COND-8 v0.4) — the real fix for the
personal-inbox timeouts. Live diagnosis on the 88k-message iCloud inbox showed
Apple Mail's AppleScript bridge costs ~1.8s per message touch (count/endpoints are
cheap; any index/range access is not), so a daily ~60-message window needs ~108s —
over budget regardless of the 0.3.3 cap. AppleScript is the wrong tool for large
mailboxes; IMAP `SEARCH SINCE` is server-side date-indexed and returns the complete
window in under a second. Floyd threat-review ratified (Rulings 1–2, R1–R29).

- **Personal accounts (gmail.com / me.com / icloud.com) now read DIRECTLY from the
  provider over TLS-validated IMAP** (hardcoded `imap.mail.me.com` /
  `imap.gmail.com`, port 993, TLS ≥ 1.2, system trust store). Read-only by
  construction: EXAMINE (read-only select) + UID SEARCH + UID FETCH(BODY.PEEK) —
  the client cannot write, move, delete, flag, or mark-as-read, and never sets
  \\Seen on Derick's real mail. ARA business accounts stay on the fast AppleScript
  path (unchanged, R-SAFE cap retained).
- **Auth: app-specific passwords Derick generates and stores himself in the macOS
  Keychain** (`ara-business-pulse-imap-icloud` / `-gmail`). The raw secret never
  appears in files, env vars, tool results, logs, or exception text; it is read at
  runtime via `/usr/bin/security` (list argv, bounded timeout) and used only inside
  the TLS session. One-time setup + revocation documented in the README.
- **Two-phase privacy fetch:** phase 1 fetches INTERNALDATE + headers only; the
  known-senders filter runs BEFORE any body fetch — bodies of unknown-sender
  personal mail are never even downloaded. Window filtering uses the
  server-assigned INTERNALDATE (never the attacker-controlled Date: header), with
  a one-day SEARCH over-fetch so the day-granular SINCE can never under-fetch.
- **Ships-dark = zero network:** an empty known-senders list means the personal
  account is skipped at the account boundary — no Keychain read, no DNS, no
  connection.
- **Failure modes surface, never crash:** a missing Keychain item, auth rejection,
  network/TLS failure, or timeout degrades THAT account
  (`accounts_failed.kind`: credential_missing / auth_failed / network / timeout,
  `status:"partial"`, named on the pulse banner). Exactly one login attempt per
  scan (no lockout risk); zero accounts succeeding still fails loud.
- **Parser hardening:** per-message (1 MB partial fetch) and per-account (25 MB)
  byte bounds, stdlib email parsing with replace-on-bad-charset, text parts only
  (attachments never decoded), MIME part-walk cap, control chars stripped; UID
  result-set bound rides the existing `accounts_capped` machinery.
- **Audit:** every IMAP connection is logged (account, host, outcome, duration,
  counts — never content); read events now carry `via: "imap" | "applescript"`.

## 0.3.3

Feature release — the message-count cap (ADR docs/adr/0001), fixing the personal-
inbox 90s timeouts that 0.3.2 made survivable but did not eliminate.

- **Fix — personal inboxes no longer time out at 90s, and personal known-sender
  mail is delivered.** The read stopped using `whose date received > cutoff`, which
  walked the ENTIRE (years-large) inbox. It now examines the NEWEST
  `min(total, READ_MAX_MESSAGES_PER_ACCOUNT)` (500) messages by index (dates
  bulk-fetched in one round-trip) — bounded to O(ceiling), not O(inbox). In 0.3.2
  both personal accounts timed out and delivered zero mail; 0.3.3 delivers their
  known-sender mail.
- **Ordering-independent completeness (not "N most recent", and no early-stop).**
  The read examines ALL of the newest-up-to-ceiling messages and keeps EVERY
  in-window one, regardless of order — so a known sender buried under newsletter
  noise, OR a message delivered/moved out of order, is still captured. It does not
  stop at the first out-of-window message (which could otherwise silently drop
  in-window mail behind it).
- **Cap saturation is surfaced, never silently truncated (COND-5).** The account is
  flagged CAPPED when there is unexamined mail (more messages than it examined) AND
  the OLDEST-by-index examined message is still in-window — i.e. the window extends
  past the examined range, so in-window mail may sit beyond it. This boundary rule
  (decision in unit-tested Python) is order-robust: a busy day with >500 in-window
  messages is flagged even if an out-of-order message is interleaved, and a small
  delta on a huge inbox is never falsely capped. A capped account is named in
  `accounts_capped`, `status: "partial"`, and on the 8788 viewer's INCOMPLETE-SCAN
  banner. A busy day never silently drops mail while looking clean.
- Preserved: COND-8 allow-list + fail-closed, the known-senders filter, the
  ships-dark boundary skip, per-account degrade (timeout/stall) + systemic/wipeout
  fail-loud, C1 log-privacy, the run-token/cutoff correlation, and the structural
  banner.

> The logic + COND-5 flagging are verified by the mocked suites; the actual speed
> win on the large personal inboxes is confirmed by a live run (mocks can't measure
> osascript timing).

## 0.3.2

Patch release fixing the mail-scan timeout regression introduced in 0.3.1 (the two
builds are otherwise indistinguishable by version, hence this bump).

- **Fix — a slow personal inbox no longer kills the whole scan.** In 0.3.1, a
  personal account (Gmail/iCloud) whose inbox read timed out or stalled raised and
  aborted the entire morning scan before it reached the ARA mailboxes. Reads are now
  bounded per account.
- **Graceful per-account degradation (max-availability).** Any single account whose
  read times out or stalls (incl. pre-90s AppleEvent `-1712`) is skipped and the scan
  is marked `status: "partial"`; the accounts that returned are still delivered.
  Systemic failures (Mail not running / auth / account-enumeration failure) and a
  total wipeout (zero accounts return) still fail loud — a partial scan is never
  presented as complete.
- **Injection-proof INCOMPLETE-SCAN banner on the 8788 viewer.** When a scan is
  partial, the local pulse viewer injects a structural warning banner into the served
  HTML by construction (from a Python-written scan-status marker, correlated to the
  pulse by run token). It cannot be suppressed by a prompt-injection in scanned mail,
  and shows a neutral "scan status unknown" caution when it cannot confirm the pulse
  matches the latest scan.
- **On-brand banner styling.** ARA-branded RED (incomplete) / AMBER (unknown) warning
  banner — flat field, datum spine, inline warning glyph, IBM Plex type. Copy
  pluralizes on the number of skipped accounts.
- **Ships-dark personal accounts** with an empty known-senders list are skipped at the
  account boundary (never enumerated).

## 0.3.1

Changed known-senders to load from a local file (reinstall-proof, git-free). Built on
0.3.0, which added personal mail (known-senders), iMessage (read-only), and the
ARA-branded local viewer — and introduced the slow-personal-inbox timeout regression
that could abort the whole scan (fixed in 0.3.2).
