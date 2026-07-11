"""Read-side test doubles for read_core (no Mail.app / TCC / MCP SDK required).

This is the READ-side subset of the canonical `tests/fakes.py` in the FALKE dev
tree (apple-mail-draft-mcp). The marketplace plugin currently ships read-path
tests only; the draft-side doubles (RecordingMailDriver, etc.) live in the FALKE
tree and can be ported here if/when draft tests are added to the plugin repo.
"""

from __future__ import annotations

from read_core import MailAccount, ReadMailDriver, ReadMailError, ReadMailTimeout


class FakeReadMailDriver(ReadMailDriver):
    """A ReadMailDriver backed by an in-memory 'Mail world'.

    `world` maps account NAME -> {"email": <addr>, "messages": [(sender, subject,
    date, body), ...]}. The driver records EVERY account name it was asked to
    read via read_inbox() in `self.read_calls`, so a COND-8 test can assert a
    non-allow-listed (personal) account was NEVER passed to read_inbox — i.e.
    ZERO message reads occurred against it. Enforcement happens in read_core
    (the account boundary), BEFORE this driver's read_inbox is ever called.

    Fault injection (all optional; empty defaults == the plain FALKE fake):
      - `timeout_accounts`  : read_inbox() on one of these raises ReadMailTimeout,
        modeling a large personal inbox exceeding the 90s ReadMailDriver timeout.
        A per-account DEGRADABLE fault (max-availability).
      - `error_accounts`    : read_inbox() on one of these raises a plain
        ReadMailError modeling a pre-timeout per-account STALL (rc!=0, e.g.
        AppleEvent -1712). Per WS1 this is now ALSO per-account DEGRADABLE (it is
        scoped to one account; enumeration already succeeded).
      - `list_accounts_error`: list_accounts() itself raises ReadMailError, modeling
        a SYSTEMIC enumeration failure (Mail not running / auth) — stays FAIL-LOUD.
    """

    def __init__(
        self,
        world: dict[str, dict],
        timeout_accounts: set[str] | None = None,
        error_accounts: set[str] | None = None,
        list_accounts_error: bool = False,
    ):
        super().__init__()
        self._world = world
        self._timeout_accounts = set(timeout_accounts or ())
        self._error_accounts = set(error_accounts or ())
        self._list_accounts_error = list_accounts_error
        self.list_accounts_calls = 0
        self.read_calls: list[str] = []  # account names read_inbox was called on
        self.read_cutoffs: list[str] = []

    def list_accounts(self):  # type: ignore[override]
        self.list_accounts_calls += 1
        if self._list_accounts_error:
            # Systemic enumeration failure (e.g. Mail not running) — fail loud.
            raise ReadMailError("osascript list_accounts failed (modeled)")
        return [
            MailAccount(name=name, email=info.get("email", ""))
            for name, info in self._world.items()
        ]

    def read_inbox(self, account_name, cutoff):  # type: ignore[override]
        # Record that a message-level read was attempted against this account.
        self.read_calls.append(account_name)
        self.read_cutoffs.append(cutoff)
        if account_name in self._timeout_accounts:
            # Model the live defect: enumerating this (large personal) inbox
            # exceeds the ReadMailDriver timeout. Raising the TIMEOUT subtype lets
            # read_core degrade this ONE account (max-availability); if the ships-
            # dark boundary skip regresses and this account is enumerated, the test
            # still catches it via read_calls.
            raise ReadMailTimeout(
                f"osascript read timed out (modeled) for {account_name!r}"
            )
        if account_name in self._error_accounts:
            # Pre-timeout per-account STALL surfacing as rc!=0 (AppleEvent -1712).
            raise ReadMailError(
                f"osascript read failed (rc=1): AppleEvent timed out (-1712) "
                f"for {account_name!r}"
            )
        info = self._world.get(account_name)
        if info is None:
            return []
        return list(info.get("messages", []))
