"""Tests for swipe steps."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import flow as F

class FakeDevice:

    def __init__(self):
        self.swipes = []
        self.taps = []

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.swipes.append((x1, y1, x2, y2, duration_ms))

    def tap(self, x, y):
        self.taps.append((x, y))

class FakeBot:

    def __init__(self, scale=1.0, screen=(1600, 900), same_aspect=True, seen=None):
        self.device = FakeDevice()
        self.scale = scale
        self.screen_w, self.screen_h = screen
        self.base_w, self.base_h = 1600, 900
        self.same_aspect = same_aspect
        self.buttons = {"row_button": {"pos": None, "template": "row.png", "rect": None}}
        self.seen = seen
        self.captures = 0

    def capture(self):
        self.captures += 1

    def find(self, name, threshold=None):
        return self.seen

    def is_visible(self, name, threshold=None):
        return self.seen is not None

    def to_screen(self, x, y):
        s = self.scale
        if self.same_aspect:
            return int(round(x * s)), int(round(y * s))
        nx = x * s if x <= self.base_w / 2 else self.screen_w - (self.base_w - x) * s
        ny = y * s if y <= self.base_h / 2 else self.screen_h - (self.base_h - y) * s
        return int(round(nx)), int(round(ny))

def runner_with(bot):
    fr = F.FlowRunner.__new__(F.FlowRunner)
    fr.bot = bot
    fr.log = lambda *_a: None
    fr.should_stop = lambda: False
    fr.wait_if_paused = lambda: None
    fr._in_game = False
    return fr

class SwipeIsAKnownActionTest(unittest.TestCase):
    def test_swipe_is_in_the_action_table(self):
        self.assertIn("swipe", F.ACTIONS)
        _label, fields = F.ACTIONS["swipe"]
        for need in ("target", "x", "y", "dx", "dy", "swipe_ms", "after", "optional"):
            self.assertIn(need, fields, f"ช่อง {need} หายไปจากฟอร์มของ swipe")

    def test_a_swipe_step_survives_loading(self):
        steps = F.steps_from([{"action": "swipe", "x": 800, "y": 620,
                               "dx": 0, "dy": -300, "swipe_ms": 420}])
        self.assertEqual(len(steps), 1, "ขั้นปัดจอถูกทิ้งตอนโหลด")
        self.assertEqual((steps[0].dx, steps[0].dy, steps[0].swipe_ms), (0, -300, 420))

    def test_pace_never_stretches_the_swipe_itself(self):
        f = F.Flow(steps=F.steps_from([{"action": "swipe", "dy": -300,
                                        "swipe_ms": 400, "after": 1.0}]))
        F.scale_pace(f, 3.0)
        self.assertEqual(f.steps[0].swipe_ms, 400)
        self.assertAlmostEqual(f.steps[0].after, 3.0)

class SwipeGeometryTest(unittest.TestCase):
    def test_distance_scales_with_the_screen(self):
        bot = FakeBot(scale=2.0, screen=(3200, 1800))
        step = F.Step(action="swipe", x=800, y=620, dy=-300, after=0)
        self.assertEqual(runner_with(bot)._play("0", step), "ok")
        x1, y1, x2, y2, _ms = bot.device.swipes[0]
        self.assertEqual((x1, y1), (1600, 1240))
        self.assertEqual((x2, y2), (1600, 640))

    def test_crossing_the_middle_of_a_different_shaped_screen(self):
        bot = FakeBot(scale=1.2, screen=(2400, 1080), same_aspect=False)
        step = F.Step(action="swipe", x=1000, y=450, dx=-500, after=0)
        self.assertEqual(runner_with(bot)._play("0", step), "ok")
        x1, y1, x2, y2, _ms = bot.device.swipes[0]
        self.assertEqual((x1, y1), bot.to_screen(1000, 450))
        self.assertEqual(x2, x1 - 600, "ระยะปัดไม่ใช่ delta * scale")
        self.assertEqual(y2, y1)
        wrong = bot.to_screen(1000 - 500, 450)[0]
        self.assertNotEqual(x2, wrong, "ยังแมปจุดปลายด้วย to_screen อยู่")

    def test_end_point_is_clamped_into_the_screen(self):
        bot = FakeBot(scale=1.0, screen=(1600, 900))
        step = F.Step(action="swipe", x=800, y=100, dy=-400, after=0)
        self.assertEqual(runner_with(bot)._play("0", step), "ok")
        _x1, _y1, _x2, y2, _ms = bot.device.swipes[0]
        self.assertEqual(y2, 0, "ปลายหลุดขอบจอ = แอนดรอยด์ตัดเอง ได้ระยะไม่เท่าที่สั่ง")

    def test_the_anchor_image_moves_the_start_point(self):
        bot = FakeBot(scale=1.0, seen=(430, 705))
        step = F.Step(action="swipe", target="row_button", x=800, y=620,
                      dy=-300, after=0)
        self.assertEqual(runner_with(bot)._play("0", step), "ok")
        x1, y1, _x2, y2, _ms = bot.device.swipes[0]
        self.assertEqual((x1, y1), (430, 705))
        self.assertEqual(y2, 405)
        self.assertGreaterEqual(bot.captures, 1, "ไม่ได้จับภาพใหม่ก่อนหาจุดยึด")

    def test_missing_anchor_falls_back_to_the_typed_point(self):
        bot = FakeBot(scale=1.0, seen=None)
        step = F.Step(action="swipe", target="row_button", x=800, y=620,
                      dy=-300, after=0)
        self.assertEqual(runner_with(bot)._play("0", step), "ok")
        self.assertEqual(bot.device.swipes[0][:2], (800, 620))

    def test_nothing_to_swipe_from_is_skipped_not_tapped_at_the_corner(self):
        bot = FakeBot(scale=1.0, seen=None)
        step = F.Step(action="swipe", dy=-300)
        self.assertEqual(runner_with(bot)._play("0", step), "skip")
        self.assertEqual(bot.device.swipes, [])

    def test_zero_distance_is_skipped(self):
        bot = FakeBot(scale=1.0)
        step = F.Step(action="swipe", x=800, y=620)
        self.assertEqual(runner_with(bot)._play("0", step), "skip")
        self.assertEqual(bot.device.swipes, [], "ปัดระยะ 0 = แตะค้าง ไม่ใช่การเลื่อน")

    def test_not_optional_turns_a_bad_swipe_into_a_failure(self):
        bot = FakeBot(scale=1.0)
        step = F.Step(action="swipe", dy=-300, optional=False)
        self.assertEqual(runner_with(bot)._play("0", step), "fail")

class SwipeLogPrivacyTest(unittest.TestCase):

    def setUp(self):
        self._detail = F.DETAIL

    def tearDown(self):
        F.DETAIL = self._detail

    def _lines(self, detail):
        F.DETAIL = detail
        out = []
        bot = FakeBot(scale=1.0)
        fr = runner_with(bot)
        fr.log = out.append
        fr._play("0", F.Step(action="swipe", target="row_button",
                             x=800, y=620, dy=-300, after=0))
        return out

    def test_customer_build_says_nothing_about_coordinates(self):
        self.assertEqual(self._lines(detail=False), [])

    def test_dev_build_still_shows_the_numbers(self):
        blob = "\n".join(self._lines(detail=True))
        self.assertIn("800", blob)
        self.assertIn("320", blob)

if __name__ == "__main__":
    unittest.main()
