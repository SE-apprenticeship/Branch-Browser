import threading
import tkinter as tk
from tkinter import simpledialog, messagebox
from tkinter import ttk

from message_type import MessageType


class DeleteWithSubmodulesDialog(simpledialog.Dialog):
    """
    A dialog to confirm and execute the deletion of a branch and its associated submodule branches.

    Attributes:
        github_client (GitHubClient): The GitHub client instance for API interaction.
        org_name (str): The name of the GitHub organization.
        repo_name (str): The name of the repository.
        branch_name (str): The branch to be deleted in the main repository.
        submodules (list): List of dictionaries, each containing submodule 'path' and 'branch'.
        refresh_callback (callable): Callback function to refresh the UI post-deletion.
    """

    def __init__(self, parent, github_client, org_name, repo_name, branch_name, submodules, refresh_callback):
        """
        Initialize the dialog for branch deletion.

        Args:
            parent (tk.Tk): The parent window.
            github_client (GitHubClient): GitHub client for API operations.
            org_name (str): GitHub organization name.
            repo_name (str): GitHub repository name.
            branch_name (str): The branch to delete in the main repository.
            submodules (list): List of submodule details (dicts with 'path' and 'branch').
            refresh_callback (callable): Function to refresh the UI after deletion.
        """
        validate_parameters(org_name, repo_name, branch_name, submodules)

        self.github_client = github_client
        self.org_name = org_name
        self.repo_name = repo_name
        self.branch_name = branch_name
        self.submodules = submodules
        self.refresh_callback = refresh_callback

        super().__init__(parent, title="Delete Branch with Submodules")

    def body(self, master):
        """
        Create the body of the dialog, displaying branch deletion details.

        Args:
            master (tk.Widget): Parent widget to attach components to.
        """
        self.resizable(False, False)

        tk.Label(
            master,
            text="Are you sure you want to delete the following branches?"
            ).grid(row=0, column=0, padx=10, pady=10)

        branches_to_delete = f"{self.repo_name}: {self.branch_name}\n"
        for submodule in self.submodules:
            path = submodule.get("path")
            branch = submodule.get("branch")
            branches_to_delete += f"{path}: {branch}\n"

        tk.Label(master, text=branches_to_delete, justify="left").grid(row=1, column=0, padx=10, pady=10)
        tk.Label(master, text="This action cannot be undone.").grid(row=2, column=0, padx=10, pady=10)

    def buttonbox(self):
        """Create and layout the dialog's buttons."""
        box = ttk.Frame(self)

        ttk.Button(box, text="Yes", width=10, command=self.apply).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(box, text="No", width=10, command=self.cancel).pack(side=tk.LEFT, padx=5, pady=5)

        box.pack()

    def apply(self, event=None):
        """
        Start the branch deletion process.

        Initiates a thread to handle deletion to keep the UI responsive.
        """
        self.processing_popup = tk.Toplevel(self.master)
        self.processing_popup.geometry("300x50")
        tk.Label(self.processing_popup, text="Deleting branches...").pack()
        self.processing_popup.protocol("WM_DELETE_WINDOW", lambda: None)  # Disable close button
        self.processing_popup.grab_set()

        self.destroy()

        threading.Thread(target=self.process).start()

    def process(self):
        """
        Execute the branch deletion process for the main repository and submodules.
        """
        try:
            self.__delete_branch_in_main_repo()
            self.__delete_branches_in_submodules()

            messagebox.showinfo("Success", "Branch and submodules deleted successfully!")
            self.refresh_callback()
        except Exception as e:
            error_message = f"An error occured during deleting branch with submodules: {str(e)}"
            print_message(
                MessageType.ERROR, 
                error_message)
            messagebox.showerror(
                "Error", 
                error_message)
        finally:
            self.processing_popup.destroy()

    def cancel(self, event=None):
        """Handle cancellation of the dialog."""
        cancellation_message = "Branch deletion with submodules was cancelled."
        self.destroy()
        print_message(MessageType.WARNING, cancellation_message)
        messagebox.showwarning("Cancelled", cancellation_message)
        super().cancel(event)

    def __delete_branch(self, repo_name, branch_name):
        """
        Delete a branch in a specified repository.

        Args:
            repo_name (str): The name of the repository where the branch should be deleted.
            branch_name (str): The name of the branch to delete.

        Raises:
            Exception: If the deletion fails.
        """
        try:
            self.github_client.organization_repo_delete_branch(self.org_name, repo_name, branch_name)
            print_message(MessageType.INFO, f"Deleted branch '{branch_name}' in '{repo_name}'.")
        except Exception as e:
            print_message(
                MessageType.ERROR,
                f"Failed to delete branch '{branch_name}' in '{repo_name}': {str(e)}")
            raise

    def __delete_branch_in_main_repo(self):
        """
        Delete the branch in the main repository by using the __delete_branch method.
        
        Raises:
            Exception: If the deletion fails.
        """
        self.__delete_branch(self.repo_name, self.branch_name)
        
    def __delete_branches_in_submodules(self):
        """
        Delete branches in all specified submodules by using the __delete_branch method.
        
        Raises:
            Exception: If any submodule branch deletion fails.
        """
        for submodule in self.submodules:
            submodule_path = submodule.get("path")
            submodule_branch = submodule.get("branch")
            self.__delete_branch(submodule_path, submodule_branch)


def validate_parameters(org_name, repo_name, branch_name, submodules):
    """
    Validate input parameters for the dialog.

    Args:
        org_name (str): Organization name.
        repo_name (str): Repository name.
        branch_name (str): Branch name.
        submodules (list): List of submodule dictionaries.

    Raises:
        ValueError: If any parameter is invalid.
    """
    if not isinstance(org_name, str) or not org_name:
        error_message = "org_name must be a non-empty string."
        print_message(MessageType.ERROR, f"Validation Error: {error_message}")
        raise ValueError(error_message)
    
    if not isinstance(repo_name, str) or not repo_name:
        error_message = "repo_name must be a non-empty string."
        print_message(MessageType.ERROR, f"Validation Error: {error_message}")
        raise ValueError(error_message)
    
    if not isinstance(branch_name, str) or not branch_name:
        error_message = "branch_name must be a non-empty string."
        print_message(MessageType.ERROR, f"Validation Error: {error_message}")
        raise ValueError(error_message)
    
    if not isinstance(submodules, list):
        error_message = "submodules must be a list."
        print_message(MessageType.ERROR, f"Validation Error: {error_message}")
        raise ValueError(error_message)

    for submodule in submodules:
        if not isinstance(submodule, dict) or "path" not in submodule or "branch" not in submodule:
            error_message = f"Each submodule must be a dictionary with 'path' and 'branch': {submodule}"
            print_message(MessageType.ERROR, f"Validation Error: {error_message}")
            raise ValueError(error_message)
        
        path = submodule.get("path")
        branch = submodule.get("branch")

        if not isinstance(path, str) or not path.strip():
            error_message = f"'path' must be a non-empty string: {path}"
            print_message(MessageType.ERROR, f"Validation Error: {error_message}")
            raise ValueError(error_message)
        
        if not isinstance(branch, str) or not branch.strip():
            error_message = f"'branch' must be a non-empty string: {branch}"
            print_message(MessageType.ERROR, f"Validation Error: {error_message}")
            raise ValueError(error_message)


def print_message(msg_type, message):
    """
    Print a message with its type.

    Args:
        msg_type (MessageType): The type of the message.
        message (str): The message content.
    """
    print(f"{msg_type.value} {message}")
