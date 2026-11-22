"""ADB wrapper for one emulator instance."""
import subprocess
import threading
import time

import cv2
import numpy as np

from .config import (
    CREATE_NO_WINDOW, DEFAULT_INDEX, DEFAULT_SERIAL, adb_path, serial_for_index,
)

class Device:
    def __init__(self, serial: str | None = None, index: int | None = None):
        if serial and index is not None:
            raise ValueError("pass either serial or index, not both")
        if index is not None:
            serial = serial_for_index(index)
        self.serial = serial or DEFAULT_SERIAL
        self._input_lock = threading.Lock()

    def _run(self, *args: str, binary: bool = False,
             timeout: float = 20.0) -> bytes | str:
        cmd = [str(adb_path()), "-s", self.serial, *args]
        try:
            result = subprocess.run(
                cmd, capture_output=True, creationflags=CREATE_NO_WINDOW,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"adb {' '.join(args)} timed out after {timeout}s")
        if result.returncode != 0:
            raise RuntimeError(
                f"adb {' '.join(args)} failed: {result.stderr.decode(errors='replace')}"
            )
        return result.stdout if binary else result.stdout.decode(errors="replace")

    def connect(self, timeout: float = 60.0, should_stop=None) -> None:
        stop = should_stop or (lambda: False)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if stop():
                raise RuntimeError(f"ยกเลิกการเชื่อมต่อ {self.serial}")
            try:
                subprocess.run(
                    [str(adb_path()), "connect", self.serial],
                    capture_output=True, creationflags=CREATE_NO_WINDOW,
                    timeout=15,
                )
            except subprocess.TimeoutExpired:
                pass
            try:
                if self._run("shell", "getprop", "sys.boot_completed").strip() == "1":
                    return
            except RuntimeError:
                pass
            for _ in range(20):
                if stop():
                    raise RuntimeError(f"ยกเลิกการเชื่อมต่อ {self.serial}")
                time.sleep(0.1)
        raise TimeoutError(f"Device {self.serial} did not become ready in {timeout}s")

    def screenshot(self) -> np.ndarray:
        png = self._run("exec-out", "screencap", "-p", binary=True)
        img = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("Failed to decode screenshot (empty or corrupt PNG)")
        return img

    def foreground_package(self) -> str:
        try:
            out = self._run("shell", "dumpsys window | grep mCurrentFocus", timeout=10)
        except RuntimeError:
            return ""
        text = str(out)
        if "/" not in text:
            return ""
        return text.rsplit(" ", 1)[-1].split("/", 1)[0].strip()

    def app_in_front(self, package: str) -> bool:
        return self.foreground_package() == package

    def launch_activity(self, package: str) -> str:
        try:
            out = self._run("shell", "cmd", "package", "resolve-activity",
                            "--brief", package, timeout=15)
        except RuntimeError:
            return ""
        for line in reversed(str(out).splitlines()):
            line = line.strip()
            if line.startswith(package + "/"):
                return line
        return ""

    def launch_app(self, package: str) -> None:
        activity = self.launch_activity(package)
        if activity:
            try:
                self._run("shell", "am", "start", "-n", activity, timeout=30)
                return
            except RuntimeError:
                pass
        self._run("shell", "monkey", "-p", package,
                  "-c", "android.intent.category.LAUNCHER", "1", timeout=30)

    def tap(self, x: int, y: int) -> None:
        with self._input_lock:
            self._run("shell", "input", "tap", str(int(x)), str(int(y)))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        with self._input_lock:
            self._run(
                "shell", "input", "swipe",
                str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(duration_ms),
            )

    def key(self, keycode: str) -> None:
        with self._input_lock:
            self._run("shell", "input", "keyevent", keycode)

    def text(self, body: str) -> None:
        quoted = str(body or "").replace("'", "'\\''")
        with self._input_lock:
            self._run("shell", f"input text '{quoted}'")

def add_device_args(parser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--index", type=int, default=None,
                       help="LDPlayer instance index (0, 1, 2, ...)")
    group.add_argument("--serial", type=str, default=None,
                       help="explicit adb serial, e.g. 127.0.0.1:5555")

def device_from_args(args) -> "Device":
    if getattr(args, "serial", None):
        return Device(serial=args.serial)
    if getattr(args, "index", None) is not None:
        return Device(index=args.index)
    return Device(index=DEFAULT_INDEX)
