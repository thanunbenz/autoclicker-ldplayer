"""Flow data model and runner."""
import json
import os
import random
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, field

from .config import CONFIG_DIR, DEFAULT_BASE_RESOLUTION, LOG_DETAIL

FLOWS_DIR = CONFIG_DIR / "flows"

ACTIONS = {
    "tap":          ("แตะรูป",
                     ["target", "timeout", "after", "optional"]),
    "wait_for":     ("รอจนรูปโผล่",
                     ["target", "timeout", "optional"]),
    "wait_gone":    ("รอจนรูปหาย",
                     ["target", "timeout", "optional"]),
    "sleep":        ("หน่วงเวลา", ["seconds"]),
    "tap_xy":       ("แตะพิกัด", ["x", "y", "after"]),
    "swipe":        ("ปัดจอ (เลื่อนรายการ)",
                     ["target", "x", "y", "dx", "dy", "swipe_ms", "after", "optional"]),
    "type_text":    ("พิมพ์ข้อความ (ช่องค้นหาในเกม)",
                     ["target", "timeout", "text", "submit", "after", "optional"]),
    "repeat_until": ("ทำซ้ำจนเจอรูป", ["target", "until", "after", "max_tries", "optional"]),
    "watch_until":  ("เฝ้าจอจนเจอรูป",
                     ["until", "poll", "timeout", "optional"]),
    "watch_choice": ("เฝ้าจนกว่าจะเจอรายการที่เลือก",
                     ["until", "poll", "timeout", "optional"]),
    "if_seen":      ("ถ้าเจอรูปนี้", ["target", "timeout", "after"]),
    "guard":        ("ด่านตรวจ (ไม่เจอ=กระโดดไปขั้นอื่น)",
                     ["target", "timeout", "goto", "streak"]),
    "skip_if_seen": ("ถ้าเจอรูปนี้ให้ข้าม (เจอ=กระโดดไปขั้นอื่น)",
                     ["target", "timeout", "goto", "streak"]),
    "goto_step":    ("ข้ามไปขั้นตอนอื่น (ไม่มีเงื่อนไข)", ["goto"]),
}

NESTED_ACTIONS = ("repeat_until", "if_seen")

GOTO_ACTIONS = tuple(a for a, (_label, fields) in ACTIONS.items() if "goto" in fields)

ALWAYS_JUMP_ACTIONS = tuple(a for a in GOTO_ACTIONS
                            if "target" not in ACTIONS[a][1])

MOVE_ACTIONS = ("swipe", "sleep", *GOTO_ACTIONS)

def _is_navigation(body: list) -> bool:
    return bool(body) and all(s.action in MOVE_ACTIONS for s in body)

NOTE_LABELS = {
    "watch_choice": "ตั้งชื่อรายการนี้ (log เรียกชื่อนี้แทนชื่อรูป)",
    "type_text": "ป้ายของช่องกรอกในหน้าโปรแกรม (ผู้ใช้จะเห็นคำนี้)",
}

DEFAULT_ASK_LABEL = "ข้อความที่จะให้บอทพิมพ์"

UNTIL_SEP = ","

_INTERNAL_WORDS = frozenset({"label", "lable", "button", "buton", "btn",
                             "hud", "icon", "img", "template"})

MAX_JUMPS_PER_PASS = 500

DETAIL = LOG_DETAIL
LONG_WAIT_SEC = 60

STAGE_SHOP = "ร้านค้า"
STAGE_INGAME = "ในเกม"
STAGE_AFTER = "เก็บของ"
STAGE_ERRAND = "แวะทำ"
STAGE_DEFAULT = {
    STAGE_SHOP: "เตรียมของ",
    STAGE_INGAME: "กำลังวิ่ง",
    STAGE_AFTER: "เก็บของรางวัล",
    STAGE_ERRAND: "กำลังทำงาน",
}

class _Goto(Exception):

    def __init__(self, to: int):
        self.to = to

WATCH_POLL = 0.5
MIN_POLL = 0.1
MIN_SPAM_INTERVAL = 0.05
POLL_SLICE = 0.35
TAP_RETRIES = 1
TAP_SETTLE = 0.4
WRITE_RETRIES = 6
READ_RETRIES = 3

JUMP_GROUP = "กระโดดรัว"
SLIDE_DROP = 180
JUMP_FALLBACK = (210, 760)
MAX_TAPS_CAP = 999

def until_names(raw) -> list[str]:
    items = raw if isinstance(raw, (list, tuple)) else str(raw or "").split(UNTIL_SEP)
    out, seen = [], set()
    for it in items:
        name = str(it or "").strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out

def join_until(names) -> str:
    return f"{UNTIL_SEP} ".join(until_names(names))

def uses_until(step: "Step") -> bool:
    return "until" in ACTIONS.get(step.action, ("", ()))[1]

def goto_target(step: "Step") -> tuple:
    if step.goto and step.goto >= 1:
        return step.goto - 1, f"ขั้น {step.goto}"
    return 10 ** 9, "จบรอบ"

def image_names(flow: "Flow") -> set[str]:
    out: set[str] = set()

    def walk(steps):
        for s in steps:
            if not s.enabled:
                continue
            fields = ACTIONS.get(s.action, ("", ()))[1]
            if "target" in fields and (s.target or "").strip():
                out.add(s.target.strip())
            if "until" in fields:
                out.update(s.until_list())
            walk(s.steps or [])

    walk(flow.steps)
    return out

def display_name(template: str) -> str:
    parts = [p for p in re.split(r"[\s_\-.]+", str(template or "").strip()) if p]
    words = [p for p in parts if p.lower() not in _INTERNAL_WORDS] or parts
    return " ".join(w[:1].upper() + w[1:] for w in words)

