"""Tests for template loading."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import vision as V

class LoadTemplateTest(unittest.TestCase):
    def setUp(self):
        self._imread = V.cv2.imread
        self.reads = []
        V.cv2.imread = lambda p, *a, **k: (self.reads.append(p),
                                           self._imread(p, *a, **k))[1]

    def tearDown(self):
        V.cv2.imread = self._imread

    def test_does_not_touch_imread_when_the_file_is_absent(self):
        with self.assertRaises(FileNotFoundError):
            V.load_template("ไม่มีไฟล์นี้แน่นอน_zzz.png")
        self.assertEqual(self.reads, [], f"ยังเรียก imread อยู่: {self.reads}")

    def test_still_reads_real_files_from_disk(self):
        import tempfile

        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "fixture.png").write_bytes(b"")
            cv2.imwrite(str(Path(tmp, "fixture.png")),
                        np.zeros((8, 8, 3), dtype=np.uint8))
            old = V.TEMPLATES_DIR
            V.TEMPLATES_DIR = Path(tmp)
            try:
                img = V.load_template("fixture.png")
            finally:
                V.TEMPLATES_DIR = old
        self.assertIsNotNone(img)
        self.assertEqual(len(self.reads), 1, "ไม่ได้อ่านจากดิสก์ทั้งที่ไฟล์มี")

    def test_orphan_buttons_have_no_missing_template(self):
        from bot import config as C
        buttons, _meta = C.read_buttons_file()
        missing = []
        for name, b in buttons.items():
            f = (b or {}).get("template") if isinstance(b, dict) else None
            if f and not (C.TEMPLATES_DIR / f).is_file():
                missing.append(f"{name} -> {f}")
        self.assertEqual(missing, [], "ปุ่มที่ไม่มีรูป: " + ", ".join(missing))

if __name__ == "__main__":
    unittest.main()
