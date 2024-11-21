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

    def __init__(self, parent, github_client, org_name, repo_name, branch_name,
                 submodules):
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
        self.repo_name = repo_name
        self.branch_name = branch_name
        self.submodules = submodules

        self.success = False
        

        super().__init__(
            parent, title="Delete Branch with Submodules"
            )
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
            text=f"Are you sure you want to delete the following branches?"
        ).grid(row=0, column=0, padx=10, pady=10)

        # List the repositories with the branch
        # repo_list_text = "\n".join(self.repos_with_branch)
        # tk.Label(master, text=repo_list_text, justify="left").grid(
        #     row=1, column=0, padx=10, pady=10)

        branches_to_delete = f"{self.repo_name}: {self.branch_name}\n"
        print(f"Num of submodules: {len(self.submodules)}")
        for submodule in self.submodules:
            path = submodule.get("path")
            branch = submodule.get("branch")
            branches_to_delete += f"{path}: {branch}\n"
        # for submodule in self.submodules:
        #     branches_to_delete = branches_to_delete.join(submodule.get("path"))
        #     branches_to_delete = branches_to_delete.join(submodule.get("branch"))

        tk.Label(master, text=branches_to_delete, justify="left").grid(
            row=1, column=0, padx=10, pady=10)

        # Add a warning about the action being irreversible
        tk.Label(master, text="This action cannot be undone.").grid(
            row=2, column=0, padx=10, pady=10)

    def apply(self, event=None):
        print("Apply method triggered")
        """
        Apply the deletion of the branch in each repository and submodule.
        """
        try:
            # Brisanje grane iz glavnog repozitorijuma
            self.github_client.organization_repo_delete_branch(
                self.org_name, self.repo_name, self.branch_name
            )
            print(f"Successfully deleted branch '{self.branch_name}' in repository '{self.repo_name}'.")

            # Provera postojanja grane
            branches = self.github_client.get_organization_repo_branches(
                self.org_name, self.repo_name
            )
            if self.branch_name in branches:
                raise Exception(f"Branch '{self.branch_name}' still exists in repository '{self.repo_name}'.")

            # Brisanje grana u podmodulima
            for submodule in self.submodules:
                submodule_path = submodule.get("path")
                submodule_branch = submodule.get("branch")

                self.github_client.organization_repo_delete_branch(
                    self.org_name, submodule_path, submodule_branch
                )
                print(f"Branch '{submodule_branch}' deleted successfully in submodule '{submodule_path}'.")

                submodule_branches = self.github_client.get_organization_repo_branches(
                    self.org_name, submodule_path
                )
                if submodule_branch in submodule_branches:
                    raise Exception(f"Branch '{submodule_branch}' still exists in submodule '{submodule_path}'.")

            # Ako su sve operacije uspešne, postavi success na True
            self.success = True

        except Exception as e:
            # Loguj grešku i postavi success na False
            logging.error(f"An error occurred: {str(e)}")
            print(f"Error: {str(e)}")
            self.success = False
        print("OK")

    # def validate(self):
    #     """
    #     Ensure the operation completed successfully before allowing dialog to close.
    #     """
    #     return self.success