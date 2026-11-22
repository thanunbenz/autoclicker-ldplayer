"""Paths, JSON settings, and button/template metadata."""

import json
import os
import sys
import time
from pathlib import Path

def _base_dirs() -> tuple[Path, Path]:
    if getattr(sys, "frozen", False):
        data = Path(sys.executable).resolve().parent
        bundle = Path(getattr(sys, "_MEIPASS", data))
        return data, bundle
    root = Path(__file__).resolve().parent.parent
    return root / "data", root / "data"

DATA_ROOT, BUNDLE_ROOT = _base_dirs()
PROJECT_ROOT = Path(__file__).resolve().parent.parent

LOG_DETAIL = not getattr(sys, "frozen", False)
TEMPLATES_DIR = DATA_ROOT / "templates"
CONFIG_DIR = DATA_ROOT / "config"
BUTTONS_FILE = CONFIG_DIR / "buttons.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
AUTOFIT_FILE = CONFIG_DIR / "autofit.json"

BUTTONS_META_KEY = "_meta"
DEFAULT_BASE_RESOLUTION = (1600, 900)

def enable_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

SEEDED_FILE = CONFIG_DIR / ".seeded.json"
SEED_DIRS = ("templates", "config")

def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()

def _read_seeded() -> dict:
    try:
        data = read_json(SEEDED_FILE, {})
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def ensure_data_files() -> dict:
    if not getattr(sys, "frozen", False):
        return {"added": 0, "updated": 0, "kept": 0}
    import shutil

    was = _read_seeded()
    now = {}
    added = updated = kept = 0
    for sub in SEED_DIRS:
        src_root = BUNDLE_ROOT / sub
        if not src_root.exists():
            continue
        for src in src_root.rglob("*"):
            if not src.is_file():
                continue
            rel = f"{sub}/{src.relative_to(src_root).as_posix()}"
            shipped = _sha256(src)
            now[rel] = shipped
            dst = DATA_ROOT / sub / src.relative_to(src_root)
            if dst.exists():
                if _sha256(dst) == shipped:
                    continue
                if was.get(rel) and _sha256(dst) != was[rel]:
                    kept += 1
                    now[rel] = was[rel]
                    continue
                if not was.get(rel):
                    kept += 1
                    now[rel] = _sha256(dst)
                    continue
            existed = dst.exists()
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            except OSError:
                now.pop(rel, None)
                continue
            updated += 1 if existed else 0
            added += 0 if existed else 1
    try:
        write_json(SEEDED_FILE, dict(sorted(now.items())), indent=1)
    except OSError:
        pass
    return {"added": added, "updated": updated, "kept": kept}

WRITE_RETRIES = 6
READ_RETRIES = 3

def write_json(path: Path, data, indent: int = 2, ensure_ascii: bool = False) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
    except OSError:
        return False
    for attempt in range(WRITE_RETRIES):
        try:
            os.replace(tmp, path)
            return True
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
        except OSError:
            break
    try:
        path.write_text(text, encoding="utf-8")
        return True
    except OSError:
        return False
    finally:
        tmp.unlink(missing_ok=True)

def read_json(path: Path, default=None):
    if not path.exists():
        return default
    for attempt in range(READ_RETRIES):
        try:
            text = path.read_text(encoding="utf-8")
            if text.strip():
                return json.loads(text)
        except (ValueError, OSError):
            pass
        if attempt < READ_RETRIES - 1:
            time.sleep(0.05)
    return default

def read_buttons_file() -> tuple[dict, dict]:
    data = read_json(BUTTONS_FILE) if BUTTONS_FILE.exists() else None
    if not isinstance(data, dict):
        from . import assets
        raw = assets.buttons_bytes()
        if raw is None:
            return {}, {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            return {}, {}
        if not isinstance(data, dict):
            return {}, {}
    meta = data.get(BUTTONS_META_KEY)
    buttons = {k: v for k, v in data.items() if not k.startswith("_")}
    return buttons, meta if isinstance(meta, dict) else {}

def write_buttons_file(buttons: dict, meta: dict | None = None) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if meta:
        data[BUTTONS_META_KEY] = meta
    data.update({k: v for k, v in buttons.items() if not k.startswith("_")})
    write_json(BUTTONS_FILE, data)

def base_resolution(meta: dict | None = None) -> tuple[int, int]:
    if meta is None:
        _, meta = read_buttons_file()
    res = (meta or {}).get("base_resolution")
    if isinstance(res, (list, tuple)) and len(res) == 2:
        try:
            return int(res[0]), int(res[1])
        except (TypeError, ValueError):
            pass
    return DEFAULT_BASE_RESOLUTION

def read_autofit() -> dict:
    if not AUTOFIT_FILE.exists():
        return {}
    try:
        data = read_json(AUTOFIT_FILE, {})
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}

