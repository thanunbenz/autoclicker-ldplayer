"""OpenCV template matching."""
from pathlib import Path

import cv2
import numpy as np

from .config import TEMPLATES_DIR

def load_template(name: str) -> np.ndarray:
    path = TEMPLATES_DIR / name
    if path.is_file():
        tpl = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if tpl is not None:
            return tpl
    from . import assets
    data = assets.template_bytes(name)
    if data is not None:
        tpl = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if tpl is not None:
            return tpl
    raise FileNotFoundError(f"Template not found: {name}")

SCALE_EPS = 0.005

def resize_by(img: np.ndarray, factor: float) -> np.ndarray:
    if abs(factor - 1.0) < SCALE_EPS:
        return img
    h, w = img.shape[:2]
    size = (max(1, int(round(w * factor))), max(1, int(round(h * factor))))
    interp = cv2.INTER_AREA if factor < 1.0 else cv2.INTER_LINEAR
    return cv2.resize(img, size, interpolation=interp)

def _fits(screen: np.ndarray, tpl: np.ndarray) -> bool:
    return tpl.shape[0] <= screen.shape[0] and tpl.shape[1] <= screen.shape[1]

MIN_TEMPLATE_PX = 10

def match_at_scale(screen: np.ndarray, tpl: np.ndarray, factor: float,
                   region: tuple | None = None) -> tuple[float, tuple[int, int]]:
    scaled = resize_by(tpl, factor)
    if min(scaled.shape[:2]) < MIN_TEMPLATE_PX or not _fits(screen, scaled):
        return 0.0, (0, 0)
    crop, ox, oy = _crop(screen, region, scaled.shape)
    result = cv2.matchTemplate(crop, scaled, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    return float(max_val), (ox + max_loc[0], oy + max_loc[1])

def score_at_scale(screen: np.ndarray, tpl: np.ndarray, factor: float,
                   region: tuple | None = None) -> float:
    return match_at_scale(screen, tpl, factor, region)[0]

def _crop(screen: np.ndarray, region, tpl_shape) -> tuple[np.ndarray, int, int]:
    if region is None:
        return screen, 0, 0
    H, W = screen.shape[:2]
    th, tw = tpl_shape[:2]
    x, y, w, h = region
    x0 = max(0, min(int(x), W - tw))
    y0 = max(0, min(int(y), H - th))
    x1 = min(W, int(x) + int(w))
    y1 = min(H, int(y) + int(h))
    if x1 - x0 < tw or y1 - y0 < th:
        return screen, 0, 0
    return screen[y0:y1, x0:x1], x0, y0

def locate(
    screen: np.ndarray,
    template: np.ndarray | str,
    threshold: float = 0.85,
    region: tuple | None = None,
) -> tuple[int, int] | None:
    if isinstance(template, str):
        template = load_template(template)
    if not _fits(screen, template):
        return None
    crop, ox, oy = _crop(screen, region, template.shape)
    result = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    h, w = template.shape[:2]
    return ox + max_loc[0] + w // 2, oy + max_loc[1] + h // 2

def locate_all(screen: np.ndarray, tpl: np.ndarray, threshold: float = 0.75,
               scales: tuple = (1.0,), limit: int = 20) -> list:
    out = []
    for factor in scales:
        scaled = resize_by(tpl, factor)
        if min(scaled.shape[:2]) < MIN_TEMPLATE_PX or not _fits(screen, scaled):
            continue
        h, w = scaled.shape[:2]
        result = cv2.matchTemplate(screen, scaled, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= threshold)
        for x, y in zip(xs.tolist(), ys.tolist()):
            out.append((float(result[y][x]), int(x), int(y), w, h))
    return suppress_overlaps(out, limit=limit)

OVERLAP_MAX = 0.3

def suppress_overlaps(hits: list, limit: int = 20) -> list:
    kept = []
    for hit in sorted(hits, key=lambda h: -h[0]):
        _, x, y, w, h = hit
        if any(_overlap((x, y, w, h), k[1:]) > OVERLAP_MAX for k in kept):
            continue
        kept.append(hit)
        if len(kept) >= limit:
            break
    return kept

def _overlap(a: tuple, b: tuple) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    if not inter:
        return 0.0
    return inter / max(1, min(aw * ah, bw * bh))

def match_score(screen: np.ndarray, template: np.ndarray | str,
                region: tuple | None = None) -> float:
    if isinstance(template, str):
        template = load_template(template)
    if not _fits(screen, template):
        return 0.0
    crop, _ox, _oy = _crop(screen, region, template.shape)
    result = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    return float(max_val)
