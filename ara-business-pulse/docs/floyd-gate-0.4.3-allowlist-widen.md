# Floyd Gate Report — ara-business-pulse 0.4.3 recipient allow-list widen

- **Verdict: APPROVE** — converted from approve-with-conditions on the same-day
  §8 delta re-gate; all three conditions verified closed (§10). Initial
  verdict (historical): approve-with-conditions, three conditions.
- **Date:** 2026-07-18 (initial gate + delta re-gate)
- **Reviewer:** Floyd (Technical Architect & Final Review/Validation Gate)
- **Builder:** Boris. **Directed by:** Derick (widen decision, 2026-07-18).
- **Scope:** uncommitted working-tree change in
  `/Users/africahome/ara-cowork-marketplace/` — `ara-business-pulse`
  0.4.2 → 0.4.3: `APPLE_MAIL_DRAFT_ALLOWED_DOMAINS` widened from
  `ara-data.com` to `ara-data.com,falkecorp.com,falkehoa.com` + doc sync.
  No validation-code change.
- **Asset-capture AC:** not applicable — ARA-internal tooling change, not a
  client-facing engagement deliverable or closeout.

---

## 1. Change inventory (verified against `git diff` / `git status`)

Exactly 7 modified files, all under `ara-business-pulse/`, nothing untracked:

| File | Change | Verified |
|---|---|---|
| `.mcp.json` | The one functional line: recipient env widened to 3 named domains | yes — parses, from-accounts byte-identical |
| `.claude-plugin/plugin.json` | 0.4.3 + description de-staled ("allow-listed business domains only") | yes |
| `apple-mail/server.py` | Docstring contract text only (named-domain list, fail-closed default) | yes — no code delta |
| `skills/ara-business-pulse/SKILL.md` | Two stale ARA-only body claims fixed | yes — but a third missed, see C-3 |
| `skills/…/reference/config.md` | Recipient-allow-list row updated (named domains, fail-closed default, "add only by deliberate decision") | yes |
| `README.md` | Config table row updated | yes |
| `CHANGELOG.md` | New 0.4.3 entry = canonical threat note | yes — every claim in it independently verified (§3) |

Confirmed NOT changed: `config.py`, `draft_core.py` (zero diff — the
fail-closed code default `("ara-data.com",)` is untouched),
`APPLE_MAIL_DRAFT_FROM_ACCOUNTS` (sender posture), the falke sibling (§5), the
installed cache (§5).

## 2. Validation evidence (executed, twice)

All executions at the `validate_request` level against the marketplace
(shipping) copy — no Mail.app, no drafts, no network.

| Suite | Run 1 | Run 2 |
|---|---|---|
| Boris's harness (13 checks; scratchpad `verify_allowlist_widen.py`) | 13/13 | 13/13 |
| Floyd's independent probes (24 checks; scratchpad `floyd_probes_0.4.3.py`) | 24/24 | 24/24 |
| Shipped marketplace suite (`apple-mail/tests`, unittest) | 49/49 OK | 49/49 OK |
| Pulse-server suite (regression, not in scope-claims) | 13/13 OK | — |

Floyd probe coverage beyond Boris's harness (all behaved fail-closed):

- **Homoglyph / IDN:** Cyrillic-а `fаlkecorp.com`, umlaut `fälkecorp.com`,
  punycode `xn--…` lookalike → all refused. Root cause verified in code, not
  just observed: `_ADDRESS_RE` constrains the domain to ASCII **before**
  `.lower()` runs, so no Unicode case-fold trick (probed with KELVIN SIGN
  U+212A → 'k') can normalize into an allow-listed domain. Ordering is correct.
- **Trailing dot** (`falkecorp.com.`, `falkehoa.com.`) → refused (malformed).
- **Case variance** (`MFALKE@FALKECORP.COM`) → accepted; correct behavior —
  case-insensitive exact match on the same domain, not a bypass.
- **Structural garbage:** empty domain `mfalke@`, @-less recipient, double-@,
  RFC-quoted local part containing `@`, display-name form
  `Name <addr>`, embedded newline, NBSP in domain, bytes recipient,
  whitespace-only recipient → all refused.
