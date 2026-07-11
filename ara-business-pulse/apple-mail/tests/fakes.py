"""Read-side test doubles for read_core (no Mail.app / TCC / MCP SDK required).

This is the READ-side subset of the canonical `tests/fakes.py` in the FALKE dev
tree (apple-mail-draft-mcp). The marketplace plugin currently ships read-path
tests only; the draft-side doubles (RecordingMailDriver, etc.) live in the FALKE
tree and can be ported here if/when draft tests are added to the plugin repo.
"""

from __future__ import annotations

from read_core import MailAccount, ReadMailDriver, ReadMailError


class FakeReadMailDriver(ReadMailDriver):
    """A ReadMailDriver backed by an in-memory 'Mail world'.

    `world` maps account NAME -> {"email": <addr>, "messages": [(sender, subject,
    date, body), ...]}. The driver records EVERY account name it was asked to
    read via read_inbox() in `self.read_calls`, so a COND-8 test can assert a
    non-allow-listed (personal) account was NEVER passed to read_inbox — i.e.
    ZERO message reads occurred against it. Enforcement happens in read_core
    (the account boundary), BEFORE this driver's read_inbox is ever called.

    `timeout_accounts` (optional) models the LIVE DEFECT this fix targets: any
    account named here raises ReadMailError when read_inbox() is called on it —
    the way enumerating a large personal iCloud inbox exceeds the 90s
    ReadMailDriver timeout and fails loud. It lets a test prove not just that a
    ships-dark personal account is absent from read_calls, but that the scan
    would DIE if the boundary skip regressed and that inbox were enumerated.
    Default (empty set) is identical to the FALKE fake's behavior.
    """

    def __init__(self, world: dict[str, dict], timeout_accounts: set[str] | None = None):
        super().__init__()
        self._world = world
        self._timeout_accounts = set(timeout_accounts or ())
        self.list_accounts_calls = 0
        self.read_calls: list[str] = []  # account names read_inbox was called on
        self.read_cutoffs: list[str] = []

    def list_accounts(self):  # type: ignore[override]
        self.list_accounts_calls += 1
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
            # exceeds the ReadMailDriver timeout and fails loud (COND-5). If the
            # boundary skip regresses and this account is enumerated, the whole
            # scan dies right here — exactly the bug this fix removes.
            raise ReadMailError(
                f"osascript read timed out (modeled) for {account_name!r}"
            )
        info = self._world.get(account_name)
        if info is None:
            return []
        return list(info.get("messages", []))
