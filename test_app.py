import unittest
from unittest.mock import Mock, patch, MagicMock, mock_open
from BranchBrowser import App, load_config
import os

class TestAppMethods(unittest.TestCase):

    def setUp(self):
        with patch.object(App, 'setup_ui'), patch.object(App, 'setup_actions'):
            self.mock_root = Mock()
            self.mock_github_client = Mock()
            self.app = App(self.mock_root, self.mock_github_client, "TestOrg", "TestRepo")
        
        self.app.org_combo = Mock()
        self.app.repo_combo = MagicMock()
        self.app.branches_tree = MagicMock()

        self.app.populate_tree = Mock()

        # Ensure get_children() returns a list (or any iterable)
        self.app.branches_tree.get_children.return_value = ['child1', 'child2']

    def test_refresh_branches_by_config(self):
        self.app.org_combo.get.return_value = "TestOrg"
        self.app.repo_combo.get.return_value = "TestRepo"
        branches_structure = {"main": ["feature1", "feature2"], "dev": ["hotfix"]}
        self.mock_github_client.get_repo_branches_structure.return_value = branches_structure

        self.app.refresh_branches_by_config()

        # Test that the delete method is called with the iterable returned by get_children()
        self.app.branches_tree.delete.assert_called_once_with('child1', 'child2')
        self.app.branches_tree.heading.assert_called_once_with("#0", text="Branches on TestOrg/TestRepo")
        self.app.populate_tree.assert_called_once_with(self.app.branches_tree, branches_structure)

    @patch.object(App, 'update_tree')
    def test_update_repos(self, mock_update_tree):
        self.app.org_combo.get.return_value = "TestOrg"
        repos = ["repo1", "TestRepo", "repo3"]
        self.mock_github_client.get_organization_repos_names.return_value = repos

        self.app.update_repos(event=None)

        # Set the mock 'values' attribute directly
        self.app.repo_combo.__getitem__.side_effect = lambda key: repos if key == 'values' else None

        self.app.repo_combo['values'] = repos
        self.app.repo_combo.current.assert_called_once_with(1)
        mock_update_tree.assert_called_once()

    @patch.object(App, 'refresh_branches_by_config')
    def test_update_tree(self, mock_refresh_branches_by_config):
        self.app.update_tree(event=None)

        mock_refresh_branches_by_config.assert_called_once()

    @patch("builtins.open", new_callable=mock_open, read_data='{"default_organization": "TestOrg", "default_repository": "TestRepo"}')
    def test_load_config_valid(self, mock_file):
        config = load_config()
        
        self.assertIsNotNone(config)
        self.assertEqual(config.get("default_organization"), "TestOrg")
        self.assertEqual(config.get("default_repository"), "TestRepo")
        mock_file.assert_called_once_with(os.path.join(os.path.dirname(__file__), "config.json"), "r")

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists", return_value=False)
    def test_load_config_file_not_found(self, mock_exists, mock_file):
        config = load_config()
        
        self.assertIsNone(config)
        mock_exists.assert_called_once_with(os.path.join(os.path.dirname(__file__), "config.json"))
        mock_file.assert_not_called()

    @patch("builtins.open", new_callable=mock_open, read_data='{"default_organization": "TestOrg", "default_repository": "TestRepo"')
    def test_load_config_invalid_json(self, mock_file):
        config = load_config()
        
        self.assertIsNone(config)
        mock_file.assert_called_once_with(os.path.join(os.path.dirname(__file__), "config.json"), "r")
if __name__ == '__main__':
    unittest.main()