- **Env misconfig space:** unset / `""` / whitespace-only / `",,,"` → all
  narrow to `("ara-data.com",)`; mixed-case env entries lower-cased. Every
  degenerate env value narrows, none widens.
- **Sender posture:** `PM@FALKECORP.COM` as from-account → refused (client
  domains valid as recipients only, never as senders).
- **Bound:** 26 recipients → refused (`MAX_RECIPIENTS=25` intact).

Independent third confirmation of the fail-closed default: the Falke dev-tree
COND-6 suite run against this shipping code errors exactly one test — the one
expecting `falkecorp.com` in the *code default* — with
`recipient domain 'falkecorp.com' not on allow-list ('ara-data.com',)`.

## 3. Threat ruling (gate item 2)

**The CHANGELOG 0.4.3 threat note is ACCEPTED as accurate and sufficient.**
Every claim in it was verified by execution or code inspection:

- Named-domain exact match, no wildcard/suffix/subdomain logic — verified
  adversarially (8+ lookalike classes refused).
- Fail-closed code default preserved — verified 4 ways plus the dev-tree
  cross-check.
- Sender list untouched — byte-identical in `.mcp.json`, tested.
- Save-only tool surface (COND-2): the only Mail write verb reachable is
  `save` plus a read-only existence query; static AppleScript, argv-passed,
  `shell=False` (COND-7) — confirmed unchanged in `draft_core.py`.
- Full-recipient audit logging on created **and** rejected attempts —
  confirmed in `_log` call sites.

**Delta-risk analysis.** The widen moves the worst-case prompt-injection
outcome from "stage a self-addressed draft" (near-zero value) to "stage a
convincing client-bound draft in Derick's Drafts" (real social-engineering
value: a plausible ask to the client, sent under Derick's own hand if he is
careless). The exfil/action channel remains human-gated — the tool cannot
send; a human must open Mail and click Send on exactly the staged body. OWASP
LLM mapping: LLM01 residual is bounded by the LLM06 control (high-impact
action = Send stays human); LLM02 (sensitive content addressed off-org) is
bounded by the same gate. The residual risk therefore concentrates entirely on
**human review vigilance at Send time** — which is why C-1 below is a
condition, not a suggestion.

**Ruling on "no additional tool-level control warranted": CONCUR.**
A draft-body banner is impossible by design (BODY-CLEAN — the body ships to
the client on Send and must stay clean); a subject prefix has the identical
defect; an in-tool confirmation step duplicates the human Send gate without
adding information. The correct layer for the residual is the digest (skill
layer). No tool/code change required for 0.4.3.

## 4. Conditions (must land before ship; all in files this change already touches)

- **C-1 — Digest must name client-bound drafts (skill layer).** Boris's
  recommendation, adopted as a condition. SKILL.md (Step 4 and/or the digest
  composition step) must require the digest to explicitly call out drafts
  staged to non-ARA domains, e.g. *"2 drafts staged to falkecorp.com — review
  before sending."* Rationale: the entire residual risk of this widen is
  human-send vigilance, BODY-CLEAN forbids marking the draft itself, so the
  digest is the only surface where the flag can live. No contract/code change.
- **C-2 — Document the go-live/update chain in-repo.** Nothing in the repo
  currently states that the running `apple-mail` MCP server keeps the prior
  env until respawned. Add to the CHANGELOG 0.4.3 entry (or README): *after
  updating to 0.4.3, restart the session — the widened recipient list is not
  live until the MCP server respawns.* Without this, the predictable failure
  mode is "updated but client drafts still refused" (fail-safe direction, but
  a guaranteed confusion).
- **C-3 — Fix the missed stale claim in SKILL.md frontmatter.** The YAML
  `description` (lines 11–12) still reads "DRAFT ONLY, **ARA business only** —
  the human sends." Boris fixed the two body claims but missed the frontmatter
  — the first contract text a model reads when selecting the skill, now
  internally inconsistent with the body. Errs in the narrowing direction (can
  only cause a refused legitimate draft, never a widened one) — severity LOW,
  but it fails the claims-vs-enforcement standard this change was held to.
  One-line fix: "named business domains only (ARA + named client domains)."