def _looks_internal(text: str) -> bool:
    return any(k in text for k in ("_button", "_label", "_lable", "_hud", "_icon"))

def _looks_like_a_file_name(text: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9]+_[A-Za-z0-9]+", text or ""))

def _name_key(name) -> str:
    return " ".join(str(name or "").split()).lower()

@dataclass
class Step:
    action: str = "tap"
    target: str = ""
    until: str = ""
    seconds: float = 1.0
    timeout: float = 8.0
    after: float = 1.0
    optional: bool = True
    x: int = 0
    y: int = 0
    dx: int = 0
    dy: int = 0
    swipe_ms: int = 300
    max_tries: int = 30
    poll: float = WATCH_POLL
    text: str = ""
    submit: bool = False
    note: str = ""
    group: str = ""
    enabled: bool = True
    goto: int = 0
    streak: int = 1
    steps: list = field(default_factory=list)

    def until_list(self) -> list[str]:
        return until_names(self.until)

    def watch_title(self) -> str:
        name = " ".join((self.note or "").split())
        if name and not _looks_internal(name):
            return name
        n = len(self.until_list())
        return "เฝ้าจนเจอรายการที่เลือก" + (f" ({n} อย่าง)" if n else "")

    def label(self) -> str:
        name, _fields = ACTIONS.get(self.action, (self.action, []))
        if self.action == "sleep":
            return f"{name} {self.seconds:g} วิ"
        if self.action == "tap_xy":
            return f"{name} ({self.x}, {self.y})"
        if self.action == "swipe":
            frm = self.target or f"({self.x}, {self.y})"
            return f"{name} {frm} -> ({self.dx:+g}, {self.dy:+g})"
        if self.action == "repeat_until":
            body = f"{len(self.steps)} ขั้นตอนข้างใน" if self.steps else self.target
            return f"{name} {self.until} ({body})"
        if self.action == "if_seen":
            how = "ตรวจครั้งเดียว" if self.timeout <= 0 else f"รอไม่เกิน {self.timeout:g} วิ"
            return f"{name} {self.target} ({how} · {len(self.steps)} ขั้นตอนข้างใน)"
        if self.action == "watch_until":
            return f"{name} {self.until} (ตรวจทุก {self.poll:g} วิ)"
        if self.action == "goto_step":
            return f"{name} -> {'ขั้น ' + str(self.goto) if self.goto >= 1 else 'จบรอบ'}"
        if self.action == "watch_choice":
            return self.watch_title()
        return f"{name} {self.target}"

def _hint(note: str, steps: int) -> str:
    text = (note or "").strip()
    return text if text and not _looks_internal(text) else f"{steps} ขั้นตอน"

@dataclass
class Jump:
    enabled: bool = True
    target: str = ""
    every: float = 0.25
    jitter: float = 0.35
    double: float = 0.25
    slide: float = 0.15
    slide_ms: int = 320
    slide_target: str = ""
    max_taps: int = 0
    start: int = -1
    end: int = -1

    def is_set(self) -> bool:
        return 0 <= self.start < self.end

    def covers(self, i: int) -> bool:
        return self.is_set() and self.start < i <= self.end

@dataclass
class Flow:
    name: str = "flow"
    description: str = ""
    steps: list = field(default_factory=list)
    group_defs: list = field(default_factory=list)
    jump: Jump = field(default_factory=Jump)

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description,
                "group_defs": list(self.group_defs),
                "jump": asdict(self.jump),
                "steps": [asdict(s) for s in self.steps]}

    def jump_switch(self) -> dict:
        j = self.jump
        span = (j.end - j.start) if j.is_set() else 0
        note = (f"ขั้น {j.start + 2}-{j.end + 1} · แตะ " + (j.target or "จุดเริ่มต้น")
                if j.is_set() else "ยังไม่ได้ตั้งช่วง (ตั้งในโหมดเดฟ)")
        hint = ("กระโดดเองระหว่างที่แอปกำลังทำงาน" if j.is_set()
                else "ยังไม่ได้ตั้งช่วง (ตั้งในโหมดเดฟ)")
        return {"name": JUMP_GROUP, "steps": span, "enabled": bool(j.enabled),
                "jump": True, "note": note, "hint": hint,
                "cfg": {"every": j.every, "jitter": j.jitter,
                        "double": j.double, "slide": j.slide,
                        "max_taps": j.max_taps}}

    def tune_jump(self, cfg: dict) -> bool:
        j = self.jump
        before = (j.every, j.jitter, j.double, j.slide, j.max_taps)
        if "every" in cfg:
            j.every = _num(cfg["every"], j.every, MIN_SPAM_INTERVAL, 5)
        if "jitter" in cfg:
            j.jitter = _num(cfg["jitter"], j.jitter, 0, 0.9)
        if "double" in cfg:
            j.double = _num(cfg["double"], j.double, 0, 1)
        if "slide" in cfg:
            j.slide = _num(cfg["slide"], j.slide, 0, 1)
        if "max_taps" in cfg:
            j.max_taps = int(_num(cfg["max_taps"], j.max_taps, 0, MAX_TAPS_CAP))
        return (j.every, j.jitter, j.double, j.slide, j.max_taps) != before

    def clamp_jump(self) -> None:
        j = self.jump
        last = len(self.steps) - 1
        if last < 1 or j.start < 0 or j.end < 0:
            j.start = j.end = -1
            return
        j.start = max(0, min(j.start, last - 1))
        j.end = max(j.start + 1, min(j.end, last))

    def sync_group_defs(self) -> None:
        defs = [g for g in self.group_defs if isinstance(g, str) and g.strip()]
        seen = set(defs)
        for s in self.all_steps():
            if s.group and s.group not in seen:
                defs.append(s.group)
                seen.add(s.group)
        self.group_defs = defs

    def add_group(self, name: str) -> bool:
        name = (name or "").strip()
        if not name or name in self.group_defs:
            return False
        self.group_defs.append(name)
        return True

    def remove_group(self, name: str) -> None:
        self.group_defs = [g for g in self.group_defs if g != name]
        for s in self.all_steps():
            if s.group == name:
                s.group = ""

    def rename_group(self, old: str, new: str) -> bool:
        new = (new or "").strip()
        if not new or old not in self.group_defs or new in self.group_defs:
            return False
        self.group_defs = [new if g == old else g for g in self.group_defs]
        for s in self.all_steps():
            if s.group == old:
                s.group = new
        return True

    def all_steps(self):
        for s in self.steps:
            yield s
            yield from (s.steps or [])

    def groups(self, include_empty: bool = False) -> list[dict]:
        self.sync_group_defs()
        counts = {g: 0 for g in self.group_defs}
        on = {g: True for g in self.group_defs}
        note = {g: "" for g in self.group_defs}
        for s in self.all_steps():
            if s.group not in counts:
                continue
            counts[s.group] += 1
            on[s.group] = on[s.group] and s.enabled
            note[s.group] = note[s.group] or s.note
        return [{"name": g, "steps": counts[g],
                 "enabled": on[g] if counts[g] else False, "note": note[g],
                 "hint": _hint(note[g], counts[g])}
                for g in self.group_defs if include_empty or counts[g]]

    def set_group(self, name: str, on: bool) -> int:
        n = 0
        for s in self.all_steps():
            if s.group == name and s.enabled != on:
                s.enabled = on
                n += 1
        return n

    def set_text(self, value) -> int:
        text = str(value or "").strip()
        if not text:
            return 0
        n = 0
        for s in self.all_steps():
            if s.action == "type_text" and s.text != text:
                s.text = text
                n += 1
        return n

    def set_choice(self, group: str, names) -> int:
        want = {_name_key(n) for n in (names or []) if str(n).strip()}
        if not want:
            return 0
        n = 0
        for s in self.all_steps():
            if s.group != group or not uses_until(s):
                continue
            cand = s.until_list()
            keep = [t for t in cand if _name_key(display_name(t)) in want]
            if keep and len(keep) != len(cand):
                s.until = join_until(keep)
                n += 1
        return n

