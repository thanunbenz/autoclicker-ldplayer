"""Tkinter tool for cropping button templates."""
import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import simpledialog, ttk

import cv2
from PIL import Image, ImageTk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot.config import (
    TEMPLATES_DIR, base_resolution, read_buttons_file, write_buttons_file,
)
from bot.device import Device, add_device_args
from bot.ldconsole import list_instances
from bot.vision import resize_by

MAX_W, MAX_H = 1000, 620
DRAG_THRESHOLD = 6

class CalibratorGUI:
    def __init__(self, root: tk.Tk, initial_index: int | None = None):
        self.root = root
        self.device = None
        self.instances = []
        self.screen = None
        self.scale = 1.0
        self.photo = None
        self.buttons = {}
        self.drag_start = None
        self.rect_id = None
        self.base_scale = 1.0

        self.buttons, self.meta = read_buttons_file()
        self.base_w, self.base_h = base_resolution(self.meta)
        self.fresh = not self.buttons

        root.title("LDPlayer - Button Calibrator")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.canvas = tk.Canvas(root, bg="#222", cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        panel = ttk.Frame(root, padding=8)
        panel.grid(row=0, column=1, sticky="ns")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        ttk.Label(panel, text="Instance:").pack(anchor="w")
        self.instance_var = tk.StringVar()
        self.instance_box = ttk.Combobox(
            panel, textvariable=self.instance_var, state="readonly", width=24
        )
        self.instance_box.pack(fill="x")
        self.instance_box.bind("<<ComboboxSelected>>", self.on_instance_selected)
        ttk.Button(panel, text="Reload instances", command=self.reload_instances).pack(
            fill="x", pady=(2, 8)
        )

        ttk.Button(panel, text="Capture / Refresh", command=self.refresh).pack(fill="x")
        ttk.Label(panel, text="Buttons:").pack(anchor="w", pady=(10, 0))
        self.listbox = tk.Listbox(panel, width=26, height=16)
        self.listbox.pack(fill="both", expand=True)
        ttk.Button(panel, text="Test tap", command=self.test_tap).pack(fill="x", pady=(6, 0))
        ttk.Button(panel, text="Delete selected", command=self.delete_selected).pack(fill="x")
        ttk.Button(panel, text="Save", command=self.save).pack(fill="x", pady=(6, 0))
        self.status = ttk.Label(panel, text="", wraplength=190, foreground="#2a7")
        self.status.pack(anchor="w", pady=(8, 0))

        self.reload_instances(initial_index)

    def _label(self, inst: dict) -> str:
        state = "running" if inst["running"] else "stopped"
        return f"{inst['index']}: {inst['name']} [{state}]"

    def reload_instances(self, prefer_index: int | None = None):
        self.instances = list_instances()
        labels = [self._label(i) for i in self.instances]
        self.instance_box["values"] = labels
        if not self.instances:
            self.set_status("no instances found", ok=False)
            return
        pick = 0
        for n, inst in enumerate(self.instances):
            if prefer_index is not None and inst["index"] == prefer_index:
                pick = n
                break
        else:
            for n, inst in enumerate(self.instances):
                if inst["running"]:
                    pick = n
                    break
        self.instance_box.current(pick)
        self.select_instance(self.instances[pick])

    def on_instance_selected(self, _event=None):
        n = self.instance_box.current()
        if 0 <= n < len(self.instances):
            self.select_instance(self.instances[n])

    def select_instance(self, inst: dict):
        if not inst["running"]:
            self.device = None
            self.set_status(f"instance {inst['index']} is stopped · launch it first", ok=False)
            return
        self.set_status(f"connecting to {inst['serial']} ...")
        self.root.update_idletasks()
        device = Device(serial=inst["serial"])
        try:
            device.connect(timeout=60)
        except Exception as e:
            self.device = None
            self.set_status(f"connect failed: {e}", ok=False)
            return
        self.device = device
        self.root.title(f"LDPlayer - Button Calibrator  [{inst['index']}:{inst['name']}]")
        self.refresh()

    def to_device(self, x, y):
        return int(round(x / self.scale)), int(round(y / self.scale))

    def to_base(self, x, y):
        dx, dy = self.to_device(x, y)
        return int(round(dx / self.base_scale)), int(round(dy / self.base_scale))

    def base_to_display(self, x, y):
        f = self.base_scale * self.scale
        return x * f, y * f

    def set_status(self, msg, ok=True):
        self.status.config(text=msg, foreground="#2a7" if ok else "#c33")

    def refresh(self):
        if self.device is None:
            self.set_status("no instance connected · pick a running one", ok=False)
            return
        try:
            self.screen = self.device.screenshot()
        except Exception as e:
            self.set_status(f"screenshot failed: {e}", ok=False)
            return
        h, w = self.screen.shape[:2]
        self.scale = min(1.0, MAX_W / w, MAX_H / h)
        note = self._update_base(w, h)
        self.redraw()
        self.set_status(f"screen {w}x{h}{note}", ok="⚠" not in note)

    def _update_base(self, w: int, h: int) -> str:
        if self.fresh:
            self.base_w, self.base_h = w, h
        if (w, h) == (self.base_w, self.base_h):
            self.base_scale = 1.0
            return ""
        self.base_scale = h / self.base_h
        aspect_off = abs(w / h - self.base_w / self.base_h) > 0.03
        return (f"  ⚠ ปุ่มชุดนี้คาลิเบรตที่ {self.base_w}x{self.base_h} · "
                f"ที่เพิ่มใหม่จะถูกแปลงกลับ (x{1 / self.base_scale:.3f})"
                + ("  สัดส่วนจอต่างกัน อาจเพี้ยน" if aspect_off else ""))

    def redraw(self):
        rgb = cv2.cvtColor(self.screen, cv2.COLOR_BGR2RGB)
        disp = cv2.resize(rgb, None, fx=self.scale, fy=self.scale)
        img = Image.fromarray(disp)
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.config(width=img.width, height=img.height)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        for name, b in self.buttons.items():
            if not b.get("pos"):
                continue
            px, py = self.base_to_display(*b["pos"])
            if b.get("rect"):
                x, y, w, h = b["rect"]
                x0, y0 = self.base_to_display(x, y)
                x1, y1 = self.base_to_display(x + w, y + h)
                self.canvas.create_rectangle(x0, y0, x1, y1,
                                             outline="#ffb400", width=1)
            self.canvas.create_line(px - 7, py, px + 7, py, fill="#ff3030", width=2)
            self.canvas.create_line(px, py - 7, px, py + 7, fill="#ff3030", width=2)
            self.canvas.create_text(px + 6, py - 8, text=name, anchor="w",
                                    fill="#ff3030", font=("Segoe UI", 9, "bold"))
        self.refresh_list()

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        for name, b in self.buttons.items():
            tag = "[tpl]" if b.get("template") else "[pt]"
            self.listbox.insert(tk.END, f"{tag} {name}")

    def on_press(self, ev):
        self.drag_start = (ev.x, ev.y)
        self.rect_id = None

    def on_motion(self, ev):
        if not self.drag_start:
            return
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            *self.drag_start, ev.x, ev.y, outline="#30ff30", width=1
        )

    def on_release(self, ev):
        if not self.drag_start:
            return
        start, self.drag_start = self.drag_start, None
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.rect_id = None
        moved = abs(ev.x - start[0]) + abs(ev.y - start[1])
        if moved < DRAG_THRESHOLD:
            self.add_point(ev.x, ev.y)
        else:
            self.add_region(start, (ev.x, ev.y))

    def ask_name(self, kind):
        name = simpledialog.askstring("Name", f"Name for this {kind}:", parent=self.root)
        if name:
            name = name.strip()
        if not name:
            return None
        if name in self.buttons and self.buttons[name].get("template"):
            (TEMPLATES_DIR / self.buttons[name]["template"]).unlink(missing_ok=True)
        return name

    def add_point(self, dx, dy):
        x, y = self.to_base(dx, dy)
        name = self.ask_name("tap point")
        if not name:
            return
        self.buttons[name] = {"pos": [x, y], "template": None, "rect": None}
        self.redraw()
        self.set_status(f"added '{name}' -> tap ({x}, {y})")

    def add_region(self, d0, d1):
        x0, y0 = self.to_device(*d0)
        x1, y1 = self.to_device(*d1)
        x, y, w, h = min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)
        if w < 4 or h < 4:
            return
        name = self.ask_name("template region")
        if not name:
            return
        crop = resize_by(self.screen[y:y + h, x:x + w], 1.0 / self.base_scale)
        bx, by = self.to_base(*d0)
        bx1, by1 = self.to_base(*d1)
        rx, ry = min(bx, bx1), min(by, by1)
        rw, rh = crop.shape[1], crop.shape[0]
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(TEMPLATES_DIR / f"{name}.png"), crop)
        self.buttons[name] = {"pos": [rx + rw // 2, ry + rh // 2],
                              "template": f"{name}.png", "rect": [rx, ry, rw, rh]}
        self.redraw()
        self.set_status(f"added '{name}' -> template ({rw}x{rh} @ base)")

    def selected_name(self):
        sel = self.listbox.curselection()
        if not sel:
            return None
        return self.listbox.get(sel[0]).split(" ", 1)[1]

    def test_tap(self):
        if self.device is None:
            self.set_status("no instance connected", ok=False)
            return
        name = self.selected_name()
        if not name:
            self.set_status("select a button first", ok=False)
            return
        pos = self.buttons[name].get("pos")
        if not pos:
            self.set_status(f"'{name}' has no tap point", ok=False)
            return
        x = int(round(pos[0] * self.base_scale))
        y = int(round(pos[1] * self.base_scale))
        try:
            self.device.tap(x, y)
            self.set_status(f"tapped '{name}' ({x}, {y}) · Refresh to see result")
        except Exception as e:
            self.set_status(f"tap failed: {e}", ok=False)

    def delete_selected(self):
        name = self.selected_name()
        if not name:
            return
        b = self.buttons.pop(name)
        if b.get("template"):
            (TEMPLATES_DIR / b["template"]).unlink(missing_ok=True)
        self.redraw()
        self.set_status(f"deleted '{name}'")

    def save(self):
        if not self.buttons:
            return
        meta = dict(self.meta)
        meta["base_resolution"] = [self.base_w, self.base_h]
        write_buttons_file(self.buttons, meta)
        self.meta = meta
        self.fresh = False
        self.set_status(f"saved {len(self.buttons)} buttons "
                        f"@ {self.base_w}x{self.base_h}")

    def on_close(self):
        self.save()
        self.root.destroy()

def main():
    parser = argparse.ArgumentParser(description="Button calibrator GUI")
    add_device_args(parser)
    args = parser.parse_args()
    initial_index = args.index if getattr(args, "index", None) is not None else None

    root = tk.Tk()
    CalibratorGUI(root, initial_index=initial_index)
    root.mainloop()

if __name__ == "__main__":
    main()
