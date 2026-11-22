"""Tie one device, calibrated buttons, and template matching together."""
import random
import time

import numpy as np

from .config import (
    TEMPLATES_DIR, base_resolution, read_autofit, read_buttons_file, write_autofit,
)
from .device import Device
from .vision import (
    load_template, locate, match_at_scale, match_score, resize_by, score_at_scale,
)

DEFAULT_THRESHOLD = 0.80
ROI_PAD = 60

ASPECT_TOLERANCE = 0.03
FIT_MIN_SCORE = 0.70
FIT_COARSE_STEP = 0.05
FIT_FINE_STEP = 0.01
FIT_LIMITS = (0.40, 2.60)
FIT_PROBE_KEEP = 3
FIT_COARSE_WIDTH = 720
FIT_SNAP = 0.02

def _auto_registered(buttons: dict) -> dict:
    known = {b.get("template") for b in buttons.values()}
    tpl_files = []
    if TEMPLATES_DIR.exists():
        tpl_files = [p.name for p in sorted(TEMPLATES_DIR.glob("*.png"))]
    out, seen = {}, set()
    for fname in tpl_files:
        stem = fname[:-4] if fname.endswith(".png") else fname
        if fname in seen or fname in known or stem in buttons or stem in out:
            continue
        seen.add(fname)
        out[stem] = {"pos": None, "template": fname, "rect": None}
    return out

def calibrated_names() -> set[str]:
    buttons, _meta = read_buttons_file()
    return set(buttons) | set(_auto_registered(buttons))

def _steps(lo: float, hi: float, step: float) -> list[float]:
    out, v = [], lo
    while v <= hi + 1e-9:
        out.append(round(v, 4))
        v += step
    return out