def text_ask(flow: "Flow") -> dict | None:
    steps = [s for s in flow.all_steps() if s.action == "type_text"]
    if not steps:
        return None
    note = next((s.note.strip() for s in steps if s.note.strip()), "")
    clean = note and not _looks_internal(note) and not _looks_like_a_file_name(note)
    return {"label": note if clean else DEFAULT_ASK_LABEL,
            "value": steps[0].text or ""}

def choices(flow: "Flow", picks: dict | None = None) -> list[dict]:
    picked_of = picks or {}
    out = []
    flow.sync_group_defs()
    for group in flow.group_defs:
        opts = {}
        for s in flow.all_steps():
            if s.group != group or not uses_until(s):
                continue
            cand = s.until_list()
            if len(cand) < 2:
                continue
            for name in cand:
                shown = display_name(name)
                opts.setdefault(_name_key(shown), shown)
        if not opts:
            continue
        want = {_name_key(n) for n in (picked_of.get(group) or [])}
        out.append({"group": group, "all": not want,
                    "options": [{"name": shown, "on": not want or key in want}
                                for key, shown in opts.items()]})
    return out

def normalize_choice(flow: "Flow", group: str, names) -> list[str]:
    opts = next((c["options"] for c in choices(flow) if c["group"] == group), [])
    want = {_name_key(n) for n in (names or [])}
    out = [o["name"] for o in opts if _name_key(o["name"]) in want]
    return [] if len(out) == len(opts) else out

def unreachable_choices(flow: "Flow") -> list[dict]:
    out = []
    for i, top in enumerate(flow.steps):
        rows = [(str(i), top)]
        rows += [(f"{i}.{k}", s) for k, s in enumerate(top.steps or [])]
        for path, s in rows:
            if (s.group or "").strip() or not uses_until(s):
                continue
            count = len(s.until_list())
            if count >= 2:
                out.append({"path": path, "no": _human(path),
                            "action": s.action, "count": count})
    return out

_BASE_FIELDS = ("enabled", "timeout", "after", "seconds", "until", "text")
_BASE_ATTR = "_override_base"

def snapshot_base(flow: "Flow") -> "Flow":
    for s in flow.all_steps():
        if not hasattr(s, _BASE_ATTR):
            setattr(s, _BASE_ATTR, tuple(getattr(s, f) for f in _BASE_FIELDS))
    return flow

def restore_base(flow: "Flow") -> "Flow":
    for s in flow.all_steps():
        base = getattr(s, _BASE_ATTR, None)
        if base:
            for f, v in zip(_BASE_FIELDS, base):
                setattr(s, f, v)
    return flow

def apply_override(flow: "Flow", override: dict | None) -> "Flow":
    restore_base(flow)
    if not override:
        return flow
    snapshot_base(flow)
    for name, on in (override.get("groups") or {}).items():
        if name == JUMP_GROUP:
            flow.jump.enabled = bool(on)
        else:
            flow.set_group(name, bool(on))
    for group, names in (override.get("choices") or {}).items():
        flow.set_choice(group, names)
    flow.set_text(override.get("text"))
    j = override.get("jump")
    if j:
        flow.tune_jump(j)
        if "enabled" in j:
            flow.jump.enabled = bool(j["enabled"])
    scale_pace(flow, override.get("pace"))
    return flow

PACE_MIN, PACE_MAX = 1.0, 3.0

