from pathlib import Path
import unittest


class ProjectDetailScoringRemovedTests(unittest.TestCase):
    def test_project_detail_no_longer_contains_assessment_form_or_legacy_weight_logic(self):
        content = Path("app/templates/project_detail.html").read_text(encoding="utf-8")

        self.assertNotIn('id="detail-assessment-section"', content)
        self.assertNotIn('id="detail-locked-section"', content)
        self.assertNotIn('function submitAssessmentForm', content)
        self.assertNotIn('function loadAssessments', content)
        self.assertNotIn('function renderAssessments', content)
        self.assertNotIn('function triggerAutoSummarize', content)
        self.assertNotIn('function setDetailPanels', content)
        self.assertNotIn("const assessmentForm = document.getElementById('assessment-form');", content)
        self.assertNotIn("project.weight_difficulty", content)
        self.assertNotIn("project.weight_hours", content)
        self.assertNotIn("project.weight_boredom", content)
        self.assertNotIn("project.weight_intensity", content)
        self.assertNotIn("const projectScoreWeights =", content)
        self.assertIn("summary.dimension_averages", content)
        self.assertIn('function loadModuleSummary', content)
        self.assertIn('function renderScoreBreakdown', content)


if __name__ == "__main__":
    unittest.main()