def write_autofit(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        write_json(AUTOFIT_FILE, data)
    except OSError:
        pass

_LDPLAYER_CANDIDATES = [
    r"C:\LDPlayer\LDPlayer14",
    r"C:\LDPlayer\LDPlayer9",
    r"C:\LDPlayer\LDPlayer64",
    r"C:\leidian\LDPlayer9",
    r"D:\LDPlayer\LDPlayer9",
    r"D:\LDPlayer\LDPlayer14",
    r"C:\Program Files\LDPlayer9",
]

ADB_BASE_PORT = 5555
DEFAULT_INDEX = 0

CREATE_NO_WINDOW = 0x08000000

def serial_for_index(index: int) -> str:
    return f"127.0.0.1:{ADB_BASE_PORT + index * 2}"

DEFAULT_SERIAL = serial_for_index(DEFAULT_INDEX)

def _is_ldplayer_dir(path: Path) -> bool:
    return (path / "adb.exe").exists() and (path / "ldconsole.exe").exists()

def find_ldplayer_dirs() -> list[Path]:
    found = []
    for raw in _load_settings().get("ldplayer_dirs", []):
        p = Path(str(raw))
        if _is_ldplayer_dir(p) and p not in found:
            found.append(p)
    for cand in _LDPLAYER_CANDIDATES:
        p = Path(cand)
        if _is_ldplayer_dir(p) and p not in found:
            found.append(p)
    return found

def resolve_ldplayer_dir(path) -> Path | None:
    p = Path(str(path)).expanduser()
    if _is_ldplayer_dir(p):
        return p
    if _is_ldplayer_dir(p.parent):
        return p.parent
    try:
        for child in sorted(p.iterdir()):
            if child.is_dir() and _is_ldplayer_dir(child):
                return child
    except OSError:
        pass
    return None

def add_ldplayer_dir(path) -> Path | None:
    resolved = resolve_ldplayer_dir(path)
    if resolved is None:
        return None
    settings = _load_settings()
    saved = [str(d) for d in settings.get("ldplayer_dirs", [])]
    if str(resolved) not in saved:
        saved.insert(0, str(resolved))
    settings["ldplayer_dirs"] = saved
    settings["ldplayer_dir"] = str(resolved)
    write_json(SETTINGS_FILE, settings)
    return resolved

def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            got = read_json(SETTINGS_FILE, {})
            return got if isinstance(got, dict) else {}
        except (ValueError, OSError):
            return {}
    return {}

def get_ldplayer_dir() -> Path:
    saved = _load_settings().get("ldplayer_dir")
    if saved and _is_ldplayer_dir(Path(saved)):
        return Path(saved)
    detected = find_ldplayer_dirs()
    if detected:
        return detected[0]
    return Path(_LDPLAYER_CANDIDATES[0])

def set_ldplayer_dir(path) -> None:
    settings = _load_settings()
    settings["ldplayer_dir"] = str(path)
    write_json(SETTINGS_FILE, settings)

def _clean_indices(raw) -> list[int]:
    out = set()
    for v in raw or []:
        try:
            i = int(v)
        except (TypeError, ValueError):
            continue
        if i >= 0:
            out.add(i)
    return sorted(out)

def get_selected_screens() -> list[int] | None:
    raw = _load_settings().get("screens_selected")
    if not isinstance(raw, list):
        return None
    return _clean_indices(raw)

def set_selected_screens(indices) -> list[int]:
    clean = _clean_indices(indices)
    settings = _load_settings()
    settings["screens_selected"] = clean
    write_json(SETTINGS_FILE, settings)
    return clean

def adb_path() -> Path:
    return get_ldplayer_dir() / "adb.exe"

def ldconsole_path() -> Path:
    return get_ldplayer_dir() / "ldconsole.exe"

LDPLAYER_DIR = get_ldplayer_dir()
ADB = adb_path()
LDCONSOLE = ldconsole_path()
