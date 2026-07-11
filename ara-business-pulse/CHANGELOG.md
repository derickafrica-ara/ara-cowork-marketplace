# Changelog — ara-business-pulse

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
