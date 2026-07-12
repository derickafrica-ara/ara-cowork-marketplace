"""Contract test for ReadMailDriver.read_inbox parsing the read_account.applescript
output format: `META\\n<GS-framed records>` where META = `saturated(0|1) US total`.

The AppleScript itself (newest-first index walk, timing) is live-only. This pins the
PYTHON side of that contract — the META split, saturation decode, and record framing —
which is fully testable by stubbing the osascript boundary (_run).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from read_core import ReadMailDriver, _GS, _US  # noqa: E402


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


class TestReadInboxParse(unittest.TestCase):
    def test_saturated_flag_and_records_decoded(self):
        out = "1" + _US + "1234\n" + _GS.join([
            _rec("a@x.com", "Subj1", "2026-07-11 07:00:00", "body one"),
            _rec("b@y.com", "Subj2", "2026-07-11 06:30:00", "body two"),
        ])
        records, saturated = _StubDriver(out).read_inbox("ARA", "2026-07-11 06:00:00")
        self.assertTrue(saturated)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], ("a@x.com", "Subj1", "2026-07-11 07:00:00", "body one"))

    def test_not_saturated(self):
        out = "0" + _US + "42\n" + _rec("a@x.com", "S", "2026-07-11 07:00:00", "b")
        records, saturated = _StubDriver(out).read_inbox("ARA", "x")
        self.assertFalse(saturated)
        self.assertEqual(len(records), 1)

    def test_empty_stream_meta_only(self):
        records, saturated = _StubDriver("0" + _US + "0\n").read_inbox("ARA", "x")
        self.assertEqual(records, [])
        self.assertFalse(saturated)

    def test_short_record_is_padded_to_four_fields(self):
        out = "0" + _US + "1\n" + _rec("a@x.com", "Subj")  # only 2 fields
        records, _ = _StubDriver(out).read_inbox("ARA", "x")
        self.assertEqual(records, [("a@x.com", "Subj", "", "")])

    def test_body_newlines_do_not_break_meta_split(self):
        # A message body containing newlines must NOT be mistaken for the META
        # delimiter (the FIRST newline separates META from the record stream).
        body = "line1\nline2\nline3"
        out = "1" + _US + "9\n" + _rec("a@x.com", "S", "2026-07-11 07:00:00", body)
        records, saturated = _StubDriver(out).read_inbox("ARA", "x")
        self.assertTrue(saturated)
        self.assertEqual(records[0][3], body)  # body preserved intact

    def test_ceiling_is_passed_to_osascript(self):
        from config import READ_MAX_MESSAGES_PER_ACCOUNT
        drv = _StubDriver("0" + _US + "0\n")
        drv.read_inbox("ARA", "2026-07-11 06:00:00")
        self.assertEqual(drv.last_args, ["ARA", "2026-07-11 06:00:00",
                                         str(READ_MAX_MESSAGES_PER_ACCOUNT)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
