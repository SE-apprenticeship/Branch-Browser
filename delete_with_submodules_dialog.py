import tkinter as tk
import logging
from tkinter import simpledialog


# Set up logging configuration
logging.basicConfig(
    # The log file where the messages will be stored
    filename='branch_deletion_with_submodules.log',
    # Log messages of this level or higher (INFO, WARNING, ERROR, etc.)
    level=logging.INFO,
    # Format of the log messages
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='a'  # Append to the file, don't overwrite
)


class DeleteWithSubmodulesDialog(simpledialog.Dialog):
    """
    A dialog to confirm the deletion of a branch in a repository and its associated submodules.

    This class creates a dialog that provides the user with information about the branches
    to be deleted, including the main repository and its submodules. The user is asked for
    confirmation before proceeding with the deletion. The class also handles the deletion of
    branches in both the main repository and the submodules, logging the results of each operation.

    Attributes:
        github_client (GitHubClient): The GitHub client instance to interact with GitHub's API.
        org_name (str): The name of the GitHub organization.
        repo_name (str): The name of the repository from which the branch will be deleted.
        branch_name (str): The name of the branch to delete in the main repository.
        submodules (list): A list of dictionaries representing submodules, each containing 'path' and 'branch' details.
        success (bool): Indicates whether the branch deletion process was successful.

    Methods:
        body(master): Creates the body of the dialog, displaying details about the branch and submodules to be deleted.
        apply(event=None): Handles the deletion process by calling helper methods to delete branches in the main repository and submodules.
        _delete_branch_in_main_repo(): Deletes the specified branch in the main repository.
        _delete_branches_in_submodules(): Deletes the specified branches in all submodules.
    """

    def __init__(self, parent, github_client, org_name, repo_name, branch_name,
                 submodules):
        """
        Initializes the dialog for confirming the deletion of a branch.

        Args:
            parent (tk.Tk): The parent window.
            github_client (GitHubClient): The GitHub client instance.
            org_name (str): The name of the organization.
            repo_name (str): The name of the repository.
            branch_name (str): The name of the branch to delete.
            submodules (list): List of submodules, each containing 'path' and 'branch'.
        """
        self.github_client = github_client
        self.org_name = org_name
        self.repo_name = repo_name
        self.branch_name = branch_name
        self.submodules = submodules

        self.success = False

        super().__init__(parent, title="Delete Branch with Submodules")

    def body(self, master):
        """
        Create the body of the dialog, displaying the branch deletion details.

        Args:
            master: The parent dialog to add the dialog components to.
        """
        self.resizable(False, False)

        # Prompt user about the deletion
        tk.Label(
            master,
            text=f"Are you sure you want to delete the following branches?"
        ).grid(row=0, column=0, padx=10, pady=10)

        branches_to_delete = f"{self.repo_name}: {self.branch_name}\n"
        for submodule in self.submodules:
            path = submodule.get("path")
            branch = submodule.get("branch")
            branches_to_delete += f"{path}: {branch}\n"

        tk.Label(master, text=branches_to_delete, justify="left").grid(
            row=1, column=0, padx=10, pady=10)

        # Add a warning about the action being irreversible
        tk.Label(master, text="This action cannot be undone.").grid(
            row=2, column=0, padx=10, pady=10)

    def apply(self, event=None):
        """
        Apply the deletion of the branch in each repository and submodule.

        This method calls the helper methods to delete branches in the main
        repository and its submodules. If all operations are successful,
        the `success` attribute is set to True. Otherwise, an error is logged.
        """
        try:
            # Delete branch in the main repository
            self._delete_branch_in_main_repo()

            # Delete branches in submodules
            self._delete_branches_in_submodules()

            # If all operations were successful, set success to True
            self.success = True

        except Exception as e:
            # Log the error and set success to False
            logging.error(f"An error occurred: {str(e)}")
            print(f"Error: {str(e)}")
            self.success = False

    def _delete_branch_in_main_repo(self):
        """
        Delete the specified branch in the main repository.

        Calls the GitHub client's method to delete the branch in the main repository.
        Logs the success or failure of the operation.
        """
        try:
            self.github_client.organization_repo_delete_branch(
                self.org_name, self.repo_name, self.branch_name
            )
            print(f"Successfully deleted branch '{self.branch_name}' in repository '{self.repo_name}'.")
            logging.info(f"Successfully deleted branch '{self.branch_name}' in repository '{self.repo_name}'.")
        except Exception as e:
            logging.error(f"Failed to delete branch '{self.branch_name}' in repository '{self.repo_name}': {str(e)}")
            print(f"Failed to delete branch '{self.branch_name}' in repository '{self.repo_name}': {str(e)}")
            raise e

    def _delete_branches_in_submodules(self):
        """
        Delete the branches in all specified submodules.

        Iterates through the list of submodules and calls the GitHub client's method
        to delete each branch in the respective submodule repository. Logs the success
        or failure of each operation.
        """
        for submodule in self.submodules:
            submodule_path = submodule.get("path")
            submodule_branch = submodule.get("branch")

            try:
                self.github_client.organization_repo_delete_branch(
                    self.org_name, submodule_path, submodule_branch
                )
                print(f"Branch '{submodule_branch}' deleted successfully in submodule '{submodule_path}'.")
                logging.info(f"Branch '{submodule_branch}' deleted successfully in submodule '{submodule_path}'.")
            except Exception as e:
                logging.error(f"Failed to delete branch '{submodule_branch}' in submodule '{submodule_path}': {str(e)}")
                print(f"Failed to delete branch '{submodule_branch}' in submodule '{submodule_path}': {str(e)}")
                raise e
