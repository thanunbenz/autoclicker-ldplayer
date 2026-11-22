"""Tests for text input steps."""
import re
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import flow as F
from bot.device import Device

APP = Path(__file__).resolve().parent.parent
FLOW_HTML = APP / "editor" / "flow.html"

class FakeDevice:

    def __init__(self):
        self.typed = []
        self.keys = []
        self.taps = []

    def text(self, body):
        self.typed.append(body)

    def key(self, keycode):
        self.keys.append(keycode)

    def tap(self, x, y):
        self.taps.append((x, y))

class FakeBot:
    def __init__(self, seen=True):
        self.device = FakeDevice()
        self.buttons = {"search_box": {"pos": None, "template": "s.png", "rect": None}}
        self.seen = seen
        self.tapped = []

    def capture(self):
        pass

    def is_visible(self, name, threshold=None):
        return self.seen

    def tap(self, name, threshold=None):
        self.tapped.append(name)
        return True

def runner_with(bot, found=(10, 10)):
    fr = F.FlowRunner.__new__(F.FlowRunner)
    fr.bot = bot
    fr.log = lambda *_a: None
    fr.should_stop = lambda: False
    fr.wait_if_paused = lambda: None
    fr.work_taps = 0
    fr.said = []
    fr._tech = lambda msg: fr.said.append(msg)
    fr._sleep = lambda _s: True
    fr._wait_visible = lambda _n, _t, want=True: found
    return fr

def play(fr, **kw):
    step = F.Step(action="type_text", **kw)
    return fr._type_text(step, "[1] พิมพ์ข้อความ")

class ActionTableTest(unittest.TestCase):
    def test_it_is_a_known_action_with_every_field_it_needs(self):
        self.assertIn("type_text", F.ACTIONS)
        _label, fields = F.ACTIONS["type_text"]
        for need in ("target", "timeout", "text", "submit", "after", "optional"):
            self.assertIn(need, fields, f"ช่อง {need} หายไปจากฟอร์มของ type_text")

    def test_a_step_survives_loading(self):
        steps = F.steps_from([{"action": "type_text", "target": "search_box",
                               "text": "angel wing", "submit": True}])
        self.assertEqual(len(steps), 1, "ขั้นพิมพ์ข้อความถูกทิ้งตอนโหลด")
        self.assertEqual((steps[0].text, steps[0].submit), ("angel wing", True))

    def test_it_is_not_counted_as_going_somewhere(self):
        self.assertNotIn("type_text", F.MOVE_ACTIONS)

    def test_it_can_never_become_a_gate(self):
        self.assertNotIn("type_text", F.GOTO_ACTIONS)

class EscapingTest(unittest.TestCase):

    def _sent(self, body):
        d = Device.__new__(Device)
        d._input_lock = threading.Lock()
        out = []
        d._run = lambda *a, **k: out.append(a)
        d.text(body)
        return out[0]

    def test_the_whole_string_is_quoted(self):
        args = self._sent("angel wing")
        self.assertEqual(args, ("shell", "input text 'angel wing'"))

    def test_a_single_quote_does_not_break_out(self):
        args = self._sent("it's")
        self.assertEqual(args[1], "input text 'it'\\''s'")

    def test_shell_metacharacters_stay_inside_the_quotes(self):
        for bad in ("a & b", "a; rm -rf /", "a $HOME b", "a | b", "a > b"):
            with self.subTest(text=bad):
                sent = self._sent(bad)[1]
                self.assertTrue(sent.startswith("input text '") and sent.endswith("'"),
                                f"{bad!r} หลุดออกนอก quote")

