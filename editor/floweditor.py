"""Visual flow editor built on pywebview."""
import base64
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import webview

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot import config, flow as flowmod
from bot.bot import Bot
from bot.device import Device
from bot import ldconsole
from bot.ldconsole import list_instances

THUMB_BOX = (128, 96)
SCREEN_BOX = (900, 900)
JPEG_QUALITY = 82

UI_PREFS_FILE = config.CONFIG_DIR / "floweditor-ui.json"
WIN_DEFAULT = (1280, 860)
WIN_MIN = (1000, 700)
WIN_MAX = (6000, 4000)

FLOW_HTML = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "flow.html"

def _data_uri(img, box: tuple) -> str:
    h, w = img.shape[:2]
    f = min(1.0, box[0] / w, box[1] / h)
    if f < 1.0:
        img = cv2.resize(img, (max(1, int(w * f)), max(1, int(h * f))),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")

class Api:

    def __init__(self, index: int = 0):
        self._window = None
        self._index = index
        self._instances = []
        self._stop = threading.Event()
        self._running = False
        self._thread = None
        self._jump = flowmod.Jump()
        self._opened = WIN_DEFAULT

    def _js(self, fn: str, *args) -> None:
        if not self._window:
            return
        payload = ", ".join(json.dumps(a, ensure_ascii=False) for a in args)
        try:
            self._window.evaluate_js(f"window.{fn} && window.{fn}({payload})")
        except Exception:
            pass

    def _log(self, msg: str) -> None:
        self._js("pushLog", str(msg))

    def list_templates(self):
        buttons, _meta = config.read_buttons_file()
        out = []
        seen = set()
        for name, b in buttons.items():
            file = b.get("template")
            if not file:
                out.append({"name": name, "thumb": "", "w": 0, "h": 0,
                            "pos": b.get("pos"), "point_only": True})
                continue
            seen.add(file)
            out.append(self._template_entry(name, file, b.get("pos")))
        tdir = config.TEMPLATES_DIR
        if tdir.exists():
            for p in sorted(tdir.glob("*.png")):
                if p.name not in seen and p.stem not in buttons:
                    out.append(self._template_entry(p.stem, p.name, None))
        out.sort(key=lambda e: e["name"].lower())
        return out

    def _template_entry(self, name, file, pos):
        img = cv2.imread(str(config.TEMPLATES_DIR / file), cv2.IMREAD_COLOR)
        if img is None:
            return {"name": name, "thumb": "", "w": 0, "h": 0, "pos": pos,
                    "missing": True}
        h, w = img.shape[:2]
        return {"name": name, "thumb": _data_uri(img, THUMB_BOX),
                "w": w, "h": h, "pos": pos}

    def get_instances(self):
        try:
            self._instances = list_instances()
        except Exception as e:
            self._log(f"อ่านรายชื่อจอไม่ได้: {e}")
            self._instances = []
        return [{**i, "label": f"{'●' if i['running'] else '○'} {i['index']}: {i['name']}"}
                for i in self._instances]

    def get_ldplayer(self):
        dirs = config.find_ldplayer_dirs()
        current = config.get_ldplayer_dir()
        if current not in dirs and config._is_ldplayer_dir(current):
            dirs = [current, *dirs]
        return {"current": str(current), "dirs": [str(d) for d in dirs]}

    def set_ldplayer_dir(self, path):
        config.set_ldplayer_dir(path)
        self._log(f"LDPlayer -> {path}")
        return {"ok": True, "instances": self.get_instances()}

    def pick_ldplayer_dir(self):
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--pick-folder"]
        else:
            picker = str(Path(__file__).resolve().parent / "pick_folder.py")
            cmd = [sys.executable, picker, "--pick-folder"]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=300)
            lines = out.stdout.decode(errors="replace").strip().splitlines()
            path = lines[-1].strip() if lines else ""
        except Exception:
            path = ""
        if not path:
            return {"ok": False}
        resolved = config.add_ldplayer_dir(path)
        if resolved is None:
            self._log(f"ไม่ใช่โฟลเดอร์ LDPlayer: {path}")
            return {"ok": False, "error": "ไม่ใช่โฟลเดอร์ LDPlayer"}
        self._log(f"ใช้ LDPlayer ที่ {resolved}")
        return {"ok": True, "path": str(resolved),
                "ld": self.get_ldplayer(), "instances": self.get_instances()}

    def restart_instance(self, index):
        index = int(index)
        if self._running and self._thread and self._thread.is_alive():
            return {"ok": False, "error": "flow กำลังรันอยู่ - กดหยุดก่อน"}
        threading.Thread(target=self._restart_instance, args=(index,),
                         daemon=True).start()
        return {"ok": True}

    def _restart_instance(self, index):
        self._log(f"ปิดจอ {index} ...")
        ldconsole.quit_instance(index)
        time.sleep(2)
        self._log(f"เปิดจอ {index} ใหม่ ...")
        ldconsole.launch_instance(index)
        try:
            Device(index=index).connect(timeout=180, should_stop=self._stop.is_set)
            self._log(f"จอ {index} พร้อมใช้งานแล้ว ✓")
        except Exception as e:
            self._log(f"จอ {index} เปิดแล้วแต่ยังต่อ adb ไม่ได้: {e}")
        self._js("reloadInstancesFromPy")

    def get_ui_prefs(self):
        got = config.read_json(UI_PREFS_FILE, {})
        out = dict(got) if isinstance(got, dict) else {}
        out["open_w"], out["open_h"] = self._opened
        return out

    def set_ui_prefs(self, prefs):
        if not isinstance(prefs, dict):
            return False
        return bool(config.write_json(UI_PREFS_FILE, prefs))

    def get_meta(self):
        w, h = config.base_resolution()
        return {"actions": {k: {"label": v[0], "fields": v[1]}
                            for k, v in flowmod.ACTIONS.items()},
                "nested": list(flowmod.NESTED_ACTIONS),
                "note_labels": dict(flowmod.NOTE_LABELS),
                "base": {"w": w, "h": h},
                "default_index": self._index}

    def list_flows(self):
        return flowmod.list_flows()

    def load_flow(self, name):
        return flowmod.load_flow(name).to_dict()

    def save_flow(self, data):
        try:
            f = flowmod.from_dict(data or {})
            if not (data or {}).get("name"):
                return {"ok": False, "error": "ตั้งชื่อ flow ก่อน"}
            flowmod.save_flow(f)
        except (OSError, TypeError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        self._log(f"บันทึก flow '{f.name}' ({len(f.steps)} ขั้นตอน)")
        warnings = flowmod.unreachable_choices(f)
        for w in warnings:
            self._log(f"⚠ ขั้น {w['no']} ตั้งไว้ {w['count']} อย่างแต่ยังไม่มีกลุ่ม"
                      f" · ผู้ใช้จะไม่เห็นรายการติ๊กของขั้นนี้")
        return {"ok": True, "name": f.name, "flows": flowmod.list_flows(),
                "warnings": warnings}

    def flow_warnings(self, data):
        return {"unreachable": flowmod.unreachable_choices(
            flowmod.from_dict(data or {}))}

    def restore_flow(self, name):
        if not flowmod.restore_flow(name):
            self._log(f"ไม่มีสำรองของ '{name}'")
            return {"ok": False, "error": "ไม่มีไฟล์สำรอง"}
        self._log(f"กู้คืน '{name}' จากไฟล์สำรองแล้ว")
        return {"ok": True, "flow": flowmod.load_flow(name).to_dict()}

    def delete_flow(self, name):
        flowmod.delete_flow(name)
        self._log(f"ลบ flow '{name}'")
        return {"ok": True, "flows": flowmod.list_flows()}

    def _connect(self, index):
        device = Device(index=int(index))
        device.connect(timeout=60, should_stop=self._stop.is_set)
        return Bot(device, log=self._log)

    def capture(self, index):
        try:
            screen = Device(index=int(index)).screenshot()
        except Exception as e:
            self._log(f"จับภาพไม่สำเร็จ: {e}")
            return {"ok": False, "error": str(e)}
        h, w = screen.shape[:2]
        return {"ok": True, "img": _data_uri(screen, SCREEN_BOX),
                "w": w, "h": h}

    def probe(self, index, names):
        try:
            bot = self._connect(index)
            bot.capture()
        except Exception as e:
            self._log(f"เชื่อมต่อไม่สำเร็จ: {e}")
            return {"ok": False, "error": str(e)}
        scores = {}
        for name in (names or []):
            if name and name in bot.buttons:
                scores[name] = round(bot.score(name), 3)
        return {"ok": True, "scores": scores, "threshold": bot.threshold}

    def run_flow(self, data, index, loops=1):
        if self._running and not (self._thread and self._thread.is_alive()):
            self._running = False
        if self._running:
            return {"ok": False, "error": "กำลังรันอยู่ (กด หยุด ก่อน)"}
        parsed = flowmod.from_dict(data or {})
        steps = parsed.steps
        if not steps:
            return {"ok": False, "error": "ยังไม่มีขั้นตอน"}
        parsed.clamp_jump()
        self._jump = parsed.jump
        self._stop.clear()
        self._running = True
        self._js("pushRunState", True)
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        args=(steps, int(index), int(loops)))
        self._thread.start()
        return {"ok": True}

    def _run(self, steps, index, loops):
        self._log(f"เชื่อมต่อ instance {index} ... (จอต้องเปิดอยู่และเปิด ADB debugging)")
        try:
            bot = self._connect(index)
        except Exception as e:
            self._log(f"เชื่อมต่อ instance {index} ไม่สำเร็จ: {e}")
            self._running = False
            self._js("pushRunState", False)
            return
        try:
            flowmod.FlowRunner(
                bot, steps,
                log=self._log,
                on_step=lambda i, st: self._js("pushStep", i, st),
                should_stop=self._stop.is_set,
                loops=loops,
                jump=self._jump,
                on_fail=lambda info: self._capture_failure(bot, info),
            ).run()
        except Exception as e:
            self._log(f"flow ล้ม: {e}")
        finally:
            self._running = False
            self._js("pushRunState", False)

    def _capture_failure(self, bot, info):
        screen = getattr(bot, "_screen", None)
        if screen is None:
            self._log("(ไม่มีภาพจอให้เก็บ · ยังไม่ได้จับภาพเลยสักครั้ง)")
            return
        info = dict(info)
        try:
            logs = config.DATA_ROOT / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = logs / f"flow-stop-{stamp}-step{info.get('no', '?')}.png"
            cv2.imwrite(str(path), screen)
            info["file"] = str(path)
            self._log(f"เก็บภาพหน้าที่หยุดไว้ที่ {path}")
        except OSError as e:
            self._log(f"เซฟภาพไม่ได้: {e}")
        info["img"] = _data_uri(screen, SCREEN_BOX)
        self._js("pushFail", info)

    def stop_flow(self):
        self._stop.set()
        if not (self._thread and self._thread.is_alive()):
            self._running = False
            self._js("pushRunState", False)
            self._log("ไม่มีงานที่กำลังรัน - ปลดล็อกปุ่มแล้ว")
        else:
            self._log("กำลังหยุด ...")
        return {"ok": True}

    def open_calibrator(self, index):
        script = str(Path(__file__).resolve().parent / "calibrate_gui.py")
        subprocess.Popen([sys.executable, script, "--index", str(int(index))])
        self._log(f"เปิดตัวคาลิเบรต (จอ {index})")
        return {"ok": True}

def _remembered_size() -> tuple:
    prefs = config.read_json(UI_PREFS_FILE, {})
    if not isinstance(prefs, dict):
        return WIN_DEFAULT
    out = []
    for key, frame, default, low, high in (
        ("winW", "frameW", WIN_DEFAULT[0], WIN_MIN[0], WIN_MAX[0]),
        ("winH", "frameH", WIN_DEFAULT[1], WIN_MIN[1], WIN_MAX[1]),
    ):
        try:
            value = int(prefs[key]) + int(prefs.get(frame) or 0)
        except (KeyError, TypeError, ValueError):
            value = default
        out.append(max(low, min(high, value)))
    return tuple(out)

def main():
    argv = sys.argv[1:]
    index = 0
    if "--index" in argv:
        try:
            index = int(argv[argv.index("--index") + 1])
        except (ValueError, IndexError):
            index = 0
    config.ensure_data_files()
    api = Api(index)
    api._opened = _remembered_size()
    window = webview.create_window(
        "Flow Editor",
        str(FLOW_HTML),
        js_api=api,
        width=api._opened[0], height=api._opened[1], min_size=WIN_MIN,
        background_color="#241a12",
    )
    api._window = window
    webview.start()

if __name__ == "__main__":
    main()
