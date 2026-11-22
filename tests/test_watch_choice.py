"""Tests for watch and choice steps."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import flow as F

LEAKS = ("_button", "_label", "_lable", "_hud", "_icon")

EM_DASH = "\u2014"

BOOST_GROUP = "Boost choices"
BOOSTS = ["icon_a", "icon_b", "icon_c", "icon_d"]
TITLE = "Boost picker"

class FakeBot:

    def __init__(self, known, seen=()):
        self.buttons = {n: {"pos": None, "template": f"{n}.png", "rect": None}
                        for n in known}
        self.seen = set(seen)
        self.captures = 0
        self.looked = []

    def capture(self):
        self.captures += 1

    def is_visible(self, name, threshold=None):
        self.looked.append(name)
        return name in self.seen

    def tap(self, name, threshold=None, jitter=4, dry=False):
        return name in self.seen

def runner_with(bot, log=None):
    fr = F.FlowRunner.__new__(F.FlowRunner)
    fr.bot = bot
    fr.log = log or (lambda *_a: None)
    fr.should_stop = lambda: False
    fr.wait_if_paused = lambda: None
    fr._in_game = False
    fr._cap_tick = 0
    return fr

def step_of(action, **kw):
    kw.setdefault("until", F.join_until(BOOSTS))
    kw.setdefault("poll", 0.1)
    kw.setdefault("timeout", 0.4)
    return F.Step(action=action, **kw)

def choice_flow(group=BOOST_GROUP, note=TITLE, until=None, enabled=True):
    f = F.Flow(name="boosts", group_defs=[g for g in [group] if g])
    inner = F.Step(action="watch_choice", target="",
                   until=F.join_until(BOOSTS if until is None else until),
                   poll=0.5, timeout=30, note=note, group=group, enabled=enabled)
    f.steps = [
        F.Step(action="if_seen", target="random_button", group=group,
               steps=[F.Step(action="tap", target="random_button", group=group),
                      F.Step(action="tap", target="Multi_buy_1_button", group=group),
                      F.Step(action="tap", target="Multi_buy_2_button", group=group),
                      inner]),
    ]
    return f

class ActionTableTest(unittest.TestCase):

    def test_the_action_is_in_the_table_with_a_thai_label(self):
        self.assertIn("watch_choice", F.ACTIONS)
        label, _fields = F.ACTIONS["watch_choice"]
        self.assertTrue(label.strip(), "ไม่มีป้ายภาษาไทยให้เลือกในดรอปดาวน์")
        self.assertNotIn(EM_DASH, label, "ห้าม em-dash ในข้อความที่ผู้ใช้เห็น")

    def test_it_asks_for_exactly_the_same_fields_as_watch_until(self):
        self.assertEqual(F.ACTIONS["watch_choice"][1], F.ACTIONS["watch_until"][1])

    def test_it_holds_no_body(self):
        self.assertNotIn("watch_choice", F.NESTED_ACTIONS)

    def test_the_editor_is_told_what_the_note_box_means_here(self):
        self.assertIn("watch_choice", F.NOTE_LABELS)
        self.assertIn("ชื่อ", F.NOTE_LABELS["watch_choice"])

    def test_a_step_of_this_kind_is_not_dropped_while_loading(self):
        steps = F.steps_from([{"action": "watch_choice", "until": ["a", "b"],
                               "note": TITLE, "poll": 0.4, "timeout": 12}])
        self.assertEqual(len(steps), 1, "ขั้นชนิดใหม่ถูกทิ้งตอนโหลด")
        self.assertEqual(steps[0].until_list(), ["a", "b"])
        self.assertEqual(steps[0].note, TITLE)

    def test_saving_and_reloading_keeps_the_name(self):
        tmp = Path(tempfile.mkdtemp(prefix="crwatch_"))
        old = F.FLOWS_DIR
        F.FLOWS_DIR = tmp
        try:
            F.save_flow(choice_flow())
            again = F.load_flow("boosts")
            inner = again.steps[0].steps[-1]
            self.assertEqual(inner.action, "watch_choice")
            self.assertEqual(inner.note, TITLE, "ชื่อที่ตั้งหายหลังเซฟ")
            self.assertEqual(inner.until_list(), BOOSTS)
        finally:
            F.FLOWS_DIR = old
            shutil.rmtree(tmp, ignore_errors=True)

class SameRunAsWatchUntilTest(unittest.TestCase):

    KINDS = ("watch_until", "watch_choice")

    def test_it_stops_on_any_one_of_the_candidates(self):
        for act in self.KINDS:
            with self.subTest(action=act):
                bot = FakeBot(BOOSTS, seen=["icon_b"])
                self.assertEqual(runner_with(bot)._play("0", step_of(act)), "ok")

    def test_a_single_candidate_still_works(self):
        for act in self.KINDS:
            with self.subTest(action=act):
                bot = FakeBot(BOOSTS, seen=["icon_a"])
                self.assertEqual(
                    runner_with(bot)._play("0", step_of(act, until="icon_a")),
                    "ok")

    def test_timing_out_skips_or_fails_exactly_like_before(self):
        for act in self.KINDS:
            with self.subTest(action=act):
                bot = FakeBot(BOOSTS)
                self.assertEqual(runner_with(bot)._play("0", step_of(act)), "skip")
                self.assertGreaterEqual(bot.captures, 1, "ไม่ได้ดูจอเลย")
                self.assertEqual(
                    runner_with(FakeBot(BOOSTS))._play("0", step_of(act, optional=False)),
                    "fail")

    def test_uncalibrated_candidates_are_skipped_not_fatal(self):
        for act in self.KINDS:
            with self.subTest(action=act):
                bot = FakeBot(["icon_b"], seen=["icon_b"])
                self.assertEqual(runner_with(bot)._play("0", step_of(act)), "ok")
                self.assertNotIn("icon_a", bot.looked,
                                 "ไปหารูปที่ยังไม่ได้คาลิเบรต = เสียเวลาค้นหาเปล่าทุกรอบ")

    def test_no_calibrated_candidate_at_all_is_the_old_skip(self):
        for act in self.KINDS:
            with self.subTest(action=act):
                bot = FakeBot(["random_button"])
                self.assertEqual(runner_with(bot)._play("0", step_of(act)), "skip")

    def test_one_screenshot_covers_every_candidate(self):
        for act in self.KINDS:
            with self.subTest(action=act):
                bot = FakeBot(BOOSTS)
                runner_with(bot)._play("0", step_of(act))
                self.assertGreaterEqual(len(bot.looked), len(BOOSTS) * bot.captures)

    def test_the_first_name_in_the_list_still_wins(self):
        bot = FakeBot(BOOSTS, seen=BOOSTS)
        out = []
        old = F.DETAIL
        F.DETAIL = True
        try:
            runner_with(bot, log=out.append)._play("0", step_of("watch_choice",
                                                               note=TITLE))
        finally:
            F.DETAIL = old
        self.assertIn(F.display_name(BOOSTS[0]), "\n".join(out))

    def test_pace_stretches_the_timeout_but_not_the_poll(self):
        f = F.Flow(steps=[step_of("watch_choice", timeout=10, poll=0.5)])
        F.scale_pace(f, 2.0)
        self.assertAlmostEqual(f.steps[0].timeout, 20)
        self.assertAlmostEqual(f.steps[0].poll, 0.5)

    def test_both_kinds_go_through_one_implementation(self):
        called = []
        fr = runner_with(FakeBot(BOOSTS))
        fr._watch_until = lambda path, step, tag: called.append(step.action) or "ok"
        for act in self.KINDS:
            fr._play("0", step_of(act))
        self.assertEqual(called, list(self.KINDS))

class LogTest(unittest.TestCase):

    def setUp(self):
        self._detail = F.DETAIL

    def tearDown(self):
        F.DETAIL = self._detail

    def _lines(self, detail, seen=("icon_b",), **kw):
        F.DETAIL = detail
        out = []
        bot = FakeBot(BOOSTS, seen=seen)
        runner_with(bot, log=out.append)._play("5.3", step_of("watch_choice", **kw))
        return out

    def test_the_name_you_set_replaces_the_template_names(self):
        blob = "\n".join(self._lines(detail=True, note=TITLE))
        self.assertIn(TITLE, blob, "log ไม่ได้ใช้ชื่อที่ตั้งไว้")
        self.assertIn("B", blob, "ไม่ได้บอกว่าได้ตัวไหนมา")
        for leak in LEAKS:
            self.assertNotIn(leak, blob, f"log ยังหลุดชื่อ template: {leak}")

    def test_the_step_number_still_reads_the_way_the_editor_shows_it(self):
        self.assertIn("[6.4]", "\n".join(self._lines(detail=True, note=TITLE)))

    def test_the_customer_build_says_nothing_at_all(self):
        self.assertEqual(self._lines(detail=False, note=TITLE), [])

    def test_without_a_name_it_still_leaks_nothing(self):
        lines = self._lines(detail=True, note="")
        blob = "\n".join(lines)
        self.assertTrue(lines, "ไม่ตั้งชื่อแล้วเงียบสนิท เดฟดีบักไม่ได้")
        for leak in LEAKS:
            self.assertNotIn(leak, blob, f"ชื่อสำรองหลุดชื่อ template: {leak}")
        self.assertIn("4 อย่าง", blob, "ชื่อสำรองไม่ได้บอกด้วยซ้ำว่ากำลังรออะไรอยู่กี่อย่าง")

    def test_a_name_that_is_really_a_template_name_is_not_used(self):
        blob = "\n".join(self._lines(detail=True, note="รอ icon_a โผล่"))
        for leak in LEAKS:
            self.assertNotIn(leak, blob)

    def test_giving_up_names_no_image_either(self):
        blob = "\n".join(self._lines(detail=True, seen=(), note=TITLE))
        for leak in LEAKS:
            self.assertNotIn(leak, blob, f"บรรทัดหมดเวลาหลุดชื่อ template: {leak}")

    def test_nothing_calibrated_is_reported_without_naming_images(self):
        F.DETAIL = True
        out = []
        bot = FakeBot(["random_button"])
        runner_with(bot, log=out.append)._play("5.3", step_of("watch_choice", note=TITLE))
        for leak in LEAKS:
            self.assertNotIn(leak, "\n".join(out))

    def test_the_old_action_is_left_exactly_as_it_was(self):
        F.DETAIL = True
        out = []
        bot = FakeBot(BOOSTS, seen=["icon_b"])
        runner_with(bot, log=out.append)._play("0", step_of("watch_until"))
        self.assertIn("icon_b", "\n".join(out))

    def test_the_card_title_is_the_name_not_the_image_list(self):
        s = step_of("watch_choice", note=TITLE)
        self.assertEqual(s.label(), TITLE)
        for leak in LEAKS:
            self.assertNotIn(leak, F.Step(action="watch_choice",
                                          until=F.join_until(BOOSTS)).label())

class ChoicePickerTest(unittest.TestCase):

    def test_the_new_action_shows_up_as_a_choice(self):
        got = F.choices(choice_flow())
        self.assertEqual([c["group"] for c in got], [BOOST_GROUP])
        self.assertEqual([o["name"] for o in got[0]["options"]],
                         [F.display_name(n) for n in BOOSTS])

    def test_a_single_candidate_is_not_a_choice(self):
        self.assertEqual(F.choices(choice_flow(until=["icon_a"])), [],
                         "ใบเดียว = ไม่มีอะไรให้เลือก ไม่ต้องโผล่ในหน้าผู้ใช้")

    def test_ticking_filters_what_the_bot_watches_for(self):
        f = choice_flow()
        self.assertEqual(f.set_choice(BOOST_GROUP, ["B", "D"]), 1)
        self.assertEqual(f.steps[0].steps[-1].until_list(),
                         ["icon_b", "icon_d"])

    def test_the_per_screen_override_road_works_end_to_end(self):
        f = choice_flow()
        F.apply_override(f, {"choices": {BOOST_GROUP: ["A"]}})
        self.assertEqual(f.steps[0].steps[-1].until_list(), ["icon_a"])

    def test_the_option_list_carries_no_template_name(self):
        blob = json.dumps(F.choices(choice_flow()), ensure_ascii=False)
        for leak in LEAKS:
            self.assertNotIn(leak, blob)

class GroupWarningTest(unittest.TestCase):

    def test_the_groupless_step_is_invisible_and_that_is_the_bug(self):
        f = choice_flow(group="")
        self.assertEqual(F.choices(f), [])
        self.assertEqual(len(F.unreachable_choices(f)), 1,
                         "ตั้งไว้หลายใบแต่ไม่มีกลุ่ม แล้วไม่มีอะไรเตือนเลย")

    def test_the_warning_points_at_the_step_the_editor_shows(self):
        f = choice_flow(group="")
        f.steps = [F.Step(action="tap", target="play_button") for _ in range(5)] + f.steps
        w = F.unreachable_choices(f)[0]
        self.assertEqual(w["path"], "5.3")
        self.assertEqual(w["no"], "6.4")
        self.assertEqual(w["action"], "watch_choice")
        self.assertEqual(w["count"], len(BOOSTS))

    def test_a_grouped_step_is_not_reported(self):
        self.assertEqual(F.unreachable_choices(choice_flow()), [])

    def test_a_group_name_of_only_spaces_does_not_count_as_a_group(self):
        self.assertEqual(len(F.unreachable_choices(choice_flow(group="   "))), 1)

    def test_one_candidate_is_not_worth_a_warning(self):
        self.assertEqual(
            F.unreachable_choices(choice_flow(group="", until=["icon_a"])), [])

    def test_a_field_the_action_ignores_is_not_counted(self):
        f = F.Flow(steps=[F.Step(action="if_seen", target="a_button",
                                 until="a_button, b_button")])
        self.assertEqual(F.unreachable_choices(f), [])

    def test_a_switched_off_step_is_still_reported(self):
        self.assertEqual(len(F.unreachable_choices(choice_flow(group="",
                                                               enabled=False))), 1)

    def test_watch_until_gets_the_same_warning(self):
        f = F.Flow(steps=[F.Step(action="watch_until", until=F.join_until(BOOSTS))])
        self.assertEqual(len(F.unreachable_choices(f)), 1)

    def test_the_warning_carries_no_template_name(self):
        blob = json.dumps(F.unreachable_choices(choice_flow(group="")),
                          ensure_ascii=False)
        for leak in LEAKS:
            self.assertNotIn(leak, blob)

    def test_the_shipped_plan_has_no_hidden_choice_left(self):
        self.assertEqual(F.unreachable_choices(F.load_flow("default")), [])

class FlowEditorApiTest(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="crwatch_"))
        self._flows = F.FLOWS_DIR
        F.FLOWS_DIR = self.tmp

    def tearDown(self):
        F.FLOWS_DIR = self._flows
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _api(self):
        from editor import floweditor
        return floweditor.Api()

    def test_the_meta_tells_the_editor_what_the_note_box_is_here(self):
        meta = self._api().get_meta()
        self.assertIn("watch_choice", meta["actions"], "ดรอปดาวน์ไม่มีหมวดใหม่ให้เลือก")
        self.assertEqual(meta["note_labels"].get("watch_choice"),
                         F.NOTE_LABELS["watch_choice"])

    def test_saving_a_plan_reports_what_the_user_will_never_see(self):
        api = self._api()
        r = api.save_flow(choice_flow(group="").to_dict())
        self.assertTrue(r["ok"])
        self.assertEqual([w["no"] for w in r["warnings"]], ["1.4"])
        clean = api.save_flow(choice_flow().to_dict())
        self.assertEqual(clean["warnings"], [])

    def test_the_editor_can_ask_before_saving(self):
        r = self._api().flow_warnings(choice_flow(group="").to_dict())
        self.assertEqual(len(r["unreachable"]), 1)

if __name__ == "__main__":
    unittest.main()
