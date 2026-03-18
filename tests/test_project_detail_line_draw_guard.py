from pathlib import Path
import unittest


class ProjectDetailLineDrawGuardTests(unittest.TestCase):
    def test_anchor_mousedown_is_not_intercepted_by_connection_selection(self):
        template_path = Path("app/templates/project_detail.html")
        content = template_path.read_text(encoding="utf-8")

        listener_start = content.index("document.addEventListener('mousedown', function (event) {")
        listener_end = content.index("document.addEventListener('mouseup', function (event) {", listener_start)
        listener_block = content[listener_start:listener_end]

        expected_guard = "if (event.target.closest('.anchor-in, .anchor-out')) {\n                return;\n            }"
        self.assertIn(expected_guard, listener_block)


if __name__ == "__main__":
    unittest.main()
