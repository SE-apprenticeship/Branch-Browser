"""
This module defines the `DeleteWithSubmodulesDialog` class, which provides
a GUI dialog for confirming the deletion of a branch in multiple GitHub
repositories. It handles the confirmation and deletion process, including
handling repositories with submodules.

Classes:
    DeleteWithSubmodulesDialog: A custom dialog class for confirming branch
    deletions across repositories in a GitHub organization, with submodule
    handling.

Usage:
    This module is used in the context of a larger GitHub management tool
    that interacts with the GitHub API and allows users to manage branches
    across multiple repositories, including repositories with submodules.
"""

import tkinter as tk
from tkinter import simpledialog
import logging

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
    A dialog to confirm the deletion of a branch in multiple repositories
    with submodule handling.
    """

    def __init__(self, parent, github_client, org_name, branch_name,
                 repos_with_branch):
        """
        Initializes the dialog for confirming the deletion of a branch.

        Args:
            parent (tk.Tk): The parent window.
            github_client (GitHubClient): The GitHub client instance.
            org_name (str): The name of the organization.
            branch_name (str): The name of the branch to delete.
            repos_with_branch (list): List of repositories containing the branch.
        """
        self.github_client = github_client
        self.org_name = org_name
        self.branch_name = branch_name
        self.repos_with_branch = repos_with_branch

        super().__init__(
            parent, title=f"Delete branch '{branch_name}' in organization "
            f"'{org_name}'")

    def body(self, master):
        """
        Create the body of the dialog, displaying the branch deletion details.

        Args:
            master (tk.Widget): The parent widget to add the dialog components to.
        """
        self.resizable(False, False)

        # Prompt user about the deletion
        tk.Label(
            master,
            text=f"Are you sure you want to delete branch '{self.branch_name}' "
            f"in the following repositories?"
        ).grid(row=0, column=0, padx=10, pady=10)

        # List the repositories with the branch
        repo_list_text = "\n".join(self.repos_with_branch)
        tk.Label(master, text=repo_list_text, justify="left").grid(
            row=1, column=0, padx=10, pady=10)

        # Add a warning about the action being irreversible
        tk.Label(master, text="This action cannot be undone.").grid(
            row=2, column=0, padx=10, pady=10)

    def apply(self):
        """
        Apply the deletion of the branch in each repository.

        This method deletes the specified branch from each repository in repos_with_branch
        after confirming the action through the dialog. It then verifies if the branch was
        actually deleted by checking if the branch still exists. If no repositories are selected,
        it will display a message and return early.

        Args:
            None

        Returns:
            None

        Side Effects:
            - Deletes the branch from each repository in repos_with_branch.
            - Prints status messages to the console for each repository where the branch is deleted.
            - Verifies that the branch was deleted and prints confirmation or error.
        """
        # Check if repos_with_branch is empty
        if not self.repos_with_branch:
            message = f"No repositories contain the branch '{self.branch_name}'. Deletion cannot proceed."
            logging.warning(message)  # Log a warning
            print(message)
            return  # Exit early if no repositories contain the branch

        # Loop through each repository to delete the branch
        for repo_name in self.repos_with_branch:
            # Log the attempt to delete the branch
            logging.info(
                f"Attempting to delete branch '{self.branch_name}' in repository '{repo_name}'.")

            try:
                # Deleting the branch from the repository
                self.github_client.organization_repo_delete_branch(
                    self.org_name, repo_name, self.branch_name
                )

                # Log success of deletion attempt
                logging.info(
                    f"Branch '{self.branch_name}' successfully deleted in repository '{repo_name}'.")
                print(
                    f"Branch '{self.branch_name}' deleted successfully in repository '{repo_name}'.")

                # Verify if the branch was successfully deleted
                branches = self.github_client.get_organization_repo_branches(
                    self.org_name, repo_name)

                if self.branch_name not in branches:
                    # Log success of verification
                    logging.info(
                        f"Branch '{self.branch_name}' confirmed deleted in repository '{repo_name}'.")
                    print(
                        f"Successfully deleted branch '{self.branch_name}' in repository '{repo_name}'.")
                else:
                    # Log failure of verification
                    logging.error(
                        f"Branch '{self.branch_name}' still exists in repository '{repo_name}' after deletion attempt.")
                    print(
                        f"Error: Branch '{self.branch_name}' still exists in repository '{repo_name}'.")

            except Exception as e:
                # Log the error and continue
                error_message = f"Error occurred while deleting branch '{self.branch_name}'"
                error_message += f" in repository '{repo_name}': "
                error_message += f"{str(e)}"
                logging.error(error_message)
                print(error_message)

        # Return the branch name to indicate that the action was applied
        self.result = self.branch_name
