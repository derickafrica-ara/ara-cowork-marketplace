-- read_account.applescript
--
-- COND-7 (AppleScript string-injection prevention) + bounded-delta read + CAP.
--
-- This script is STATIC. The account name, cutoff timestamp, and message ceiling
-- arrive at runtime as elements of `argv` and are bound to variables — they are
-- DATA to the AppleScript runtime, never source. A value containing quotes, an
-- ampersand shell-call payload, a Mail verb word, backslashes, etc. is literal
-- text and cannot execute. (Same parameterized-query discipline as create_draft.)
--
-- It reads ONLY the INBOX of ONE named, allow-listed account (the Python layer
-- has already filtered to allow-listed accounts before invoking this — COND-8).
--
-- CAP (ADR docs/adr/0001 — fixes the ~90s timeout on years-large personal inboxes):
-- instead of `messages whose date received > cutoff` — which walks the ENTIRE
-- inbox (O(inbox)) and timed out at 90s — this reads the inbox NEWEST-FIRST BY
-- INDEX (positional, O(1) per message) and stops as soon as it passes the cutoff
-- (delta complete) OR after examining `ceiling` messages (saturated). So the read
-- is bounded to O(ceiling), never O(inbox). Newest-first completeness (read ALL
-- in-window messages, not "N most recent then filter") means known-sender mail
-- buried under newsletter noise WITHIN the window is still captured.
--
-- COND-5: if the ceiling is hit BEFORE passing the cutoff, older in-window mail may
-- be unread — the SATURATED flag is set so the Python layer surfaces the account as
-- CAPPED (a partial scan), NEVER a silent truncation.
--
-- READ-ONLY: the only Mail operations are property reads. There is NO save / send /
-- delete / move / set. (COND-2, read side.) No shell is invoked.
--
-- argv contract (positional, all strings):
--   item 1 : account name (exact, as returned by list_accounts.applescript)
--   item 2 : cutoff as "YYYY-MM-DD HH:MM:SS" (space separator, not T)
--   item 3 : ceiling — max messages to examine (integer as text)
--
-- Output framing:
--   * FIRST a META line: `saturated(0|1) US total-message-count`, terminated by the
--     FIRST newline. Emitted BEFORE any record; message bodies (which may contain
--     newlines) all appear AFTER it, so a crafted body cannot spoof the header.
--   * THEN the message records: fields separated by US (0x1F), records by GS (0x1D),
--     field order: sender US subject US date US body. Each field has US/GS/control
--     bytes STRIPPED before framing, so a crafted body cannot inject a separator.
--   * Python splits on the FIRST newline (META vs records), then GS then US.
-- A message whose body is empty/blank (cached / not-yet-downloaded) is emitted with
-- an EMPTY body field; Python detects that and skips+logs it (cached-body integrity).

on stripCtrl(theText)
	-- Remove the framing/control bytes from a field so content can't break framing.
	if theText is missing value then return ""
	set theText to theText as text
	set us to (ASCII character 31)
	set gs to (ASCII character 29)
	set AppleScript's text item delimiters to {us, gs}
	set parts to text items of theText
	set AppleScript's text item delimiters to ""
	set cleaned to parts as text
	return cleaned
end stripCtrl

