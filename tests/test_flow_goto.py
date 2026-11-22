"""Tests for flow jumps and gate steps."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import flow as F

FIXTURES = Path(__file__).resolve().parent / "fixtures"
_ORIGINAL_FLOWS_DIR = F.FLOWS_DIR

def setUpModule():
    F.FLOWS_DIR = FIXTURES

def tearDownModule():
    F.FLOWS_DIR = _ORIGINAL_FLOWS_DIR

def flow_files():
    return sorted(p for p in FIXTURES.glob("*.json")
                  if not p.name.endswith((".bak.json", ".json.tmp")))

def raw_step_count(raw_steps) -> int:
    total = 0
    for s in (raw_steps or []):
        if isinstance(s, dict):
            total += 1 + raw_step_count(s.get("steps"))
    return total

def parsed_step_count(steps) -> int:
    return sum(1 + parsed_step_count(s.steps) for s in (steps or []))

def guards_of(flow):
    out = []
    for i, step in enumerate(flow.steps):
        if step.action in F.GOTO_ACTIONS:
            out.append((f"{i + 1}", i, step))
        for k, child in enumerate(step.steps or []):
            if child.action in F.GOTO_ACTIONS:
                out.append((f"{i + 1}.{k + 1}", i, child))
    return out

def gate_key(step) -> str:
    return f"{step.action} {step.target}"

LONG_WAIT = 60.0

GOTO_LANDS_ON = {
    "gates": {
        "guard home_button": "goto_step",
        "skip_if_seen skip_label": "tap done_button",
        "goto_step ": "tap done_button",
    },
}

def landing_of(flow, step) -> str:
    if step.goto < 1:
        return ""
    dest = step.goto - 1
    if not 0 <= dest < len(flow.steps):
        return ""
    s = flow.steps[dest]
    return f"{s.action} {s.target or s.until}".strip()

class FlowFileTest(unittest.TestCase):
    def test_there_are_flows_to_check(self):
        self.assertTrue(flow_files(), "ไม่มีไฟล์แผนเลย เทสนี้พิสูจน์อะไรไม่ได้")

    def test_no_step_is_dropped_while_loading(self):
        for path in flow_files():
            with self.subTest(flow=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                flow = F.from_dict(data, fallback_name=path.stem)
                known = {s.get("action") for s in _walk_raw(data.get("steps"))}
                self.assertEqual(known - set(F.ACTIONS), set(),
                                 "มีชนิดขั้นตอนที่ระบบไม่รู้จัก จะถูกทิ้งตอนโหลด")
                self.assertEqual(parsed_step_count(flow.steps),
                                 raw_step_count(data.get("steps")),
                                 "จำนวนขั้นที่โหลดได้ไม่เท่ากับในไฟล์")

    def test_flow_name_matches_the_file_name(self):
        for path in flow_files():
            with self.subTest(flow=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data.get("name"), path.stem)

    def test_every_guard_has_something_to_look_for(self):
        for path in flow_files():
            flow = F.load_flow(path.stem)
            for label, _parent, step in guards_of(flow):
                if step.action in F.ALWAYS_JUMP_ACTIONS:
                    continue
                with self.subTest(flow=path.name, step=label):
                    self.assertTrue(step.target.strip(), "ด่านตรวจไม่ได้ระบุรูป")

    def test_every_kind_of_gate_is_covered_here(self):
        from_table = {a for a, (_label, fields) in F.ACTIONS.items() if "goto" in fields}
        self.assertEqual(set(F.GOTO_ACTIONS), from_table,
                         "GOTO_ACTIONS ไม่ตรงกับช่อง goto ในตาราง ACTIONS")
        self.assertLessEqual({"guard", "skip_if_seen"}, from_table,
                             "ด่านตรวจที่มีอยู่หายไปจากตาราง")

class GotoTest(unittest.TestCase):

    def test_goto_points_at_a_real_top_level_step(self):
        for path in flow_files():
            flow = F.load_flow(path.stem)
            top = len(flow.steps)
            for label, _parent, step in guards_of(flow):
                with self.subTest(flow=path.name, step=label):
                    self.assertIsInstance(step.goto, int)
                    self.assertGreaterEqual(step.goto, 0, "goto ติดลบ")
                    self.assertLessEqual(step.goto, top,
                                         f"goto ชี้เลยขั้นสุดท้าย ({top} ขั้น)")

    def test_a_guard_never_jumps_to_itself(self):
        for path in flow_files():
            flow = F.load_flow(path.stem)
            for label, parent, step in guards_of(flow):
                if not step.goto:
                    continue
                with self.subTest(flow=path.name, step=label):
                    self.assertNotEqual(step.goto - 1, parent,
                                        "ด่านตรวจกระโดดกลับมาที่ขั้นของตัวเอง")

    def test_goto_never_lands_inside_the_jump_block(self):
        for path in flow_files():
            flow = F.load_flow(path.stem)
            if not flow.jump.is_set():
                continue
            for label, _parent, step in guards_of(flow):
                if not step.goto:
                    continue
                with self.subTest(flow=path.name, step=label):
                    self.assertFalse(flow.jump.covers(step.goto - 1),
                                     "goto ชี้เข้ากลางช่วงกระโดดรัว")

    def test_every_guard_still_lands_where_it_was_meant_to(self):
        for path in flow_files():
            flow = F.load_flow(path.stem)
            got = {}
            for label, _parent, step in guards_of(flow):
                with self.subTest(flow=path.name, step=label):
                    same = got.setdefault(gate_key(step), landing_of(flow, step))
                    self.assertEqual(landing_of(flow, step), same,
                                     "ด่านตรวจชนิดเดียวกันที่มองหารูปเดียวกันไปลงคนละขั้น"
                                     " · ถ้าตั้งใจ ต้องแยกรูปของด่านออกจากกันก่อน")
            want = GOTO_LANDS_ON.get(path.stem)
            with self.subTest(flow=path.name):
                self.assertIsNotNone(
                    want, f"แผนใหม่ยังไม่ได้ประกาศปลายทางของด่านตรวจ"
                          f" · เพิ่มลง GOTO_LANDS_ON: {path.stem!r}: {got!r}")
                self.assertEqual(got, want,
                                 "ด่านตรวจไปลงคนละขั้นกับที่ประกาศไว้"
                                 " (แทรก/สลับขั้นแล้วลืมไล่เลข goto?)"
                                 " ถ้าย้ายเองตั้งใจ ให้แก้ GOTO_LANDS_ON ตาม")

    def test_a_bailout_never_lands_on_a_long_wait(self):
        for path in flow_files():
            flow = F.load_flow(path.stem)
            for i, step in enumerate(flow.steps):
                if step.action != "guard" or not step.goto:
                    continue
                dest = flow.steps[step.goto - 1]
                with self.subTest(flow=path.name, step=i + 1,
                                  guard=step.target, lands_on=step.goto):
                    self.assertLess(
                        dest.timeout, LONG_WAIT,
                        f"ด่านตรวจขั้น {i + 1} ({step.target}) ไปลงขั้น {step.goto}"
                        f" ซึ่งรอ {dest.timeout:g} วิ · ด่านตรวจมีไว้เพื่อ **ออก** จาก"
                        f" ช่วงที่ไม่สำเร็จ ไปลงขั้นที่รอนานคือยืนรอเก้อทุกรอบที่พลาด")

    def test_every_top_level_step_is_reachable(self):
        for path in flow_files():
            flow = F.load_flow(path.stem)
            n = len(flow.steps)
            edges = {i: {i + 1} for i in range(n)}
            for label, parent, step in guards_of(flow):
                dest = step.goto - 1 if step.goto >= 1 else n
                if step.action in F.ALWAYS_JUMP_ACTIONS and "." not in label:
                    edges[parent] = {dest}
                else:
                    edges[parent].add(dest)
            seen, stack = {0}, [0]
            while stack:
                i = stack.pop()
                for nxt in edges.get(i, ()):
                    if 0 <= nxt < n and nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            with self.subTest(flow=path.name):
                self.assertEqual(sorted(set(range(n)) - seen), [],
                                 "มีขั้นที่ไม่มีเส้นทางไปถึง")

def _walk_raw(raw_steps):
    for s in (raw_steps or []):
        if not isinstance(s, dict):
            continue
        yield s
        yield from _walk_raw(s.get("steps"))

def loop_exits(flow, at: int) -> list:
    n = len(flow.steps)
    step = flow.steps[at]
    dest = step.goto - 1 if step.goto >= 1 else n
    if dest > at:
        return []
    out = []
    for k in range(dest, at + 1):
        here = flow.steps[k]
        for s in [here, *(here.steps or [])]:
            if s.action not in F.GOTO_ACTIONS or s.action in F.ALWAYS_JUMP_ACTIONS:
                continue
            to = s.goto - 1 if s.goto >= 1 else n
            if not dest <= to <= at:
                out.append(k + 1)
    return out

class UnconditionalJumpTest(unittest.TestCase):

    def test_it_is_a_jump_but_not_a_gate(self):
        self.assertIn("goto_step", F.GOTO_ACTIONS, "ไม่ถูกนับเป็นขั้นที่กระโดด")
        self.assertIn("goto_step", F.ALWAYS_JUMP_ACTIONS)
        self.assertNotIn("target", F.ACTIONS["goto_step"][1],
                         "มีช่องรูป = กลายเป็นด่านตรวจที่ตรวจอะไรไม่ได้")

    def test_it_counts_as_going_somewhere_not_as_working(self):
        self.assertIn("goto_step", F.MOVE_ACTIONS)

    def test_it_jumps_without_ever_looking_at_the_screen(self):
        fr = F.FlowRunner.__new__(F.FlowRunner)
        looked = []
        fr.bot = type("B", (), {"capture": lambda self: looked.append(1)})()
        fr._tech = lambda _m: None
        fr.on_step = lambda *_a: None
        with self.assertRaises(F._Goto) as caught:
            fr._play("6", F.Step(action="goto_step", goto=3))
        self.assertEqual(caught.exception.to, 2, "ควรไปขั้นที่ 3 (index 2)")
        self.assertEqual(looked, [], "จับภาพจอทั้งที่ขั้นนี้ไม่ต้องดูจอ")

    def test_zero_means_end_of_the_round(self):
        to, dest = F.goto_target(F.Step(action="goto_step", goto=0))
        self.assertGreater(to, 10 ** 6, "goto 0 ต้องแปลว่าข้ามไปจบรอบ")
        self.assertEqual(dest, "จบรอบ")

    def test_the_loop_checker_can_tell_a_dead_loop_from_a_live_one(self):
        dead = F.Flow(steps=F.steps_from([
            {"action": "tap", "target": "a"},
            {"action": "tap", "target": "b"},
            {"action": "goto_step", "goto": 1},
        ]))
        self.assertEqual(loop_exits(dead, 2), [], "ลูปที่ไม่มีทางออกกลับบอกว่ามีทางออก")

        live = F.Flow(steps=F.steps_from([
            {"action": "tap", "target": "a"},
            {"action": "skip_if_seen", "target": "done", "goto": 4},
            {"action": "goto_step", "goto": 1},
            {"action": "tap", "target": "z"},
        ]))
        self.assertEqual(loop_exits(live, 2), [2], "ด่านที่พาออกจากลูปถูกมองข้าม")

        forward = F.Flow(steps=F.steps_from([
            {"action": "goto_step", "goto": 3},
            {"action": "tap", "target": "a"},
            {"action": "tap", "target": "b"},
        ]))
        self.assertEqual(loop_exits(forward, 0), [], "ข้ามไปข้างหน้าไม่ใช่ลูป")

    def test_no_flow_file_loops_forever(self):
        for path in flow_files():
            flow = F.load_flow(path.stem)
            for i, step in enumerate(flow.steps):
                if step.action not in F.ALWAYS_JUMP_ACTIONS:
                    continue
                with self.subTest(flow=path.name, step=i + 1):
                    dest = step.goto - 1 if step.goto >= 1 else len(flow.steps)
                    if dest > i:
                        continue
                    self.assertTrue(
                        loop_exits(flow, i),
                        f"ขั้น {i + 1} ข้ามย้อนไปขั้น {step.goto} แบบไม่มีเงื่อนไข"
                        " และในช่วงที่วนไม่มีด่านตรวจที่พาออกได้เลย = วนไม่จบ")

if __name__ == "__main__":
    unittest.main()
