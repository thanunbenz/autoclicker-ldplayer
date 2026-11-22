"""Tests for conditional flow steps."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import flow as F

APP = Path(__file__).resolve().parent.parent
EM_DASH = "\u2014"

class FakeBot:

    def __init__(self, known, seen=()):
        self.buttons = {n: {"pos": None, "template": f"{n}.png", "rect": None}
                        for n in known}
        self.seen = set(seen)
        self.captures = 0
        self.tapped = []

    def capture(self):
        self.captures += 1

    def is_visible(self, name, threshold=None):
        return name in self.seen

    def tap(self, name, threshold=None, jitter=4, dry=False):
        self.tapped.append(name)
        self.seen.discard(name)
        return True

def runner_for(bot, steps=(), log=None):
    fr = F.FlowRunner(bot, list(steps), log=log or (lambda *_a: None),
                      allow_spam=False)
    fr._in_game = False
    return fr

def gate(action="skip_if_seen", target="stop_label", goto=0, timeout=0):
    return F.Step(action=action, target=target, goto=goto, timeout=timeout)

class ActionTableTest(unittest.TestCase):

    def test_the_action_is_in_the_table_with_a_thai_label(self):
        self.assertIn("skip_if_seen", F.ACTIONS)
        label, _fields = F.ACTIONS["skip_if_seen"]
        self.assertTrue(label.strip(), "ไม่มีป้ายภาษาไทยให้เลือกในดรอปดาวน์")
        self.assertNotIn(EM_DASH, label, "ห้าม em-dash ในข้อความที่ผู้ใช้เห็น")
        self.assertIn("เจอ", label, "ป้ายไม่ได้บอกว่าเงื่อนไขคือ 'เจอ'")

    def test_it_asks_for_exactly_the_same_fields_as_guard(self):
        self.assertEqual(F.ACTIONS["skip_if_seen"][1], F.ACTIONS["guard"][1])
        self.assertEqual(F.ACTIONS["skip_if_seen"][1],
                         ["target", "timeout", "goto", "streak"])

    def test_it_holds_no_body(self):
        self.assertNotIn("skip_if_seen", F.NESTED_ACTIONS)

    def test_it_has_no_until_field(self):
        self.assertFalse(F.uses_until(F.Step(action="skip_if_seen")))
        f = F.Flow(steps=[gate(target="a_label")], group_defs=["ก"])
        self.assertEqual(F.choices(f), [])
        self.assertEqual(F.unreachable_choices(f), [])

    def test_it_counts_as_a_gate(self):
        self.assertIn("skip_if_seen", F.GOTO_ACTIONS)
        self.assertIn("guard", F.GOTO_ACTIONS)

    def test_a_step_of_this_kind_is_not_dropped_while_loading(self):
        steps = F.steps_from([{"action": "skip_if_seen", "target": "a_label",
                               "timeout": 2, "goto": 5}])
        self.assertEqual(len(steps), 1, "ขั้นชนิดใหม่ถูกทิ้งตอนโหลด")
        self.assertEqual(steps[0].goto, 5)

    def test_saving_and_reloading_keeps_the_jump(self):
        tmp = Path(tempfile.mkdtemp(prefix="crskip_"))
        old = F.FLOWS_DIR
        F.FLOWS_DIR = tmp
        try:
            F.save_flow(F.Flow(name="gates", steps=[gate(goto=3, timeout=2),
                                                    F.Step(action="tap", target="a"),
                                                    F.Step(action="tap", target="b")]))
            again = F.load_flow("gates")
            self.assertEqual(again.steps[0].action, "skip_if_seen")
            self.assertEqual(again.steps[0].goto, 3, "เลขขั้นปลายทางหายหลังเซฟ")
            self.assertEqual(again.steps[0].timeout, 2)
        finally:
            F.FLOWS_DIR = old
            shutil.rmtree(tmp, ignore_errors=True)

class OneImplementationTest(unittest.TestCase):

    def test_both_kinds_go_through_one_implementation(self):
        called = []
        fr = runner_for(FakeBot(["stop_label"]))
        fr._gate = lambda path, step, tag: called.append(step.action) or "ok"
        for act in ("guard", "skip_if_seen"):
            fr._play("0", gate(action=act))
        self.assertEqual(called, ["guard", "skip_if_seen"])

    def test_there_is_only_one_place_that_raises_the_jump(self):
        src = (APP / "bot" / "flow.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("raise _Goto("), 1,
                         "มีที่โยน _Goto มากกว่าหนึ่งแห่ง (ตรรกะด่านตรวจถูกก๊อป)")

class InvertedDecisionTest(unittest.TestCase):

    def _play(self, action, seen, goto=4):
        bot = FakeBot(["stop_label"], seen=["stop_label"] if seen else [])
        fr = runner_for(bot)
        try:
            return fr._play("0", gate(action=action, goto=goto)), None
        except F._Goto as g:
            return None, g.to

    def test_seeing_it_jumps_and_not_seeing_it_carries_on(self):
        status, to = self._play("skip_if_seen", seen=True)
        self.assertIsNone(status, "เจอแล้วไม่กระโดด")
        self.assertEqual(to, 3, "goto เป็นเลข 1-based · ต้องแปลงเป็น index 0-based")
        status, to = self._play("skip_if_seen", seen=False)
        self.assertEqual(status, "ok", "ไม่เจอแล้วต้องเดินต่อตามลำดับปกติ")
        self.assertIsNone(to)

    def test_guard_is_exactly_the_other_way_round(self):
        status, to = self._play("guard", seen=False)
        self.assertIsNone(status, "guard ไม่เจอแล้วต้องกระโดด (พฤติกรรมเดิม)")
        self.assertEqual(to, 3)
        self.assertEqual(self._play("guard", seen=True)[0], "ok")

    def test_goto_zero_means_skip_to_the_end_of_the_cycle(self):
        _status, to = self._play("skip_if_seen", seen=True, goto=0)
        self.assertGreater(to, 10 ** 6, "goto 0 ต้องแปลว่า 'ข้ามไปจบรอบ'")

    def test_the_editor_is_told_which_step_was_skipped(self):
        marks = []
        fr = runner_for(FakeBot(["stop_label"], seen=["stop_label"]))
        fr.on_step = lambda path, status: marks.append((path, status))
        with self.assertRaises(F._Goto):
            fr._play("2", gate(goto=1))
        self.assertEqual(marks, [("2", "skip")])

    def test_a_timeout_gives_the_image_a_chance_to_show_up_first(self):
        bot = FakeBot(["stop_label"])
        fr = runner_for(bot)
        self.assertEqual(fr._play("0", gate(goto=4, timeout=F.POLL_SLICE * 2 + 0.1)),
                         "ok")
        self.assertGreater(bot.captures, 1, "ตั้ง timeout ไว้แต่ดูจอครั้งเดียว")

class StreakTest(unittest.TestCase):

    def _gate_seen(self, fr, step, seen: bool, path="0"):
        fr.bot.seen = {"stop_label"} if seen else set()
        try:
            return fr._play(path, step)
        except F._Goto as g:
            return g.to

    def test_it_takes_three_sightings_in_a_row_to_jump(self):
        fr = runner_for(FakeBot(["stop_label"]))
        step = gate(goto=4)
        step.streak = 3
        self.assertEqual(self._gate_seen(fr, step, True), "ok", "ครั้งที่ 1 ก็กระโดดแล้ว")
        self.assertEqual(self._gate_seen(fr, step, True), "ok", "ครั้งที่ 2 ก็กระโดดแล้ว")
        self.assertEqual(self._gate_seen(fr, step, True), 3, "ครบสามครั้งแล้วยังไม่กระโดด")

    def test_one_miss_puts_the_count_back_to_zero(self):
        fr = runner_for(FakeBot(["stop_label"]))
        step = gate(goto=4)
        step.streak = 2
        self.assertEqual(self._gate_seen(fr, step, True), "ok")
        self.assertEqual(self._gate_seen(fr, step, False), "ok", "ไม่เจอแล้วยังกระโดด")
        self.assertEqual(self._gate_seen(fr, step, True), "ok",
                         "หลุดไปหนึ่งครั้งแล้วตัวนับไม่ได้เริ่มใหม่")
        self.assertEqual(self._gate_seen(fr, step, True), 3)

    def test_each_gate_counts_on_its_own(self):
        fr = runner_for(FakeBot(["stop_label"]))
        a, b = gate(goto=4), gate(goto=9)
        a.streak = b.streak = 2
        self.assertEqual(self._gate_seen(fr, a, True, path="0"), "ok")
        self.assertEqual(self._gate_seen(fr, b, True, path="1"), "ok",
                         "ด่านอีกใบเอาครั้งของเพื่อนไปนับด้วย")
        self.assertEqual(self._gate_seen(fr, a, True, path="0"), 3)

    def test_the_default_is_the_old_behaviour(self):
        self.assertEqual(F.Step().streak, 1)
        fr = runner_for(FakeBot(["stop_label"]))
        self.assertEqual(self._gate_seen(fr, gate(goto=4), True), 3)

    def test_a_zero_or_missing_value_is_treated_as_one(self):
        step = F.steps_from([{"action": "skip_if_seen", "target": "stop_label",
                              "goto": 4, "streak": 0}])[0]
        fr = runner_for(FakeBot(["stop_label"]))
        self.assertEqual(self._gate_seen(fr, step, True), 3)

    def test_guard_counts_the_other_way_round(self):
        fr = runner_for(FakeBot(["stop_label"]))
        step = gate(action="guard", goto=4)
        step.streak = 2
        self.assertEqual(self._gate_seen(fr, step, False), "ok")
        self.assertEqual(self._gate_seen(fr, step, False), 3)

    def test_it_survives_a_save_and_reload(self):
        tmp = Path(tempfile.mkdtemp(prefix="crstreak_"))
        old = F.FLOWS_DIR
        F.FLOWS_DIR = tmp
        try:
            step = gate(goto=3)
            step.streak = 4
            F.save_flow(F.Flow(name="gates", steps=[step]))
            self.assertEqual(F.load_flow("gates").steps[0].streak, 4,
                             "ค่าที่ตั้งไว้หายหลังเซฟ = ตั้งในเอดิเตอร์แล้วไม่มีผล")
        finally:
            F.FLOWS_DIR = old
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_new_pass_starts_counting_from_scratch(self):
        bot = FakeBot(["stop_label"], seen=["stop_label"])
        step = gate(goto=0)
        step.streak = 2
        fr = runner_for(bot, steps=[step])
        fr.run()
        self.assertEqual(fr._streaks.get("0", 0), 1)
        fr.run()
        self.assertEqual(fr._streaks.get("0", 0), 1,
                         "รอบใหม่ไม่ได้เริ่มนับใหม่ = ครั้งแรกของรอบสองกลายเป็นครั้งที่สอง")

class FailOpenTest(unittest.TestCase):

    def _run(self, action, target):
        bot = FakeBot(["other_label"], seen=["other_label"])
        fr = runner_for(bot)
        return fr._play("0", gate(action=action, target=target, goto=4))

    def test_an_uncalibrated_image_never_jumps(self):
        for act in ("guard", "skip_if_seen"):
            for target in ("typo_label", ""):
                with self.subTest(action=act, target=target):
                    self.assertEqual(self._run(act, target), "skip",
                                     "รูปที่ยังไม่รู้จักทำให้กระโดด")

    def test_it_does_not_even_look_at_the_screen(self):
        bot = FakeBot(["other_label"])
        runner_for(bot)._play("0", gate(target="typo_label", goto=4))
        self.assertEqual(bot.captures, 0, "เสียค่าจับภาพให้รูปที่ยังไม่รู้จัก")

class BreakingOutOfABodyTest(unittest.TestCase):

    def setUp(self):
        self._settle = F.TAP_SETTLE
        F.TAP_SETTLE = 0.0
        self.addCleanup(setattr, F, "TAP_SETTLE", self._settle)

    def _flow(self, parent, action, goto):
        body = [F.Step(action=action, target="stop_label", timeout=0, goto=goto),
                F.Step(action="tap", target="inner_button", timeout=0.2, after=0)]
        if parent == "repeat_until":
            head = F.Step(action="repeat_until", target="", until="never_label",
                          max_tries=3, after=0, steps=body)
        else:
            head = F.Step(action="if_seen", target="open_label", timeout=0,
                          after=0, steps=body)
        return [F.Step(action="tap", target="first_button", timeout=0.2, after=0),
                head,
                F.Step(action="tap", target="skipped_button", timeout=0.2, after=0),
                F.Step(action="tap", target="last_button", timeout=0.2, after=0)]

    def _run(self, parent, action, seen, goto=4):
        known = ["first_button", "inner_button", "skipped_button", "last_button",
                 "stop_label", "never_label", "open_label"]
        on_screen = set(known) - {"never_label"}
        if not seen:
            on_screen.discard("stop_label")
        bot = FakeBot(known, seen=on_screen)
        fr = runner_for(bot, self._flow(parent, action, goto))
        self.assertTrue(fr._play_list(fr.steps, ""), "รอบไม่จบดี")
        return bot.tapped

    def test_it_leaves_a_repeat_until_loop_mid_round(self):
        tapped = self._run("repeat_until", "skip_if_seen", seen=True)
        self.assertNotIn("inner_button", tapped, "ไม่ได้ออกจาก body ทันทีที่ตัดสินใจ")
        self.assertNotIn("skipped_button", tapped, "กระโดดแล้วยังเล่นขั้นที่ควรข้าม")
        self.assertEqual(tapped, ["first_button", "last_button"])

    def test_it_leaves_an_if_seen_block_mid_round(self):
        tapped = self._run("if_seen", "skip_if_seen", seen=True)
        self.assertEqual(tapped, ["first_button", "last_button"])

    def test_guard_still_breaks_out_the_same_way(self):
        for parent in ("repeat_until", "if_seen"):
            with self.subTest(parent=parent):
                self.assertEqual(self._run(parent, "guard", seen=False),
                                 ["first_button", "last_button"])

    def test_not_triggering_it_lets_the_body_finish(self):
        tapped = self._run("if_seen", "skip_if_seen", seen=False)
        self.assertIn("inner_button", tapped, "ไม่เข้าเงื่อนไขแต่ body ไม่ได้เล่น")
        self.assertIn("skipped_button", tapped)

    def test_a_top_level_gate_jumps_the_same_way(self):
        known = ["first_button", "skipped_button", "last_button", "stop_label"]
        bot = FakeBot(known, seen=set(known))
        steps = [F.Step(action="tap", target="first_button", timeout=0.2, after=0),
                 gate(goto=4),
                 F.Step(action="tap", target="skipped_button", timeout=0.2, after=0),
                 F.Step(action="tap", target="last_button", timeout=0.2, after=0)]
        fr = runner_for(bot, steps)
        self.assertTrue(fr._play_list(fr.steps, ""))
        self.assertEqual(bot.tapped, ["first_button", "last_button"])

class LogTest(unittest.TestCase):

    def setUp(self):
        self._detail = F.DETAIL
        self.addCleanup(setattr, F, "DETAIL", self._detail)

    def _lines(self, detail, seen=True):
        F.DETAIL = detail
        out = []
        bot = FakeBot(["stop_label"], seen=["stop_label"] if seen else [])
        fr = runner_for(bot, log=out.append)
        try:
            fr._play("5.3", gate(goto=4))
        except F._Goto:
            pass
        return out

    def test_the_customer_build_says_nothing_at_all(self):
        self.assertEqual(self._lines(detail=False), [])
        self.assertEqual(self._lines(detail=False, seen=False), [])

    def test_the_dev_build_says_where_it_jumped_to(self):
        blob = "\n".join(self._lines(detail=True))
        self.assertIn("[6.4]", blob, "เลขขั้นไม่ตรงกับการ์ดในเอดิเตอร์")
        self.assertIn("ขั้น 4", blob, "ไม่ได้บอกว่ากระโดดไปขั้นไหน")

    def test_no_em_dash_in_the_flow_module(self):
        self.assertNotIn(EM_DASH, (APP / "bot" / "flow.py").read_text(encoding="utf-8"),
                         "bot/flow.py มี em-dash")

class EndlessLoopTest(unittest.TestCase):

    class _NeverBot:

        def __init__(self):
            self.buttons = {n: {"pos": None, "template": f"{n}.png", "rect": None}
                            for n in ("go_button", "done_label")}
            self.taps = 0

        def capture(self):
            pass

        def is_visible(self, name, threshold=None):
            return False

        def tap(self, name, threshold=None, jitter=4, dry=False):
            self.taps += 1
            return True

    def _loop(self, bot, stop, max_tries=0):
        fr = F.FlowRunner(bot, [F.Step(action="repeat_until", target="go_button",
                                       until="done_label", max_tries=max_tries,
                                       after=0)],
                          log=lambda *_a: None, should_stop=stop, allow_spam=False)
        fr._in_game = False
        return fr

    def test_stopping_gets_out_of_a_loop_that_would_never_end(self):
        bot = self._NeverBot()
        fr = self._loop(bot, lambda: bot.taps >= 3)
        self.assertEqual(fr._play("0", fr.steps[0]), "fail",
                         "ลูปไม่จำกัดจบด้วยสถานะอื่นตอนถูกสั่งหยุด")
        self.assertLessEqual(bot.taps, 4, "ยังแตะจอต่อหลังถูกสั่งหยุด")

    def test_the_stop_is_checked_before_the_screen_is_ever_touched(self):
        bot = self._NeverBot()
        fr = self._loop(bot, lambda: True)
        self.assertEqual(fr._play("0", fr.steps[0]), "fail")
        self.assertEqual(bot.taps, 0, "สั่งหยุดไว้แล้วแต่ยังแตะจอ")

    def test_a_ceiling_still_ends_the_loop_by_itself(self):
        bot = self._NeverBot()
        fr = self._loop(bot, lambda: False, max_tries=3)
        self.assertEqual(fr._play("0", fr.steps[0]), "skip")
        self.assertEqual(bot.taps, 3, "จำนวนรอบไม่ตรงกับเพดานที่ตั้งไว้")

class FlowEditorApiTest(unittest.TestCase):

    def test_the_editor_can_draw_the_form_for_it(self):
        from editor import floweditor
        meta = floweditor.Api().get_meta()
        self.assertIn("skip_if_seen", meta["actions"], "ดรอปดาวน์ไม่มีหมวดใหม่ให้เลือก")
        got = meta["actions"]["skip_if_seen"]
        self.assertEqual(got["label"], F.ACTIONS["skip_if_seen"][0])
        self.assertIn("goto", got["fields"], "ฟอร์มไม่มีช่องเลขขั้นปลายทาง")
        self.assertEqual(got["fields"], meta["actions"]["guard"]["fields"])

if __name__ == "__main__":
    unittest.main()