def scale_pace(flow: "Flow", pace) -> "Flow":
    try:
        p = float(pace)
    except (TypeError, ValueError):
        return flow
    if p <= 1.0:
        return flow
    p = max(PACE_MIN, min(PACE_MAX, p))

    def walk(steps):
        for s in steps:
            s.timeout = round(s.timeout * p, 2)
            s.after = round(s.after * p, 2)
            s.seconds = round(s.seconds * p, 2)
            walk(s.steps or [])

    walk(flow.steps)
    return flow

def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]+", "", str(name)).strip()
    return cleaned or "flow"

def flow_path(name: str):
    return FLOWS_DIR / f"{_safe_name(name)}.json"

def list_flows() -> list[str]:
    names = set()
    try:
        names = {p.stem for p in FLOWS_DIR.glob("*.json")
                 if not p.name.endswith((".bak.json", ".json.tmp"))}
    except OSError:
        pass
    from . import assets
    names.update(assets.flow_names())
    return sorted(names)

def load_flow(name: str) -> Flow:
    path = flow_path(name)
    if not path.exists():
        from . import assets
        raw = assets.flow_bytes(_safe_name(name))
        if raw is not None:
            try:
                return from_dict(json.loads(raw.decode("utf-8")),
                                 fallback_name=_safe_name(name))
            except (ValueError, UnicodeError):
                pass
        return Flow(name=_safe_name(name))
    for attempt in range(READ_RETRIES):
        try:
            return from_dict(json.loads(path.read_text(encoding="utf-8")),
                             fallback_name=path.stem)
        except (ValueError, OSError):
            if attempt == READ_RETRIES - 1:
                return Flow(name=_safe_name(name))
            time.sleep(0.05)
    return Flow(name=_safe_name(name))

def steps_from(raw_steps, depth: int = 0) -> list:
    known = set(Step.__dataclass_fields__)
    out = []
    for raw in (raw_steps or []):
        if not isinstance(raw, dict):
            continue
        kw = {k: v for k, v in raw.items() if k in known}
        children = kw.pop("steps", None)
        step = Step(**kw)
        step.until = join_until(step.until)
        if step.action not in ACTIONS:
            continue
        if depth == 0 and step.action in NESTED_ACTIONS:
            step.steps = steps_from(children, depth + 1)
        else:
            step.steps = []
        out.append(step)
    return out

def from_dict(data: dict, fallback_name: str = "flow") -> Flow:
    raw_defs = data.get("group_defs")
    flow = Flow(name=data.get("name") or fallback_name,
                description=data.get("description") or "",
                steps=steps_from(data.get("steps")),
                group_defs=[str(g) for g in raw_defs
                            if isinstance(g, str) and g.strip()]
                if isinstance(raw_defs, list) else [])
    flow.sync_group_defs()
    flow.jump = _jump_from(data)
    flow.clamp_jump()
    return flow

def _num(raw, fallback, lo=None, hi=None):
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return fallback
    if lo is not None:
        v = max(lo, v)
    return min(hi, v) if hi is not None else v

def _jump_from(data: dict) -> Jump:
    raw = data.get("jump")
    if isinstance(raw, dict):
        return Jump(enabled=bool(raw.get("enabled", True)),
                    target=str(raw.get("target") or ""),
                    every=_num(raw.get("every"), 0.25, MIN_SPAM_INTERVAL, 5),
                    jitter=_num(raw.get("jitter"), 0.35, 0, 0.9),
                    double=_num(raw.get("double"), 0.25, 0, 1),
                    slide=_num(raw.get("slide"), 0.15, 0, 1),
                    slide_ms=int(_num(raw.get("slide_ms"), 320, 60, 2000)),
                    slide_target=str(raw.get("slide_target") or ""),
                    max_taps=int(_num(raw.get("max_taps"), 0, 0, MAX_TAPS_CAP)),
                    start=int(_num(raw.get("start"), -1, -1)),
                    end=int(_num(raw.get("end"), -1, -1)))

    j = Jump(target=str(data.get("spam_target") or ""),
             every=_num(data.get("spam_every"), 0.25, MIN_SPAM_INTERVAL, 5))
    raw_steps = [s for s in (data.get("steps") or []) if isinstance(s, dict)]
    marked = [i for i, s in enumerate(raw_steps)
              if s.get("spam") or s.get("spam_target")]
    for s in raw_steps:
        if s.get("spam_target") and not j.target:
            j.target = str(s["spam_target"])
            j.every = _num(s.get("spam_every"), j.every, MIN_SPAM_INTERVAL, 5)
    if marked:
        j.start = max(0, marked[0] - 1)
        j.end = marked[-1]
    return j

def backup_path(name: str):
    return FLOWS_DIR / f"{_safe_name(name)}.bak.json"

