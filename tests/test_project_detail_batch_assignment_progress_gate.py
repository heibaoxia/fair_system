from pathlib import Path
import unittest


class ProjectDetailBatchAssignmentProgressGateTests(unittest.TestCase):
    def test_batch_assignment_action_uses_progress_api_and_effective_completion(self):
        content = Path("app/templates/project_detail.html").read_text(encoding="utf-8")

        self.assertIn('async function updateBatchAssignmentAction()', content)
        self.assertIn("await fetch(`/scoring/project/{{ project.id }}/progress`)", content)
        self.assertIn("const effectiveCompletion = Boolean(data && data.effective_completion === true);", content)
        self.assertIn("trigger.title = '评分尚未全部完成';", content)
        self.assertNotIn("const isAssessmentActive = getAssessmentPeriodStatus() === 'active';", content)
        self.assertNotIn("trigger.title = '请等待评分结束';", content)


if __name__ == "__main__":
    unittest.main()