class Bot:
    def __init__(self, device: Device, threshold: float = DEFAULT_THRESHOLD,
                 autofit: bool = True, log=None):
        self.device = device
        self.threshold = threshold
        self.log = log or print
        self.buttons: dict = {}
        self.meta: dict = {}
        self.base_w, self.base_h = 0, 0
        self.scale = 1.0
        self.same_aspect = True
        self.screen_w, self.screen_h = 0, 0
        self.fit_info: dict = {}
        self._autofit = autofit
        self._fitted = False
        self._raw: dict = {}
        self._templates: dict = {}
        self._screen: np.ndarray | None = None
        self.load_buttons()

    def load_buttons(self) -> None:
        self.buttons, self.meta = read_buttons_file()
        self.base_w, self.base_h = base_resolution(self.meta)
        if not self.screen_w:
            self.screen_w, self.screen_h = self.base_w, self.base_h
        self.buttons.update(_auto_registered(self.buttons))
        self._raw.clear()
        self._templates.clear()

    def _raw_template(self, name: str) -> np.ndarray | None:
        b = self.buttons.get(name)
        if not b or not b.get("template"):
            return None
        if name not in self._raw:
            try:
                self._raw[name] = load_template(b["template"])
            except FileNotFoundError:
                self.log(f"[warn] template file missing for '{name}': {b['template']}")
                self._raw[name] = None
        return self._raw[name]

    def _template(self, name: str) -> np.ndarray | None:
        if name not in self._templates:
            raw = self._raw_template(name)
            self._templates[name] = None if raw is None else resize_by(raw, self.scale)
        return self._templates[name]

    def to_screen(self, x, y) -> tuple[int, int]:
        s = self.scale
        if self.same_aspect:
            return int(round(x * s)), int(round(y * s))
        nx = x * s if x <= self.base_w / 2 else self.screen_w - (self.base_w - x) * s
        ny = y * s if y <= self.base_h / 2 else self.screen_h - (self.base_h - y) * s
        return int(round(nx)), int(round(ny))

    def _apply_fit(self, scale: float, same_aspect: bool) -> None:
        self.scale = float(scale)
        self.same_aspect = same_aspect
        self._templates.clear()

    def fit_summary(self) -> str:
        f = self.fit_info
        if not f:
            return "[autofit] ยังไม่ได้วัด"
        w, h = f["screen"]
        bw, bh = f["base"]
        if f["source"] == "native":
            return f"[autofit] จอ {w}x{h} ตรงกับที่คาลิเบรตไว้ - ใช้ template ตรง ๆ"
        how = {"cache": "จำค่าไว้", "measured": "วัดเอง", "estimate": "ประมาณ"}.get(
            f["source"], f["source"])
        note = "" if f["same_aspect"] else "  ⚠ สัดส่วนจอต่างจากเดิม (ค้นทั้งจอแทน ROI)"
        warn = "" if f["source"] != "estimate" else \
            "  ⚠ หา template บนจอไม่เจอตอนวัด - ถ้าบอทกดพลาด ให้เปิดเกมค้างที่หน้า Lobby แล้วรันใหม่"
        return (f"[autofit] จอ {w}x{h} ≠ ที่คาลิเบรต {bw}x{bh} -> "
                f"ปรับ template x{f['scale']:.3f} ({how}, score {f['score']:.2f})"
                f"{note}{warn}")

    def fit_to_screen(self, force: bool = False) -> dict:
        if self._screen is None:
            self._screen = self.device.screenshot()
        h, w = self._screen.shape[:2]
        bw, bh = self.base_w, self.base_h
        self.screen_w, self.screen_h = w, h
        info = {"screen": [w, h], "base": [bw, bh], "scale": 1.0, "score": 1.0,
                "source": "native", "same_aspect": True}

        if (w, h) == (bw, bh):
            self._apply_fit(1.0, True)
            self.fit_info = info
            return info

        same_aspect = abs(w / h - bw / bh) <= ASPECT_TOLERANCE
        key = f"{w}x{h}"
        cache = read_autofit()
        hit = None if force else cache.get(key)
        if isinstance(hit, dict) and hit.get("base") == [bw, bh]:
            info.update(scale=float(hit["scale"]), score=float(hit.get("score", 0.0)),
                        source="cache", same_aspect=same_aspect)
        else:
            estimate = h / bh
            scale, score = self._search_scale(estimate)
            trusted = score >= FIT_MIN_SCORE
            info.update(scale=scale if trusted else estimate, score=score,
                        same_aspect=same_aspect,
                        source="measured" if trusted else "estimate")
            if trusted:
                cache[key] = {"base": [bw, bh], "scale": round(scale, 4),
                              "score": round(score, 4)}
                write_autofit(cache)
        self._apply_fit(info["scale"], same_aspect)
        self.fit_info = info
        return info

    def _fit_templates(self) -> list:
        tpls = []
        for name, b in self.buttons.items():
            if not b.get("template"):
                continue
            raw = self._raw_template(name)
            if raw is not None:
                tpls.append(raw)
        return tpls

    def _search_scale(self, estimate: float) -> tuple[float, float]:
        tpls = self._fit_templates()
        if not tpls or self._screen is None:
            return estimate, 0.0
        h, w = self._screen.shape[:2]
        lo = max(FIT_LIMITS[0], estimate * 0.55)
        hi = min(FIT_LIMITS[1], estimate * 1.55)
        shrink = min(1.0, FIT_COARSE_WIDTH / w)
        small = resize_by(self._screen, shrink)

        probes = {estimate, w / self.base_w, min(w / self.base_w, h / self.base_h), 1.0}
        ranked = [(max(score_at_scale(small, t, p * shrink) for p in probes), t)
                  for t in tpls]
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        candidates = [t for _v, t in ranked[:FIT_PROBE_KEEP]]

        best_s, best_v, best_tpl, best_at = estimate, -1.0, candidates[0], (0, 0)
        for s in _steps(lo, hi, FIT_COARSE_STEP):
            for t in candidates:
                v, at = match_at_scale(small, t, s * shrink)
                if v > best_v:
                    best_s, best_v, best_tpl, best_at = s, v, t, at
        hi_s = min(FIT_LIMITS[1], best_s + FIT_COARSE_STEP)
        th, tw = best_tpl.shape[:2]
        tw, th = tw * hi_s, th * hi_s
        pad = max(24.0, 0.3 * max(tw, th))
        region = (best_at[0] / shrink - pad, best_at[1] / shrink - pad,
                  tw + 2 * pad, th + 2 * pad)
        fine_s, fine_v = best_s, -1.0
        for s in _steps(max(FIT_LIMITS[0], best_s - FIT_COARSE_STEP), hi_s, FIT_FINE_STEP):
            v = score_at_scale(self._screen, best_tpl, s, region=region)
            if v > fine_v:
                fine_s, fine_v = s, v
        if abs(fine_s - estimate) <= FIT_SNAP * estimate:
            snapped = score_at_scale(self._screen, best_tpl, estimate, region=region)
            fine_s, fine_v = estimate, max(fine_v, snapped)
        return fine_s, max(fine_v, 0.0)

    def capture(self) -> np.ndarray:
        self._screen = self.device.screenshot()
        if self._autofit and not self._fitted:
            self._fitted = True
            try:
                self.fit_to_screen()
                self.log(self.fit_summary())
            except Exception as e:
                self.log(f"[autofit] ปรับสเกลไม่สำเร็จ ({e}) - ใช้ขนาดเดิม")
        return self._screen

    def screen(self) -> np.ndarray:
        if self._screen is None:
            self.capture()
        return self._screen

    def _region(self, name: str) -> tuple | None:
        b = self.buttons.get(name)
        rect = b.get("rect") if b else None
        if not rect or not self.same_aspect:
            return None
        x, y, w, h = rect
        s = self.scale
        p = ROI_PAD * s
        return (x * s - p, y * s - p, w * s + 2 * p, h * s + 2 * p)

    def score(self, name: str) -> float:
        tpl = self._template(name)
        if tpl is None:
            return 0.0
        return match_score(self.screen(), tpl, region=self._region(name))

    def find(self, name: str, threshold: float | None = None) -> tuple[int, int] | None:
        b = self.buttons.get(name)
        if not b:
            return None
        tpl = self._template(name)
        if tpl is None:
            return self.to_screen(*b["pos"]) if b.get("pos") else None
        th = self.threshold if threshold is None else threshold
        return locate(self.screen(), tpl, threshold=th, region=self._region(name))

    def is_visible(self, name: str, threshold: float | None = None) -> bool:
        return self.find(name, threshold) is not None

    def visible_buttons(self) -> dict[str, float]:
        scores = {n: self.score(n) for n in self.buttons if self.buttons[n].get("template")}
        return dict(sorted(scores.items(), key=lambda kv: kv[1], reverse=True))

    def tap(self, name: str, threshold: float | None = None,
            jitter: int = 4, dry: bool = False) -> bool:
        target = self.find(name, threshold)
        if target is None:
            return False
        x, y = target
        x += random.randint(-jitter, jitter)
        y += random.randint(-jitter, jitter)
        if dry:
            print(f"[dry] would tap {name} at ({x}, {y})")
            return True
        self.device.tap(x, y)
        return True

    def tap_pos(self, name: str, dry: bool = False) -> bool:
        b = self.buttons.get(name)
        if not b or not b.get("pos"):
            return False
        x, y = self.to_screen(*b["pos"])
        if dry:
            print(f"[dry] would tap(pos) {name} at ({x}, {y})")
            return True
        self.device.tap(x, y)
        return True

    def wait_for(self, name: str, timeout: float = 20.0,
                 poll: float = 0.7, threshold: float | None = None):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.capture()
            hit = self.find(name, threshold)
            if hit is not None:
                return hit
            time.sleep(poll)
        return None