def save_flow(flow: Flow) -> None:
    FLOWS_DIR.mkdir(parents=True, exist_ok=True)
    path = flow_path(flow.name)
    if path.exists():
        try:
            backup_path(flow.name).write_text(path.read_text(encoding="utf-8"),
                                              encoding="utf-8")
        except OSError:
            pass
    text = json.dumps(flow.to_dict(), indent=2, ensure_ascii=False)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(WRITE_RETRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    try:
        path.write_text(text, encoding="utf-8")
    finally:
        tmp.unlink(missing_ok=True)

def restore_flow(name: str) -> bool:
    bak = backup_path(name)
    if not bak.exists():
        return False
    try:
        flow_path(name).write_text(bak.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        return False
    return True

def delete_flow(name: str) -> bool:
    try:
        flow_path(name).unlink(missing_ok=True)
        return True
    except OSError:
        return False

def _noop(*_a, **_k):
    pass

def _human(path: str) -> str:
    return ".".join(str(int(p) + 1) for p in str(path).split("."))

class Jumper:

    def __init__(self, bot, cfg: Jump, log=_noop, paused=_noop, seed=None):
        self.bot = bot
        self.cfg = cfg
        self.log = log
        self.paused = paused
        self.rng = random.Random(seed)
        self.taps = 0
        self.doubles = 0
        self.slides = 0
        self.round_taps = 0
        self._said_cap = False
        self._on = threading.Event()
        self._done = threading.Event()
        self._thread = None
        self._warned = False

    def switch(self, on: bool) -> None:
        if on and not self._on.is_set():
            self.round_taps = 0
            self._said_cap = False
            self._on.set()
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, daemon=True)
                self._thread.start()
        elif not on:
            self._on.clear()

    def close(self) -> None:
        self._on.clear()
        self._done.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def summary(self) -> str:
        bits = [f"กระโดด {self.taps} ครั้ง"]
        if self.doubles:
            bits.append(f"สองชั้น {self.doubles}")
        if self.slides:
            bits.append(f"สไลด์ {self.slides}")
        return " · ".join(bits)

    def _point(self, name: str):
        pos = (self.bot.buttons.get(name) or {}).get("pos")
        if pos:
            return pos
        if not self._warned:
            self._warned = True
            self.log(f"  (กระโดดรัว: '{name or 'ยังไม่ได้เลือกรูป'}' ไม่มีพิกัด"
                     f" · ใช้จุดเริ่มต้น {JUMP_FALLBACK} ไปก่อน)")
        return JUMP_FALLBACK

    def _capped(self) -> bool:
        cap = int(self.cfg.max_taps or 0)
        if cap <= 0 or self.round_taps < cap:
            return False
        if not self._said_cap:
            self._said_cap = True
            self.log(f"  (กระโดดครบ {cap} ครั้งแล้ว · หยุดกระโดดรอบนี้)")
        return True

    def _gap(self) -> float:
        c = self.cfg
        spread = max(0.0, min(0.9, c.jitter))
        base = max(MIN_SPAM_INTERVAL, c.every)
        return max(MIN_SPAM_INTERVAL,
                   base * self.rng.uniform(1 - spread, 1 + spread))

    def _jump_once(self) -> None:
        pos = self._point(self.cfg.target)
        x, y = self.bot.to_screen(*pos)
        self.bot.device.tap(x, y)
        self.taps += 1
        self.round_taps += 1
        if self.rng.random() < self.cfg.double:
            self._done.wait(self.rng.uniform(0.09, 0.17))
            self.bot.device.tap(x, y)
            self.taps += 1
            self.round_taps += 1
            self.doubles += 1

    def _slide_once(self) -> None:
        pos = self._point(self.cfg.slide_target or self.cfg.target)
        bottom = getattr(self.bot, "base_h", 0) or DEFAULT_BASE_RESOLUTION[1]
        x, y = self.bot.to_screen(*pos)
        x2, y2 = self.bot.to_screen(pos[0], min(pos[1] + SLIDE_DROP, bottom - 1))
        ms = int(max(60, self.cfg.slide_ms) * self.rng.uniform(0.7, 1.3))
        self.bot.device.swipe(x, y, x2, y2, duration_ms=ms)
        self.slides += 1

    def _loop(self) -> None:
        while not self._done.is_set():
            if not self._on.is_set() or self._capped():
                self._done.wait(0.05)
                continue
            self.paused()
            try:
                if self.rng.random() < self.cfg.slide:
                    self._slide_once()
                else:
                    self._jump_once()
            except Exception as e:
                try:
                    self.log(f"  (กระโดดรัวไม่สำเร็จ: {e})")
                except Exception:
                    pass
                self._done.wait(0.2)
            self._done.wait(self._gap())

class FlowRunner:

    stage = ""
    live = None
    flow = None
    allow_spam = True
    _live_token = None
    _top_i = 0
    work_rounds = 0
    work_taps = 0
    on_mark = staticmethod(_noop)

    def __init__(self, bot, steps, log=_noop, on_step=_noop,
                 should_stop=lambda: False, loops=1, wait_if_paused=_noop,
                 on_fail=_noop, allow_spam=True, jump=None, seed=None,
                 stage="", stopped_msg=None, on_mark=_noop,
                 flow=None, live=None):
        self.bot = bot
        self.steps = steps
        self.log = log
        self.on_step = on_step
        self.should_stop = should_stop
        self.stopped_msg = stopped_msg or "หยุดโดยผู้ใช้"
        self.loops = loops
        self.on_fail = on_fail
        self.wait_if_paused = wait_if_paused
        self.on_mark = on_mark
        self.jump = jump if isinstance(jump, Jump) else Jump()
        self.allow_spam = bool(allow_spam)
        self.jumping = self.allow_spam and self.jump.enabled and self.jump.is_set()
        self.flow = flow if isinstance(flow, Flow) else None
        self.live = live if (callable(live) and self.flow is not None) else None
        self._live_token = self._live_now()
        self.jumper = Jumper(bot, self.jump, log=self._tech,
                             paused=self._hold, seed=seed)
        self.stage = str(stage or "")
        self.work_rounds = 0
        self.work_taps = 0
        self._streaks: dict = {}
        self._phase_now = ""
        self._stage_now = ""
        self._in_game = False

    def _tech(self, msg: str) -> None:
        if DETAIL:
            self.log(msg)

    def _in_game_step(self, step: "Step", i: int) -> bool:
        return self.jump.covers(i) or step.timeout >= LONG_WAIT_SEC

    def _stage(self, step: "Step", i: int) -> str:
        if self.stage:
            return self.stage
        if self._in_game_step(step, i):
            return STAGE_INGAME
        return STAGE_AFTER if self._in_game else STAGE_SHOP

    def _phase(self, step: "Step", i: int = 0) -> None:
        stage = self._stage(step, i)
        name = (step.group or "").strip()
        if not name:
            if stage == self._stage_now:
                return
            name = STAGE_DEFAULT.get(stage) or STAGE_DEFAULT[STAGE_ERRAND]
        line = f"[{stage}] {name}"
        if line != self._phase_now:
            self._phase_now = line
            self._stage_now = stage
            self.log(line)

    def _hold(self) -> None:
        self.wait_if_paused()

    def _live_now(self):
        if self.live is None:
            return None
        override, pace, allow_spam = self.live()
        return dict(override or {}), pace, bool(allow_spam)

    def _refresh_live(self) -> None:
        token = self._live_now()
        if token is None or token == self._live_token:
            return
        self._live_token = token
        override, pace, allow_spam = token
        apply_override(self.flow, {**override, "pace": pace})
        self.allow_spam = allow_spam
        was = self.jumping
        self.jumping = allow_spam and self.jump.enabled and self.jump.is_set()
        if not self.jumping:
            if was:
                self.jumper.switch(False)
        else:
            self.jumper.switch(self.jump.covers(self._top_i))

    def _sleep(self, seconds: float) -> bool:
        end = time.time() + max(0.0, seconds)
        while time.time() < end:
            if self.should_stop():
                return False
            self.wait_if_paused()
            self._refresh_live()
            time.sleep(0.05)
        return not self.should_stop()

    def _wait_visible(self, name: str, timeout: float, want=True):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.should_stop():
                return None
            self.bot.capture()
            if self.bot.is_visible(name) == want:
                if want:
                    self.on_mark(name)
                return True
            if not self._sleep(min(POLL_SLICE, deadline - time.time())):
                return None
        return None

    def _known(self, name: str) -> bool:
        return bool(name) and name in self.bot.buttons

    def _goals(self, step: Step) -> list[str]:
        return [n for n in step.until_list() if self._known(n)]

    def _first_seen(self, names) -> str:
        for name in names:
            if self.bot.is_visible(name):
                return name
        return ""

    def run(self) -> bool:
        total = len(self.steps)
        self._tech(f"เริ่ม flow {total} ขั้นตอน")
        j = self.jump
        if self.jumping:
            self._tech(f"กระโดดรัว: หลังจบขั้น {j.start + 1} ถึงจบขั้น {j.end + 1}"
                       f" · แตะ {j.target} ทุก ~{j.every:g} วิ"
                       f" (สุ่ม ±{j.jitter * 100:.0f}% · สองชั้น {j.double * 100:.0f}%"
                       f" · สไลด์ {j.slide * 100:.0f}%)")
        elif j.enabled and j.is_set():
            self._tech("กระโดดรัว: ปิดอยู่ (สวิตช์ในหน้าหลัก)")
        try:
            endless = self.loops <= 0
            if endless:
                self.log("วนไม่รู้จบ · กด หยุด เพื่อจบ")
            loop = 0
            while endless or loop < self.loops:
                if self.should_stop():
                    self._say_stopped()
                    return False
                if endless:
                    self.log(f"=== รอบ {loop + 1} (วนไม่จบ) ===")
                elif self.loops > 1:
                    self.log(f"=== รอบ {loop + 1}/{self.loops} ===")
                self._in_game = False
                self._streaks = {}
                if not self._play_list(self.steps, ""):
                    return False
                loop += 1
        finally:
            self.jumper.close()
            if self.jumper.taps or self.jumper.slides:
                self.log(f"[{STAGE_INGAME}] {self.jumper.summary()}")
            elif self.jumping:
                self.log(f"[{STAGE_INGAME}] กระโดดรัวเปิดอยู่ แต่รอบนี้ไม่ได้กระโดดเลย")
        self.log(f"[{self.stage}] เสร็จแล้ว ✓" if self.stage else "จบรอบ ✓")
        return True

    def _say_stopped(self) -> None:
        msg = self.stopped_msg() if callable(self.stopped_msg) else self.stopped_msg
        if msg:
            self.log(str(msg))

    def _play_list(self, steps, prefix: str) -> bool:
        top = prefix == ""
        n = len(steps)
        i = 0
        jumps = 0
        while i < n:
            if self.should_stop():
                self._say_stopped()
                return False
            if top:
                self._top_i = i
                self._refresh_live()
            step = steps[i]
            if top and self.jumping:
                self.jumper.switch(self.jump.covers(i))
            path = f"{prefix}{i}"
            if not step.enabled:
                self.on_step(path, "off")
                self._tech(f"[{_human(path)}] {step.label()} · ปิดอยู่ ข้าม")
                i += 1
                continue
            if top:
                self._phase(step, i)
                if self._in_game_step(step, i):
                    self._in_game = True
            self.on_step(path, "running")
            try:
                status = self._play(path, step)
            except _Goto as g:
                if not top:
                    raise
                jumps += 1
                if jumps > MAX_JUMPS_PER_PASS:
                    self._tech(f"กระโดดวนเกิน {MAX_JUMPS_PER_PASS} ครั้ง · ตัดจบรอบ (เช็ค goto)")
                    return True
                i = max(0, min(g.to, n))
                continue
            self.on_step(path, status)
            if status == "fail":
                if self.should_stop():
                    if top:
                        self._say_stopped()
                    return False
                self._tech(f"[{_human(path)}] ล้มเหลว · หยุด")
                if not DETAIL:
                    self.log("ไปต่อไม่ได้ · จบรอบนี้ก่อน แล้วเริ่มใหม่")
                self._report_fail(path, step)
                return False
            i += 1
        return True

    def _report_fail(self, path, step) -> None:
        try:
            self.on_fail({"path": path, "no": _human(path),
                          "label": step.label(), "action": step.action,
                          "target": step.target or step.until, "note": step.note})
        except Exception as e:
            self.log(f"(เก็บภาพตอนหยุดไม่สำเร็จ: {e})")

    def _play(self, path: str, step: Step) -> str:
        tag = f"[{_human(path)}] {step.label()}"
        action = step.action

        if action == "repeat_until":
            return self._repeat_until(path, step, tag)

        if action == "if_seen":
            return self._if_seen(path, step, tag)

        if action == "guard" or action == "skip_if_seen":
            return self._gate(path, step, tag)

        if action == "goto_step":
            return self._goto_step(path, step, tag)

        if action == "watch_until" or action == "watch_choice":
            return self._watch_until(path, step, tag)

        if action == "sleep":
            self._tech(f"{tag}")
            return "ok" if self._sleep(step.seconds) else "fail"

        if action == "tap_xy":
            x, y = self.bot.to_screen(step.x, step.y)
            self._tech(f"{tag} -> จอจริง ({x}, {y})")
            self.bot.device.tap(x, y)
            return "ok" if self._sleep(step.after) else "fail"

        if action == "swipe":
            return self._swipe(step, tag)

        if action == "type_text":
            return self._type_text(step, tag)

        if not self._known(step.target):
            self._tech(f"{tag} · ยังไม่มีรูปนี้ ({step.target or 'ว่าง'}) ข้าม")
            return "skip" if step.optional else "fail"

        if action == "wait_for" or action == "wait_gone":
            want = action == "wait_for"
            self._tech(f"{tag} (ไม่เกิน {step.timeout:g} วิ)")
            if self._wait_visible(step.target, step.timeout, want=want):
                return "ok"
            self._tech(f"{tag} · ไม่เกิดขึ้นใน {step.timeout:g} วิ")
            return "skip" if step.optional else "fail"

        if action == "tap":
            if self._wait_visible(step.target, step.timeout) is None:
                self._tech(f"{tag} · ไม่เจอใน {step.timeout:g} วิ")
                return "skip" if step.optional else "fail"
            return self._tap(step, tag)

        self._tech(f"{tag} · ไม่รู้จัก action '{action}'")
        return "fail"

    def _swipe(self, step: Step, tag: str) -> str:
        bot = self.bot
        start = None
        if self._known(step.target):
            bot.capture()
            start = bot.find(step.target)
            if start is None:
                self._tech(f"{tag} · ไม่เห็น {step.target} บนจอ ใช้พิกัดที่ตั้งไว้แทน")
        if start is None:
            if not (step.x or step.y):
                self._tech(f"{tag} · ไม่มีทั้งรูปยึดและพิกัดจุดเริ่ม ข้าม")
                return "skip" if step.optional else "fail"
            start = bot.to_screen(step.x, step.y)
        dx, dy = float(step.dx or 0), float(step.dy or 0)
        if not (dx or dy):
            self._tech(f"{tag} · ระยะปัดเป็น 0 ข้าม")
            return "skip" if step.optional else "fail"
        scale = float(getattr(bot, "scale", 1.0) or 1.0)
        w = int(getattr(bot, "screen_w", 0) or 0)
        h = int(getattr(bot, "screen_h", 0) or 0)
        x1, y1 = int(start[0]), int(start[1])
        x2 = int(round(x1 + dx * scale))
        y2 = int(round(y1 + dy * scale))
        if w > 1:
            x1, x2 = min(max(0, x1), w - 1), min(max(0, x2), w - 1)
        if h > 1:
            y1, y2 = min(max(0, y1), h - 1), min(max(0, y2), h - 1)
        ms = int(max(60, step.swipe_ms or 300))
        self._tech(f"{tag} -> จอจริง ({x1}, {y1}) -> ({x2}, {y2}) ใน {ms} ms")
        bot.device.swipe(x1, y1, x2, y2, duration_ms=ms)
        return "ok" if self._sleep(step.after) else "fail"

    def _type_text(self, step: Step, tag: str) -> str:
        body = (step.text or "").strip()
        if not body:
            self._tech(f"{tag} · ยังไม่ได้ใส่ข้อความ ข้าม")
            return "skip" if step.optional else "fail"
        if any(ord(c) > 127 for c in body):
            self._tech(f"{tag} · มีตัวอักษรที่คีย์บอร์ดของเครื่องพิมพ์ไม่ได้"
                       " (ต้องเป็นอังกฤษ/ตัวเลขเท่านั้น) ตัวพวกนั้นจะไม่ขึ้น")
        if step.target:
            if not self._known(step.target):
                self._tech(f"{tag} · ยังไม่มีรูปช่องค้นหา ({step.target}) ข้าม")
                return "skip" if step.optional else "fail"
            if self._wait_visible(step.target, step.timeout) is None:
                self._tech(f"{tag} · ไม่เจอช่องค้นหาใน {step.timeout:g} วิ")
                return "skip" if step.optional else "fail"
            self.bot.tap(step.target)
            self.work_taps += 1
            if not self._sleep(TAP_SETTLE):
                return "fail"
        self._tech(f"{tag} · พิมพ์ {body!r}" + (" แล้วกด Enter" if step.submit else ""))
        self.bot.device.text(body)
        if step.submit:
            self.bot.device.key("KEYCODE_ENTER")
        return "ok" if self._sleep(step.after) else "fail"

    def _tap(self, step: Step, tag: str) -> str:
        left = max(0.0, step.after)
        for n in range(1, TAP_RETRIES + 1):
            if not self.bot.tap(step.target):
                self._tech(f"{tag} · จอเปลี่ยนไปก่อน ไม่ได้แตะ")
                return "skip" if step.optional else "fail"
            self.work_taps += 1
            if not self._sleep(TAP_SETTLE):
                return "fail"
            left = max(0.0, left - TAP_SETTLE)
            self.bot.capture()
            if not self.bot.is_visible(step.target):
                self._tech(f"{tag} ✓" + (f" (แตะ {n} ครั้ง)" if n > 1 else ""))
                return "ok" if self._sleep(left) else "fail"
        self._tech(f"{tag} · แตะ {TAP_RETRIES} ครั้งแล้ว {step.target} ยังอยู่บนจอ"
                 f" (เกมไม่รับ หรือปุ่มนี้ไม่ได้หายหลังแตะ)")
        return "ok" if self._sleep(left) else "fail"

    def _if_seen(self, path: str, step: Step, tag: str) -> str:
        if not self._known(step.target):
            self._tech(f"{tag} · ยังไม่มีรูปนี้ ({step.target or 'ว่าง'}) ข้าม")
            return "skip"
        if step.timeout > 0:
            seen = self._wait_visible(step.target, step.timeout) is not None
        else:
            self.bot.capture()
            seen = bool(self.bot.is_visible(step.target))
        body = list(step.steps or [])
        if not seen:
            self._tech(f"{tag} · ไม่เจอ {step.target} ข้าม {len(body)} ขั้นตอนข้างใน")
            return "skip"
        self._tech(f"{tag} · เจอ {step.target} ✓ ทำต่อ {len(body)} ขั้นตอน")
        if body and not self._play_list(body, f"{path}."):
            return "fail"
        return "ok" if self._sleep(step.after) else "fail"

    def _streak_hit(self, path: str) -> int:
        hits = dict(getattr(self, "_streaks", None) or {})
        hits[path] = hits.get(path, 0) + 1
        self._streaks = hits
        return hits[path]

    def _streak_reset(self, path: str) -> None:
        hits = getattr(self, "_streaks", None)
        if hits:
            hits.pop(path, None)

    def _jump(self, path: str, step: Step, why: str):
        to, dest = goto_target(step)
        self._tech(f"{why} -> กระโดดไป {dest}")
        self.on_step(path, "skip")
        raise _Goto(to)

    def _goto_step(self, path: str, step: Step, tag: str) -> str:
        self._jump(path, step, f"{tag} · ไม่มีเงื่อนไข")

    def _gate(self, path: str, step: Step, tag: str) -> str:
        jump_on_seen = step.action == "skip_if_seen"
        if not self._known(step.target):
            self._tech(f"{tag} · ยังไม่มีรูปนี้ ({step.target or 'ว่าง'}) ปล่อยผ่าน")
            return "skip"
        if step.timeout > 0:
            seen = self._wait_visible(step.target, step.timeout) is not None
        else:
            self.bot.capture()
            seen = bool(self.bot.is_visible(step.target))
            if seen:
                self.on_mark(step.target)
        found = "เจอ" if seen else "ไม่เจอ"
        if seen != jump_on_seen:
            self._streak_reset(path)
            self._tech(f"{tag} · {found} {step.target} ✓ ผ่านด่าน ทำต่อ")
            return "ok"
        need = max(1, int(step.streak or 1))
        hits = self._streak_hit(path)
        if hits < need:
            self._tech(f"{tag} · {found} {step.target} ครั้งที่ {hits}/{need}"
                       f" · ยังไม่กระโดด")
            return "ok"
        self._streak_reset(path)
        self._jump(path, step, f"{tag} · {found} {step.target}")

    def _repeat_until(self, path: str, step: Step, tag: str) -> str:
        goals = self._goals(step)
        if not goals:
            self._tech(f"{tag} · ยังไม่มีรูปเงื่อนไข ({step.until or 'ว่าง'})")
            return "skip" if step.optional else "fail"
        body = list(step.steps or [])
        if not body and not self._known(step.target):
            self._tech(f"{tag} · ยังไม่มีทั้งขั้นตอนข้างในและรูปที่จะแตะ")
            return "skip" if step.optional else "fail"

        unlimited = step.max_tries <= 0
        n = 0
        while unlimited or n < step.max_tries:
            n += 1
            if self.should_stop():
                return "fail"
            self.bot.capture()
            hit = self._first_seen(goals)
            if hit:
                self._tech(f"{tag} · เจอ {hit} หลัง {n - 1} รอบ ✓")
                return "ok"
            self._tech(f"{tag} · รอบที่ {n}")
            if not _is_navigation(body):
                self.work_rounds += 1
            if body:
                if not self._play_list(body, f"{path}."):
                    return "fail"
            else:
                self.bot.tap(step.target)
            if not self._sleep(step.after):
                return "fail"
        self._tech(f"{tag} · ครบ {step.max_tries} รอบแล้วยังไม่เจอ {step.until}")
        return "skip" if step.optional else "fail"

    def _watch_until(self, path: str, step: Step, tag: str) -> str:
        named = step.action == "watch_choice"
        wanted, verb = (("รายการที่เลือกไว้", "ได้") if named
                        else (step.until or "ว่าง", "เจอ"))
        shown = display_name if named else str
        goals = self._goals(step)
        if not goals:
            self._tech(f"{tag} · ยังไม่มีรูปเงื่อนไข ({wanted})")
            return "skip" if step.optional else "fail"
        poll = max(MIN_POLL, step.poll or WATCH_POLL)
        deadline = time.time() + step.timeout
        idle = 0
        self._tech(f"{tag} · ตรวจจอทุก {poll:g} วิ (ไม่เกิน {step.timeout:g} วิ)")
        while time.time() < deadline:
            if self.should_stop():
                return "fail"
            self.bot.capture()
            hit = self._first_seen(goals)
            if hit:
                self._tech(f"{tag} · {verb} {shown(hit)} ✓")
                return "ok"
            idle += 1
            if idle == 1 or idle % 20 == 0:
                self._tech(f"{tag} · กำลังเฝ้า ...")
            if not self._sleep(poll):
                return "fail"
        self._tech(f"{tag} · ไม่เจอ {wanted} ใน {step.timeout:g} วิ")
        return "skip" if step.optional else "fail"
