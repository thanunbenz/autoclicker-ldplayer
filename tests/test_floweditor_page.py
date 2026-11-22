"""Tests that the Flow Editor page is one self-contained file."""
import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
PAGE = APP / "editor" / "flow.html"
EDITOR = APP / "editor" / "floweditor.py"

class SelfContainedPageTest(unittest.TestCase):
    def setUp(self):
        self.src = PAGE.read_text(encoding="utf-8")

    def test_no_external_stylesheets_or_scripts(self):
        self.assertIsNone(re.search(r'<link[^>]+rel="stylesheet"', self.src))
        self.assertIsNone(re.search(r'<script[^>]+src=', self.src))

    def test_no_parent_paths(self):
        for ref in ('href="../', 'src="../', 'url("../'):
            self.assertNotIn(ref, self.src)

    def test_style_and_script_are_inline(self):
        self.assertIn("<style>", self.src)
        self.assertIn("<script>", self.src)

    def test_fonts_are_local(self):
        self.assertIn('url("font/', self.src)
        self.assertIsNone(re.search(r'url\(\s*["\']?https?:', self.src))

    def test_every_url_resolves_next_to_the_page(self):
        for ref in re.findall(r'url\("([^"]+)"\)', self.src):
            self.assertTrue((PAGE.parent / ref).is_file(), ref)

    def test_editor_uses_plain_js_api_bridge(self):
        src = EDITOR.read_text(encoding="utf-8")
        self.assertIn("js_api=api", src)
        self.assertNotIn("start_global_server", src)
        self.assertNotIn("serve_webui_tree", src)
