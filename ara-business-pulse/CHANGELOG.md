# Changelog — ara-business-pulse

## 0.3.3

Feature release — the message-count cap (ADR docs/adr/0001), fixing the personal-
inbox 90s timeouts that 0.3.2 made survivable but did not eliminate.

- **Fix — personal inboxes no longer time out at 90s, and personal known-sender
  mail is delivered.** The read stopped using `whose date received > cutoff`, which
  walked the ENTIRE (years-large) inbox. It now reads the inbox NEWEST-FIRST by
  index and stops as soon as it passes the since-last-run cutoff or hits a per-
  account ceiling (`READ_MAX_MESSAGES_PER_ACCOUNT`, 500) — bounded to O(ceiling),
  not O(inbox). In 0.3.2 both personal accounts timed out and delivered zero mail;
  0.3.3 delivers their known-sender mail.
- **Completeness within the window (not "N most recent").** Because the read walks
  newest-first and keeps ALL in-window messages, a known sender buried under
  newsletter noise inside the window is still captured — the naive "read N newest,
  filter" trap is avoided.
- **Cap saturation is surfaced, never silently truncated (COND-5).** If the ceiling
  is reached before the cutoff — older in-window mail may be unread — the account is
  flagged CAPPED (`accounts_capped`, `status: "partial"`) and named on the 8788
  viewer's INCOMPLETE-SCAN banner. A busy day never silently drops mail while
  looking clean.
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
