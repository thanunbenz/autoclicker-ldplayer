"""LDPlayer console commands."""
import subprocess

from .config import (
    CREATE_NO_WINDOW, adb_path, ldconsole_path, serial_for_index,
)

def _ld(*args: str, timeout: float = 15.0):
    try:
        result = subprocess.run(
            [str(ldconsole_path()), *args],
            capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, ""
    return result.returncode == 0, result.stdout.decode(errors="replace")

def adb_devices() -> list[str]:
    try:
        result = subprocess.run(
            [str(adb_path()), "devices"],
            capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return []
    serials = []
    for line in result.stdout.decode(errors="replace").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) == 2 and parts[1].strip() == "device":
            serials.append(parts[0].strip())
    return serials

def _wm_size(serial: str) -> str | None:
    try:
        result = subprocess.run(
            [str(adb_path()), "-s", serial, "shell", "wm", "size"],
            capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=8,
        )
    except subprocess.TimeoutExpired:
        return None
    text = result.stdout.decode(errors="replace")
    for line in text.splitlines():
        if ":" in line and "x" in line:
            val = line.split(":", 1)[1].strip()
            if "x" in val:
                return val
    return None

def list_instances() -> list[dict]:
    ok, out = _ld("list2")
    if not ok and not out:
        return []
    live = set(adb_devices())
    instances = []
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) < 6 or not parts[0].strip().isdigit():
            continue
        index = int(parts[0])
        serial = serial_for_index(index)
        running = (
            parts[4] == "1"
            or parts[5].strip() not in ("-1", "")
            or serial in live
            or f"emulator-{5554 + index * 2}" in live
        )
        resolution = ",".join(parts[-3:]) if len(parts) >= 9 else "?"
        if running:
            actual = _wm_size(serial) or (
                _wm_size(f"emulator-{5554 + index * 2}") if serial not in live else None
            )
            if actual:
                resolution = actual
        instances.append({
            "index": index,
            "name": parts[1],
            "running": running,
            "resolution": resolution,
            "serial": serial,
        })
    return instances

def is_instance_running(index: int) -> bool:
    return any(i["index"] == index and i["running"] for i in list_instances())

def launch_instance(index: int) -> None:
    _ld("launch", "--index", str(index), timeout=30)

def quit_instance(index: int) -> None:
    _ld("quit", "--index", str(index), timeout=30)

def set_resolution(index: int, width: int, height: int, dpi: int = 240) -> bool:
    ok, _ = _ld("modify", "--index", str(index),
                "--resolution", f"{width},{height},{dpi}", timeout=30)
    return ok

def restart_instance(index: int) -> None:
    quit_instance(index)
    launch_instance(index)
