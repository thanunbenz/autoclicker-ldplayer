"""Load sealed assets from pack.bin when present."""
from pathlib import Path

from .config import BUNDLE_ROOT, DATA_ROOT

BUNDLED_DIR = "assets"
PACK_NAME = "pack.bin"

K_BUTTONS = "buttons.json"
K_FLOW_PREFIX = "flow/"
K_TPL_PREFIX = "tpl/"

_cache: dict | None = None

def _key() -> bytes:
    from . import vault
    from .version import APP_NAME
    salt = bytes((0x3d, 0xa8, 0x11, 0x6c, 0xf2, 0x4b, 0x90, 0x57))
    return vault.derive(APP_NAME.encode(), BUNDLED_DIR.encode(), salt,
                        (900).to_bytes(2, "big"))

def _pack_path() -> Path | None:
    for folder in (DATA_ROOT / BUNDLED_DIR, BUNDLE_ROOT / BUNDLED_DIR):
        p = folder / PACK_NAME
        if p.exists():
            return p
    return None

def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    p = _pack_path()
    if p is None:
        _cache = {}
        return _cache
    try:
        from . import vault
        _cache = vault.unpack(p.read_bytes(), _key())
    except Exception:
        _cache = {}
    return _cache

def available() -> bool:
    return bool(_load())

def clear_cache() -> None:
    global _cache
    _cache = None

def buttons_bytes() -> bytes | None:
    return _load().get(K_BUTTONS)

def template_bytes(filename: str) -> bytes | None:
    return _load().get(K_TPL_PREFIX + filename)

def template_names() -> list[str]:
    n = len(K_TPL_PREFIX)
    return [k[n:] for k in _load() if k.startswith(K_TPL_PREFIX)]

def flow_bytes(name: str) -> bytes | None:
    return _load().get(K_FLOW_PREFIX + name + ".json")

def flow_names() -> list[str]:
    n = len(K_FLOW_PREFIX)
    return sorted(k[n:-5] for k in _load()
                  if k.startswith(K_FLOW_PREFIX) and k.endswith(".json"))
