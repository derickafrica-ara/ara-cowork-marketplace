# Per-person config the skill + MCP server read

Per-person config splits into **two groups by who collects it and when**:

**Group A — the three mail allow-lists: MCP server `env` defaults (set at
install).** They ship with safe ARA defaults in the plugin's `.mcp.json` and are
enforced **inside** the MCP server; you override only if a person differs. They are
**NOT** prompted by the skill and **NOT** secrets.

| What | Where it's read | Default / example | Notes |
|---|---|---|---|
| **Read account allow-list** | `APPLE_MAIL_READ_ALLOWED_ACCOUNTS` (MCP env) | `ara-data.com,ARAdata.onmicrosoft.com,gmail.com,me.com,icloud.com` | The fixed **four-account** COND-8 boundary: two ARA accounts + Gmail + iCloud (iCloud = `me.com`/`icloud.com`). Matched on email **domain**, not display name. Empty/garbage ⇒ read nothing (fail closed). An account not on this list is skipped automatically. |
| **Personal-scope domains (known-senders filter)** | `APPLE_MAIL_READ_PERSONAL_DOMAINS` (MCP env) | `gmail.com,me.com,icloud.com` | Accounts on these domains are read **only for known senders** (the reliable substitute for Apple Mail's non-scriptable "Primary" category). ARA domains are NOT here, so they read the **full** inbox. **Explicit-empty ⇒ no domain is personal-scope = read personal inboxes in FULL** (deliberate override only — an accidental empty over-reads). |
| **Known-sender allow-list (personal accounts)** | **File-first:** `~/.ara-business-pulse/known-senders.txt` (local file, **priority source**), falling back to `APPLE_MAIL_READ_KNOWN_SENDERS` (MCP env) | *(no file + empty env — personal mail ships DARK)* | Full addresses and/or bare domains (e.g. `jane@example.com,acme.com`), comma-separated, in either source. A personal-account message is kept iff its sender's address OR domain is listed. **Why file-first:** the real list is the person's personal address book (hundreds of contacts) — it must never sit in the git-tracked `.mcp.json` (privacy), and edits to the installed `.mcp.json` are wiped on every marketplace reinstall; the local file survives reinstalls and lives in the same FileVault-protected, git-free, Dropbox-free dir as `config.json`. The file **path is hardcoded** (not env-configurable — a configurable path would let config injection point the privacy filter at an attacker-controlled file). **Fail-closed:** a missing/unreadable/malformed/empty file falls back to the env; empty env ⇒ personal accounts return NOTHING. A file problem can only narrow the read, never widen it. The run-log records `known_senders_source: file\|env\|none` + count only — never the addresses. Populating a source is the switch that turns personal mail ON (Derick's decision — see the R2 note below). |
| **From-account allow-list (sender)** | `APPLE_MAIL_DRAFT_FROM_ACCOUNTS` (MCP env) | `ara-data.com,ARAdata.onmicrosoft.com` | **Unchanged — ARA business only.** Bounds which account a draft can be composed **FROM** — the person's own ARA mailbox(es). `create_apple_mail_draft`'s required `from_account` must be on this list, or the draft is rejected. A personal account is never a draft sender. |
| **Recipient allow-list (drafts)** | `APPLE_MAIL_DRAFT_ALLOWED_DOMAINS` (MCP env) | `ara-data.com` (add `ARAdata.onmicrosoft.com` if drafting for that domain) | **Unchanged — ARA business only.** Bounds who an injection could ever draft to. Personal contacts (Gmail/iCloud/iMessage) are never valid nudge recipients. Keep conservative. |

> **R2 / "Primary category" note.** Apple Mail's macOS Categories (Primary /
> Transactions / Updates / Promotions) are **not exposed to AppleScript** (Mail 16
> scripting dictionary has no `category` property on the `message` class — verified
> via `sdef`). So the requested "read only the Primary category for personal
> accounts" is not directly implementable. The **known-senders filter above is the
> reliable substitute** (named correspondents in, promo/transactional/2FA/newsletter
> out) and it matches the iMessage known-contacts rule. It ships **fail-closed
> (empty ⇒ personal reads nothing)**; populate `APPLE_MAIL_READ_KNOWN_SENDERS` to
> turn personal mail on. This is Derick's decision to make — see Boris's finding memo.

**Group B — the two per-deployment values: collected by the skill on FIRST RUN,
not at install.** The skill (SKILL.md Step 0.5) asks for these the first time it
runs and persists them to a local config file. Nothing to paste at install time.

| What | Where it's persisted | Default / example | Notes |
|---|---|---|---|
| **Dropbox project folder** | `~/.ara-business-pulse/config.json` → `dropbox_project_folder` | `~/Library/CloudStorage/Dropbox/<ARA project folder>` | Collected on first run. Must be set **"Available offline"** so Cowork reads files on disk, not cloud placeholders. `[VERIFY]` exact path per Mac. |
| **Teams webhook URL — OPTIONAL** | `~/.ara-business-pulse/config.json` → `teams_webhook_url` (**SECRET**) | *(per channel — or skipped)* | Collected on first run; the person may **skip** it ("skip" / "not yet"). If absent, Step 6 is skipped and the rest of the pulse still delivers; add it later by saying "update my Teams webhook". **Never** commit, never write to the digest/chat, never put in the Dropbox folder, never echo to a log. Bound to one channel. Rotate if leaked (COND-3). |

### The local config file (`~/.ara-business-pulse/config.json`)

The skill persists Group B here — **on local disk, in the person's home directory
(FileVault-protected), NOT in git and NOT inside the Dropbox project folder.**
Shape:

```json
{ "dropbox_project_folder": "~/Library/CloudStorage/Dropbox/<ARA project>",
  "teams_webhook_url": "https://..." }
```

`teams_webhook_url` is omitted/`null` when Teams is skipped. The skill reads this
file at the top of every run; if it's absent or missing `dropbox_project_folder`
(or the user says "reconfigure my pulse" / "update my Teams webhook") it re-runs
the short first-run setup conversation, otherwise it proceeds with no prompting.

> **Why `~/.ara-business-pulse/`, not `${CLAUDE_PLUGIN_DATA}`:**
> `${CLAUDE_PLUGIN_DATA}` is the framework's persistent-state dir, but plain
> skill-side file read/write under it can trip Cowork's protected-directory
> permission prompt (live-grounded 2026-06-24, claude-code issue #41156 —
> re-verify). A plain `~/` path is the simplest reliable mechanism and is equally
> outside git + outside Dropbox + FileVault-protected.

Run-state (not config): `state/last-run.txt` in the project folder holds the last
successful run timestamp = the next run's `since_iso` cutoff. Absent ⇒ default to
24h ago.

> At install the employee only confirms the `.mcp.json` allow-list defaults (Group
> A — already safe) and grants one macOS permission. The Dropbox path and the
> optional Teams webhook (Group B) are collected by the skill itself on first run —
> nothing to paste at install.