## 5. Environment verifications (gate items 5)

- **Falke sibling unaffected — verified two ways.** (1) The
  `ara-cowork-marketplace` repo contains only `ara-business-pulse`;
  `falke-business-pulse` lives in a different repo entirely
  (`github.com/ara-data-ai/ara-falke-marketplace-public`), so this diff
  structurally cannot touch it. (2) Its installed cache (0.5.1, SHA
  `3e6552e`) retains its own client-gated posture
  (recipients `falkecorp.com`; from-accounts `falkecorp.com,falkehoa.com`).
- **Change not silently live — verified.** `installed_plugins.json` pins
  `ara-business-pulse@ara-marketplace` at **0.4.1** (cache path
  `…/cache/ara-marketplace/ara-business-pulse/0.4.1`, SHA `ef56c51`), and the
  cached `.mcp.json` still ships `"ara-data.com"` only.

## 6. Pre-existing gaps — disposition (gate item 6; documented debt, not blockers)

- **D-1 — CHANGELOG missing 0.4.1/0.4.2 entries.** Backfill content is
  knowable directly from git history: 0.4.1 = `ef56c51` (P1 parseISO
  month-rollover fix, Floyd gate delta 5); 0.4.2 = `4c1b8da` (digest-template
  comment-close leak fix). Since C-2 edits the CHANGELOG anyway, backfilling
  two one-line entries in the same commit is near-free — **strongly
  recommended, same commit**, not blocking.
- **D-2 — Draft-side COND-2/5/6/7 suite not shipped in the ARA flavor.**
  Confirmed: `apple-mail/tests/` ships read-side suites only; the
  security-critical draft-path suite lives only in the Falke dev tree
  (`FALKE/01_Chief_of_Staff/phase2-build/apple-mail-draft-mcp/tests/`). This
  very gate had to rely on ad-hoc scratchpad harnesses — that is the cost of
  the gap. Port evidence: 26/27 dev-tree draft-side tests pass against the
  shipping ARA code as-is; the single error is the falke-flavor default
  expectation (adapt or make the test set env explicitly). **Disposition:
  port as the next change (0.4.4), folding in Boris's 13 harness checks and
  Floyd's 24 probes as permanent regression cases. Gate policy from here: the
  next change touching the draft path does not pass this gate without an
  in-situ draft-side suite.**
- **D-3 — Minor doc drift observed (pre-existing, one-liners, next commit):**
  (a) marketplace-level `.claude-plugin/marketplace.json` description still
  says "read both ARA mailboxes" — stale since the 0.4.0 four-account read
  widen (this is the text shown at install approval); (b) README's fresh-
  install lines reference the `ara-plugins` marketplace alias while the
  machine registers `ara-marketplace`, and the marketplace-add URL is a
  placeholder. Neither affects the 0.4.3 update chain.

## 7. Go-live chain (confirmed correct, must be written down — C-2)

1. Commit the 7-file change (plus C-1/C-2/C-3 edits) in
   `/Users/africahome/ara-cowork-marketplace/`.
2. Push to `github.com/derickafrica-ara/ara-cowork-marketplace` — verified as
   the exact source URL the `ara-marketplace` entry in
   `~/.claude/plugins/known_marketplaces.json` pulls from.
3. Derick updates the plugin to 0.4.3 (marketplace update + plugin update; the
   installer pins a fresh versioned cache dir, as it did for 0.4.1).
4. **Session restart** — the running `apple-mail` MCP server process keeps the
   old env (`ara-data.com` only) until respawned. Until restart, client-bound
   drafts keep being refused (fail-safe, but confusing — hence C-2).

## 8. Re-gate protocol (what I re-verify on the conditions delta)

Fast delta check, no full re-review: (1) SKILL.md — C-1 digest rule present
and C-3 frontmatter fixed, plus a grep for any new stale-claim regression;
(2) CHANGELOG/README — C-2 restart note present (and D-1 backfill if taken);
(3) re-run the shipped 49-test suite + both harnesses once (docs-only deltas
should leave all three green); (4) confirm no file outside the named set
changed.

