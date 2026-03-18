from pathlib import Path
import unittest


class ProjectDetailShiftMultiselectTests(unittest.TestCase):
    def test_project_detail_contains_shift_multiselect_markers(self):
        content = Path("app/templates/project_detail.html").read_text(encoding="utf-8")

        self.assertIn('onclick="selectModule(this, event)"', content)
        self.assertIn('let selectedModuleIds = new Set();', content)
        self.assertIn('let isShiftSelectionActive = false;', content)
        self.assertIn('document.addEventListener(\'keydown\'', content)
        self.assertIn('document.addEventListener(\'keyup\'', content)
        self.assertIn('const isMultiSelect = selectedModuleIds.size > 1;', content)
        self.assertIn("document.getElementById('detail-module-name').textContent = `已选中 ${selectedModuleIds.size} 个模块`", content)


if __name__ == "__main__":
    unittest.main()
