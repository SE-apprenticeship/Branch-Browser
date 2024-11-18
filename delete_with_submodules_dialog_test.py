import unittest
from unittest.mock import Mock, patch
import tkinter as tk
from delete_with_submodules_dialog import DeleteWithSubmodulesDialog

class TestDeleteWithSubmodulesDialog(unittest.TestCase):
    def setUp(self):
        # Set up a root Tk instance for the dialog to attach to (required for tkinter dialogs)
        self.root = tk.Tk()
        self.root.withdraw()  # Hide the main Tkinter window

        # Mocking the GitHub client
        self.mock_github_client = Mock()
        self.org_name = "example_org"
        self.branch_name = "feature_branch"
        self.repos_with_branch = ["repo1", "repo2"]

        # Initialize dialog with mocked client and other data
        self.dialog = DeleteWithSubmodulesDialog(
            parent=self.root,
            github_client=self.mock_github_client,
            org_name=self.org_name,
            branch_name=self.branch_name,
            repos_with_branch=self.repos_with_branch
        )

    def tearDown(self):
        # Destroy the Tk instance after each test
        self.root.destroy()

    @patch('logging.warning')
    def test_apply_with_empty_repos_list(self, mock_warning):
        # Set repos_with_branch to empty to test early exit
        self.dialog.repos_with_branch = []

        # Call apply method
        self.dialog.apply()

        # Check that a warning was logged and no deletion was attempted
        mock_warning.assert_called_once_with(
            f"No repositories contain the branch '{self.branch_name}'. Deletion cannot proceed."
        )
        self.mock_github_client.organization_repo_delete_branch.assert_not_called()

    @patch('logging.info')
    @patch('logging.error')
    def test_apply_successful_deletion(self, mock_error, mock_info):
        # Mock the branch deletion and confirmation behavior
        self.mock_github_client.organization_repo_delete_branch.return_value = None
        self.mock_github_client.get_organization_repo_branches.side_effect = lambda org, repo: (
            [] if repo == "repo1" else ["feature_branch"]  # Simulate repo1 deletion success
        )

        # Call apply method
        self.dialog.apply()

        # Check that branch deletion was attempted for each repository
        self.mock_github_client.organization_repo_delete_branch.assert_any_call(
            self.org_name, "repo1", self.branch_name
        )
        self.mock_github_client.organization_repo_delete_branch.assert_any_call(
            self.org_name, "repo2", self.branch_name
        )
        # Check that success and error messages were logged correctly
        mock_info.assert_any_call("Branch 'feature_branch' confirmed deleted in repository 'repo1'.")
        mock_error.assert_called_once_with(
            "Branch 'feature_branch' still exists in repository 'repo2' after deletion attempt."
        )

    @patch('logging.error')
    def test_apply_with_deletion_error(self, mock_error):
        # Simulate an error when deleting the branch
        self.mock_github_client.organization_repo_delete_branch.side_effect = Exception("API Error")

        # Call apply method
        self.dialog.apply()

        # Verify that the error was logged
        mock_error.assert_any_call(
            "Error occurred while deleting branch 'feature_branch' in repository 'repo1': API Error"
        )
        mock_error.assert_any_call(
            "Error occurred while deleting branch 'feature_branch' in repository 'repo2': API Error"
        )

if __name__ == '__main__':
    unittest.main()
