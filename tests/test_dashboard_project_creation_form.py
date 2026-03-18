from pathlib import Path
import unittest


class DashboardProjectCreationFormTests(unittest.TestCase):
    def test_dashboard_uses_structured_project_creation_form_instead_of_prompt_shortcut(self):
        content = Path("app/templates/index.html").read_text(encoding="utf-8")

        self.assertNotIn("function createProjectQuickly()", content)
        self.assertNotIn("window.prompt(", content)
        self.assertIn('id="create-project-modal"', content)
        self.assertIn('id="create-project-form"', content)
        self.assertIn('id="create-project-dimensions"', content)
        self.assertIn('id="create-project-modules"', content)
        self.assertIn("scoring_dimensions", content)


if __name__ == "__main__":
    unittest.main()