## 9. FMEA snapshot

| Failure mode | Effect | Control | Residual |
|---|---|---|---|
| Injection stages convincing client-bound draft | Human sends a social-engineered email to the client | Save-only tool; human Send gate; COND-1; run-log; digest flag (C-1) | LOW-MED, accepted with C-1 |
| Env lost/typo'd at deploy | Narrows to ara-data.com; client drafts refused | Fail-closed code default (verified 4 ways) | LOW, fail-safe |
| Lookalike/homoglyph/IDN recipient | Off-org exfil recipient | ASCII-shape-before-lowercase + exact match (verified adversarially) | LOW |
| Session not restarted after update | Old narrow env persists; refusals continue | C-2 documentation | LOW, fail-safe |
| Docs claim ≠ enforcement | Model over/under-refuses | C-3 + D-3; grep re-check at re-gate | LOW |
| Falke sibling perturbed | Client posture drift | Separate repo (structural); cache verified | NONE observed |

---

## 10. Conversion record — §8 delta re-gate (2026-07-18, same day)

Boris closed the conditions; delta verified per the §8 protocol. **Verdict
converted to APPROVE.**

**Delta inventory.** Same 7 files as the initial gate plus
`.claude-plugin/marketplace.json` (D-3). The `server.py`, `.mcp.json`, and
`plugin.json` hunks are unchanged from the gated state — the grep-filtered
`*.py` diff shows only the previously-gated docstring hunk. **No executable
validation code touched** (Boris's claim, confirmed).

**Conditions verified closed by reading the landed text:**

- **C-1 CLOSED.** SKILL.md Step 4 now *requires* ("you **MUST** name
  client-bound drafts explicitly, per domain … never buried in a count") with
  the falkecorp.com example, the BODY-CLEAN rationale, and the
  "Floyd gate 0.4.3, C-1" tag. Requirement language, not recommendation.
- **C-2 CLOSED.** CHANGELOG 0.4.3 carries the go-live/restart block: env fixed
  at MCP-server spawn; full chain commit → push → update to 0.4.3 → session
  restart/reload; until then client-bound drafts still (correctly) refused.
- **C-3 CLOSED.** SKILL.md frontmatter now reads "DRAFT ONLY, to named
  business domains only — ARA + named client domains; the human sends."

**Debt items taken early:** D-1 backfilled (0.4.2 = `4c1b8da`, 0.4.1 =
`ef56c51`, both marked "entry backfilled at 0.4.3"); D-3 marketplace.json
description refreshed to the accurate read + draft posture. **Boris's own
additional catch** (beyond my C-3): the SKILL.md "never do" list (~line 620)
said "recipient/from allow-lists stay ARA-business-only"; now correctly
split — from-account half retained (true), recipient half corrected to "named
business domains only (ARA + named client domains; COND-6)." Verified matches
enforcement.

**Delta evidence (executed):** three JSONs parse (`marketplace.json`,
`.mcp.json`, `plugin.json`); Boris harness 13/13; Floyd probes 24/24; shipped
suite 49/49 — all green post-delta, consistent with a docs-only change.
Stale-claim sweep: five remaining grep hits, all verified CORRECT usage
(CHANGELOG fail-closed/historical/restart narrative, config.md and server.py
fail-closed-default descriptions — each states behavior I proved by
execution). No stale posture claim remains in shipped text.

**D-2 stands as recorded debt** with the gate policy unchanged: the next
change touching the draft path does not pass this gate without an in-situ
draft-side suite in `ara-business-pulse/apple-mail/tests/`.

Cleared to ship: commit → push to
`github.com/derickafrica-ara/ara-cowork-marketplace` → update installed plugin
to 0.4.3 → session restart (now documented in CHANGELOG 0.4.3 per C-2).

---

*Evidence retained in session scratchpad: `verify_allowlist_widen.py` (Boris,
run 3x total), `floyd_probes_0.4.3.py` (Floyd, 24 probes, run 3x total),
`port-check/` (dev-tree draft-suite cross-run). Shipped suites executed in
place (49/49 x3).*
