"""Tests that user logs hide implementation details."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import flow as F

LEAKS = ("_button", "_label", "_lable", "_hud", "_icon", "ขั้นตอนข้างใน", "ไม่เกิน")
TEMPLATE_LEAKS = ("_button", "_label", "_lable", "_hud", "_icon")

class _SeeingBot:

    def __init__(self, seen: str):
        self.buttons = {n: {"pos": None, "template": f"{n}.png", "rect": None}
                        for n in ("icon_a", "icon_b")}
        self.seen = seen

    def capture(self):
        pass

    def is_visible(self, name, threshold=None):
        return name == self.seen

def sample_flow():
    steps = F.steps_from([
        {"action": "tap", "target": "alpha_button", "group": "shop", "timeout": 3},
        {"action": "tap", "target": "beta_label", "group": "run", "timeout": 3},
        {"action": "tap", "target": "gamma_button", "group": "run", "timeout": 3},
        {"action": "tap", "target": "delta_label", "group": "done", "timeout": 3},
    ])
    flow = F.Flow(name="default", steps=steps,
                  group_defs=["shop", "run", "done"])
    flow.jump = F.Jump(enabled=True, start=0, end=2)
    return flow

class LogPrivacyTest(unittest.TestCase):
    def setUp(self):
        self._detail = F.DETAIL
        self.out = []
        self.fr = F.FlowRunner.__new__(F.FlowRunner)
        self.fr.log = self.out.append
        self.fr._phase_now = ""
        self.fr._stage_now = ""
        self.fr._in_game = False
        self.fr.jump = sample_flow().jump

    def tearDown(self):
        F.DETAIL = self._detail

    def _play_all(self, detail: bool):
        F.DETAIL = detail
        self.out.clear()
        self.fr._phase_now = ""
        self.fr._stage_now = ""
        self.fr._in_game = False
        for i, step in enumerate(sample_flow().steps):
            self.fr._phase(step, i)
            if self.fr._in_game_step(step, i):
                self.fr._in_game = True
            self.fr._tech(f"[1] {step.label()}")
        return self.out

    def test_customer_log_has_no_internal_names(self):
        lines = self._play_all(detail=False)
        blob = "\n".join(lines)
        for leak in LEAKS:
            self.assertNotIn(leak, blob, f"log ที่แจกหลุดร่องรอยภายใน: {leak!r}")

    def test_customer_log_still_says_something(self):
        lines = self._play_all(detail=False)
        self.assertGreaterEqual(len(lines), 3, "ลูกค้าไม่เห็นอะไรเลย เหมือนโปรแกรมค้าง")

    def test_dev_log_keeps_full_detail(self):
        lines = self._play_all(detail=True)
        blob = "\n".join(lines)
        self.assertTrue(any(k in blob for k in ("_button", "_label", "_lable")),
                        "โหมดเดฟไม่เหลือรายละเอียดให้ดีบัก")

    def test_every_line_has_a_stage_tag(self):
        for line in self._play_all(detail=False):
            self.assertRegex(line, r"^\[[^\]]+\] ", f"บรรทัดไม่มีหมวด: {line!r}")

    def test_all_three_stages_appear(self):
        blob = "\n".join(self._play_all(detail=False))
        for stage in (F.STAGE_SHOP, F.STAGE_INGAME, F.STAGE_AFTER):
            self.assertIn(f"[{stage}]", blob, f"ไม่เห็นช่วง {stage} เลยทั้งรอบ")

    def test_stages_come_in_order(self):
        seen = []
        for line in self._play_all(detail=False):
            tag = line.split("]", 1)[0][1:]
            if tag not in seen:
                seen.append(tag)
        self.assertEqual(seen, [F.STAGE_SHOP, F.STAGE_INGAME, F.STAGE_AFTER])

    def test_ingame_boundary_follows_the_jump_range(self):
        f = sample_flow()
        self.assertTrue(f.jump.is_set(), "แผนไม่ได้ตั้งช่วงกระโดด เทสนี้พิสูจน์อะไรไม่ได้")
        inside = [i for i in range(len(f.steps)) if f.jump.covers(i)]
        for i in inside:
            self.assertEqual(self.fr._stage(f.steps[i], i), F.STAGE_INGAME)

    def test_the_named_watch_step_never_spells_out_its_images(self):
        step = F.Step(action="watch_choice", note="Boost picker", poll=0.1, timeout=0.4,
                      until=F.join_until(["icon_a", "icon_b"]))
        for detail in (False, True):
            F.DETAIL = detail
            out = []
            fr = F.FlowRunner.__new__(F.FlowRunner)
            fr.bot = _SeeingBot("icon_b")
            fr.log = out.append
            fr.should_stop = lambda: False
            fr.wait_if_paused = lambda: None
            fr._in_game = False
            self.assertEqual(fr._play("5.3", step), "ok")
            blob = "\n".join(out)
            for leak in TEMPLATE_LEAKS:
                self.assertNotIn(leak, blob,
                                 f"ขั้นที่ตั้งชื่อเองยังหลุด {leak!r} (DETAIL={detail})")
            if detail:
                self.assertIn("B", blob, "โหมดเดฟไม่บอกว่าได้ตัวไหนมา")
            else:
                self.assertEqual(out, [], "บิลด์ที่แจกต้องเงียบเหมือนขั้นอื่น")

    def test_detail_is_off_in_frozen_build(self):
        import inspect

        from bot import config
        src = inspect.getsource(config)
        idx = src.index("LOG_DETAIL")
        line = src[idx:src.index("\n", idx)]
        self.assertIn("frozen", line)
        self.assertNotIn("environ", line, "อย่าให้เปิด log ละเอียดผ่าน env")

if __name__ == "__main__":
    unittest.main()
