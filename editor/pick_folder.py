"""Folder picker subprocess for the flow editor."""
import tkinter as tk
from tkinter import filedialog

def main() -> None:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        chosen = filedialog.askdirectory(
            title="เลือกโฟลเดอร์ LDPlayer (ที่มี ldconsole.exe)")
    finally:
        root.destroy()
    print(chosen or "")

if __name__ == "__main__":
    main()