on run argv
	set acctName to item 1 of argv
	set cutoffText to item 2 of argv
	set ceilingText to item 3 of argv
	set cutoffDate to (my parseISO(cutoffText))
	set ceiling to (ceilingText as integer)

	set us to (ASCII character 31)
	set gs to (ASCII character 29)
	set outRecords to {}
	set saturated to false
	set totalCount to 0

	tell application "Mail"
		-- Resolve the one named account. If it doesn't exist, error (Python treats
		-- a nonzero exit / error as fail-loud).
		set theAccount to (first account whose name is acctName)
		-- The account's inbox only (bounded scope) — not every mailbox.
		set theInbox to (my resolveInbox(theAccount))
		set totalCount to (count of messages of theInbox)

		if totalCount > 0 then
			-- Determine NEWEST-first index direction WITHOUT an O(inbox) walk: compare
			-- the two endpoint messages' received dates (positional reads). Mail's
			-- inbox message index order is monotonic by date; if message 1 is newer
			-- than the last, iterate 1..N (index 1 = newest), else iterate N..1.
			set d1 to (date received of message 1 of theInbox)
			set dN to (date received of message totalCount of theInbox)
			if not (d1 < dN) then
				set idx to 1
				set step to 1
			else
				set idx to totalCount
				set step to -1
			end if

			set examined to 0
			repeat
				if (idx < 1) or (idx > totalCount) then exit repeat
				set m to message idx of theInbox
				set mDate to missing value
				try
					set mDate to (date received of m)
				end try
				set examined to examined + 1

				-- Passed the window? (dated AND not newer than cutoff) => the delta is
				-- complete; all further-back messages are older. Stop.
				if (mDate is not missing value) and (not (mDate > cutoffDate)) then
					exit repeat
				end if

				-- In-window (or undated: emit defensively — same leniency as before;
				-- Python's cached-body integrity check handles blanks).
				set theSender to ""
				set theSubject to ""
				set theDate to ""
				set theBody to ""
				try
					set theSender to (sender of m) as text
				end try
				try
					set theSubject to (subject of m) as text
				end try
				try
					set theDate to ((date received of m) as text)
				end try
				try
					set theBody to (content of m) as text
				end try
				set rec to (my stripCtrl(theSender)) & us & (my stripCtrl(theSubject)) & us & (my stripCtrl(theDate)) & us & (my stripCtrl(theBody))
				set end of outRecords to rec

				-- Hit the ceiling WITHOUT passing the cutoff => older in-window mail may
				-- be unread. Flag saturated (Python surfaces CAPPED) and stop.
				if examined is greater than or equal to ceiling then
					set saturated to true
					exit repeat
				end if

				set idx to idx + step
			end repeat
		end if
	end tell

	set satField to "0"
	if saturated then set satField to "1"
	set metaLine to satField & us & (totalCount as text)

	set AppleScript's text item delimiters to gs
	set outText to outRecords as text
	set AppleScript's text item delimiters to ""
	return metaLine & (ASCII character 10) & outText
end run

-- Resolve the inbox of ONE account, provider-agnostically and within that
-- account's own mailboxes only (preserves COND-8 — never the app-level unified
-- `inbox`, which would span every account). IMAP/Gmail expose "INBOX"; Exchange
-- exposes a differently-cased/named inbox. Try the literal IMAP name first
-- (fast, common path), then fall back to a case-insensitive name match against
-- this account's mailboxes. Fail LOUD (error) if no inbox can be resolved.
on resolveInbox(theAccount)
	tell application "Mail"
		try
			return (mailbox "INBOX" of theAccount)
		end try
		repeat with mb in (mailboxes of theAccount)
			set mbName to ""
			try
				set mbName to (name of mb) as text
			end try
			if my nameLooksLikeInbox(mbName) then return mb
		end repeat
	end tell
	error "no inbox mailbox could be resolved for the account"
end resolveInbox

-- True iff a mailbox name is the account's inbox (case-insensitive exact match
-- on "inbox"). Mirrors the draft-side nameLooksLikeDrafts discipline. Exact
-- (not substring) so it can't match e.g. an "Inbox Archive" subfolder.
on nameLooksLikeInbox(mbName)
	if mbName is "" then return false
	ignoring case
		if mbName is "inbox" then return true
	end ignoring
	return false
end nameLooksLikeInbox

-- Parse "YYYY-MM-DD HH:MM:SS" into an AppleScript date from integer components.
-- The cutoff is our own code's value, but it is still bound as data and the date
-- is built from integers — never string-templated into source.
on parseISO(s)
	set s to s as text
	set theYear to (text 1 thru 4 of s) as integer
	set theMonth to (text 6 thru 7 of s) as integer
	set theDay to (text 9 thru 10 of s) as integer
	set theHour to (text 12 thru 13 of s) as integer
	set theMin to (text 15 thru 16 of s) as integer
	set theSec to (text 18 thru 19 of s) as integer
	set d to current date
	set year of d to theYear
	set month of d to theMonth
	set day of d to theDay
	set hours of d to theHour
	set minutes of d to theMin
	set seconds of d to theSec
	return d
end parseISO
