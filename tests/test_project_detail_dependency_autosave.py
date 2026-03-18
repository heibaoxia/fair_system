from pathlib import Path
import unittest


class ProjectDetailDependencyAutosaveTests(unittest.TestCase):
    def test_manual_save_dependency_button_removed(self):
        content = Path("app/templates/project_detail.html").read_text(encoding="utf-8")

        self.assertNotIn('data-manager-action="save-dependencies"', content)
        self.assertNotIn('保存依赖关系', content)

    def test_add_connection_posts_immediately_and_rolls_back_on_failure(self):
        content = Path("app/templates/project_detail.html").read_text(encoding="utf-8")

        self.assertIn('async function addConnection(from, to)', content)
        self.assertIn("await fetch(`/projects/${projectId}/dependencies?current_member_id=${currentMemberId}`", content)
        self.assertIn("connections = connections.filter((item) => connectionKey(item.from, item.to) !== key);", content)
        self.assertIn("showToast(error.message || '依赖关系保存失败', true);", content)

    def test_delete_selected_connection_calls_delete_api_immediately(self):
        content = Path("app/templates/project_detail.html").read_text(encoding="utf-8")

        self.assertIn("document.addEventListener('keydown', async function (event) {", content)
        self.assertIn("await fetch(`/projects/${projectId}/dependencies/${persistedConnection.id}?current_member_id=${currentMemberId}`", content)
        self.assertIn("persistedConnections = persistedConnections.filter((item) => item.id !== persistedConnection.id);", content)
        self.assertIn("showToast(error.message || '删除依赖关系失败', true);", content)


if __name__ == "__main__":
    unittest.main()