class PlayTest(unittest.TestCase):
    def test_it_types_the_text(self):
        bot = FakeBot()
        fr = runner_with(bot)
        self.assertEqual(play(fr, text="angel wing"), "ok")
        self.assertEqual(bot.device.typed, ["angel wing"])

    def test_enter_is_a_switch_not_a_habit(self):
        bot = FakeBot()
        play(runner_with(bot), text="abc")
        self.assertEqual(bot.device.keys, [], "กด Enter ทั้งที่ไม่ได้สั่ง")

        bot2 = FakeBot()
        play(runner_with(bot2), text="abc", submit=True)
        self.assertEqual(bot2.device.keys, ["KEYCODE_ENTER"])

    def test_no_text_means_nothing_is_sent(self):
        for empty in ("", "   "):
            bot = FakeBot()
            fr = runner_with(bot)
            with self.subTest(text=repr(empty)):
                self.assertEqual(play(fr, text=empty), "skip")
                self.assertEqual(bot.device.typed, [], "ยิงข้อความว่างเข้าเกม")

    def test_no_text_fails_the_step_when_it_is_not_optional(self):
        bot = FakeBot()
        self.assertEqual(play(runner_with(bot), text="", optional=False), "fail")

    def test_the_search_box_is_tapped_once_before_typing(self):
        bot = FakeBot()
        fr = runner_with(bot)
        self.assertEqual(play(fr, target="search_box", text="abc"), "ok")
        self.assertEqual(bot.tapped, ["search_box"], "แตะช่องค้นหาซ้ำ/ไม่แตะเลย")
        self.assertEqual(fr.work_taps, 1)

    def test_typing_happens_after_the_tap(self):
        bot = FakeBot()
        play(runner_with(bot), target="search_box", text="abc")
        self.assertEqual(bot.device.typed, ["abc"])

    def test_a_missing_search_box_skips_instead_of_typing_into_nowhere(self):
        bot = FakeBot()
        fr = runner_with(bot, found=None)
        self.assertEqual(play(fr, target="search_box", text="abc"), "skip")
        self.assertEqual(bot.device.typed, [], "พิมพ์ทั้งที่หาช่องไม่เจอ")

    def test_an_uncalibrated_search_box_skips_too(self):
        bot = FakeBot()
        fr = runner_with(bot)
        self.assertEqual(play(fr, target="no_such_box", text="abc"), "skip")
        self.assertEqual(bot.device.typed, [])

    def test_text_the_keyboard_cannot_type_is_called_out(self):
        bot = FakeBot()
        fr = runner_with(bot)
        play(fr, text="ปีกนางฟ้า")
        self.assertTrue(any("พิมพ์ไม่ได้" in m for m in fr.said),
                        f"ไม่ได้เตือนเรื่องตัวอักษรที่พิมพ์ไม่ติด: {fr.said}")

    def test_plain_english_is_not_called_out(self):
        bot = FakeBot()
        fr = runner_with(bot)
        play(fr, text="angel wing")
        self.assertFalse(any("พิมพ์ไม่ได้" in m for m in fr.said),
                         "เตือนทั้งที่เป็นภาษาอังกฤษล้วน")

    def test_the_user_facing_log_never_says_anything(self):
        said = []
        bot = FakeBot()
        fr = runner_with(bot)
        fr.log = said.append
        play(fr, target="search_box", text="abc")
        self.assertEqual(said, [], f"พูดใส่ log ของผู้ใช้: {said}")

class EditorTest(unittest.TestCase):

    def setUp(self):
        self.body = FLOW_HTML.read_text(encoding="utf-8")

    def test_the_text_box_is_a_text_input_not_a_number(self):
        m = re.search(r"\btext:\s*\{[^}]*type:\s*\"(\w+)\"", self.body)
        self.assertIsNotNone(m, "FIELD ไม่มีช่อง text")
        self.assertEqual(m.group(1), "text", "ช่องข้อความไม่ได้เป็นชนิด text")
        self.assertIn('cfg.type === "text"', self.body,
                      "renderEditor ยังไม่รู้จักช่องชนิด text (ช่องจะไม่โผล่)")

    def test_the_enter_switch_is_a_checkbox(self):
        m = re.search(r"\bsubmit:\s*\{[^}]*type:\s*\"(\w+)\"", self.body)
        self.assertIsNotNone(m, "FIELD ไม่มีช่อง submit")
        self.assertEqual(m.group(1), "bool")

    def test_the_label_warns_about_thai(self):
        m = re.search(r"\btext:\s*\{\s*label:\s*\"([^\"]+)\"", self.body)
        self.assertIsNotNone(m)
        self.assertIn("อังกฤษ", m.group(1),
                      "ป้ายไม่ได้บอกว่าพิมพ์ไทยไม่ได้ = คนทำแผนจะเจอเอาตอนรัน")

    def test_new_step_defaults_match_the_python_dataclass(self):
        step = F.Step(action="type_text")
        block = self.body[self.body.index("const DEFAULTS = "):]
        block = block[:block.index("};")]
        m = re.search(r"\btext:\s*\"([^\"]*)\"", block)
        self.assertIsNotNone(m, "DEFAULTS ไม่มี text")
        self.assertEqual(m.group(1), step.text)
        m = re.search(r"\bsubmit:\s*(true|false)", block)
        self.assertIsNotNone(m, "DEFAULTS ไม่มี submit")
        self.assertEqual(m.group(1) == "true", step.submit)

    def test_the_card_warns_when_there_is_no_text(self):
        start = self.body.index("function stepProblem(")
        fn = self.body[start:self.body.index("\n    }", start)]
        self.assertIn('s.action === "type_text"', fn,
                      "stepProblem ยังไม่รู้จักขั้นพิมพ์ข้อความ")
        self.assertIn("ยังไม่ได้ใส่ข้อความ", fn)

if __name__ == "__main__":
    unittest.main()
