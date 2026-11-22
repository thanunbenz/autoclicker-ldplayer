"""Tests for pace scaling."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import flow as F

def _flow():
    return F.Flow(steps=[
        F.Step(action="tap", target="a", timeout=10, after=1.0),
        F.Step(action="if_seen", target="b", timeout=3, after=0.5, steps=[
            F.Step(action="tap", target="c", timeout=8, after=2.0),
        ]),
        F.Step(action="sleep", seconds=4),
    ])

class PaceTest(unittest.TestCase):
    def test_default_pace_changes_nothing(self):
        f = _flow()
        F.scale_pace(f, 1)
        self.assertEqual(f.steps[0].timeout, 10)
        self.assertEqual(f.steps[0].after, 1.0)

    def test_missing_or_bad_pace_is_ignored(self):
        for bad in (None, "", "abc", 0):
            f = _flow()
            F.scale_pace(f, bad)
            self.assertEqual(f.steps[0].timeout, 10, f"pace={bad!r} ไม่ควรเปลี่ยนอะไร")

    def test_stretches_waits_and_delays(self):
        f = _flow()
        F.scale_pace(f, 2)
        self.assertEqual(f.steps[0].timeout, 20)
        self.assertEqual(f.steps[0].after, 2.0)
        self.assertEqual(f.steps[2].seconds, 8)

    def test_reaches_nested_steps(self):
        f = _flow()
        F.scale_pace(f, 2)
        self.assertEqual(f.steps[1].steps[0].timeout, 16)
        self.assertEqual(f.steps[1].steps[0].after, 4.0)

    def test_clamped_to_max(self):
        f = _flow()
        F.scale_pace(f, 99)
        self.assertEqual(f.steps[0].timeout, 10 * F.PACE_MAX)

    def test_does_not_touch_poll(self):
        f = _flow()
        before = f.steps[0].poll
        F.scale_pace(f, 2)
        self.assertEqual(f.steps[0].poll, before)

    def test_applied_through_override(self):
        f = _flow()
        F.apply_override(f, {"pace": 2})
        self.assertEqual(f.steps[0].timeout, 20)

if __name__ == "__main__":
    unittest.main()
