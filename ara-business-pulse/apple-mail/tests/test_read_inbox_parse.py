"""Unit tests for the R-SAFE cap: (1) ReadMailDriver.read_inbox parsing the
read_account.applescript output, and (2) the ordering-INDEPENDENT completeness
DECISION `_is_saturated` (moved out of the untested AppleScript into Python).

Output format: `META\\n<GS-framed records>` where META =
`examined US saw_out_of_window(0|1) US total`.

The AppleScript itself (newest-first bulk fetch, timing) is live-only. This pins the
PYTHON side of that contract — META decode, record framing, and the saturation
decision — which is fully testable by stubbing the osascript boundary (_run).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import READ_MAX_MESSAGES_PER_ACCOUNT  # noqa: E402
from read_core import ReadMailDriver, _GS, _US, _is_saturated  # noqa: E402


class _StubDriver(ReadMailDriver):
    """A ReadMailDriver whose osascript boundary (_run) returns a fixed string, so
    the read_inbox parser can be exercised without Mail.app / osascript."""

    def __init__(self, out: str):
        super().__init__()
        self._out = out
        self.last_args: list[str] | None = None

    def _run(self, script, args):  # type: ignore[override]
        self.last_args = list(args)
        return self._out


def _rec(*fields: str) -> str:
    return _US.join(fields)


def _meta(examined: int, saw_oow: int, total: int) -> str:
    return f"{examined}{_US}{saw_oow}{_US}{total}"


class TestReadInboxParse(unittest.TestCase):
    def test_metadata_and_records_decoded(self):
        out = _meta(2, 1, 1234) + "\n" + _GS.join([
            _rec("a@x.com", "Subj1", "2026-07-11 07:00:00", "body one"),
            _rec("b@y.com", "Subj2", "2026-07-11 06:30:00", "body two"),
        ])
        records, examined, saw_oow, total = _StubDriver(out).read_inbox("ARA", "cut")
        self.assertEqual(examined, 2)
        self.assertTrue(saw_oow)
        self.assertEqual(total, 1234)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], ("a@x.com", "Subj1", "2026-07-11 07:00:00", "body one"))

    def test_empty_stream_meta_only(self):
        records, examined, saw_oow, total = _StubDriver(_meta(0, 0, 0) + "\n").read_inbox("ARA", "x")
        self.assertEqual(records, [])
        self.assertEqual((examined, saw_oow, total), (0, False, 0))

    def test_short_record_is_padded_to_four_fields(self):
        out = _meta(1, 1, 1) + "\n" + _rec("a@x.com", "Subj")  # only 2 fields
        records, *_ = _StubDriver(out).read_inbox("ARA", "x")
        self.assertEqual(records, [("a@x.com", "Subj", "", "")])

    def test_body_newlines_do_not_break_meta_split(self):
        # A message body containing newlines must NOT be mistaken for the META
        # delimiter (the FIRST newline separates META from the record stream).
        body = "line1\nline2\nline3"
        out = _meta(9, 0, 9) + "\n" + _rec("a@x.com", "S", "2026-07-11 07:00:00", body)
        records, examined, saw_oow, _ = _StubDriver(out).read_inbox("ARA", "x")
        self.assertEqual(examined, 9)
        self.assertFalse(saw_oow)
        self.assertEqual(records[0][3], body)  # body preserved intact

    def test_garbage_meta_defaults_defensively(self):
        records, examined, saw_oow, total = _StubDriver("junk\n").read_inbox("ARA", "x")
        self.assertEqual((examined, saw_oow, total), (0, False, 0))
        self.assertEqual(records, [])

    def test_ceiling_is_passed_to_osascript(self):
        drv = _StubDriver(_meta(0, 0, 0) + "\n")
        drv.read_inbox("ARA", "2026-07-11 06:00:00")
        self.assertEqual(drv.last_args, ["ARA", "2026-07-11 06:00:00",
                                         str(READ_MAX_MESSAGES_PER_ACCOUNT)])


class TestIsSaturated(unittest.TestCase):
    """The ordering-independent completeness decision (Floyd's R-SAFE rule):
    saturated iff examined >= ceiling AND no examined message was out of window."""

    CEIL = 500

    def test_ceiling_hit_all_in_window_is_saturated(self):
        # Examined the full ceiling and even the boundary was still in-window =>
        # in-window mail may exist beyond the ceiling => CAPPED.
        self.assertTrue(_is_saturated(self.CEIL, saw_out_of_window=False, ceiling=self.CEIL))

    def test_interleaved_boundary_seen_is_not_saturated(self):
        # THE silent-drop case, now closed: examined the ceiling but at least one
        # examined message was OUT of window (e.g. an interleaved old message) => the
        # window boundary was reached; the collection (no early stop) already has
        # every in-window message => COMPLETE, not capped.
        self.assertFalse(_is_saturated(self.CEIL, saw_out_of_window=True, ceiling=self.CEIL))

    def test_small_delta_on_huge_inbox_not_falsely_capped(self):
        # A small 24h delta on a years-large inbox: we examine the ceiling but hit
        # out-of-window messages among the newest => complete, NOT falsely capped.
        self.assertFalse(_is_saturated(self.CEIL, saw_out_of_window=True, ceiling=self.CEIL))

    def test_whole_inbox_examined_is_complete(self):
        # Examined fewer than the ceiling => we saw the ENTIRE inbox => complete,
        # regardless of whether a boundary message existed.
        self.assertFalse(_is_saturated(42, saw_out_of_window=False, ceiling=self.CEIL))
        self.assertFalse(_is_saturated(0, saw_out_of_window=False, ceiling=self.CEIL))


if __name__ == "__main__":
    unittest.main(verbosity=2)
