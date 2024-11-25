import base64
import datetime
from enum import Enum
from io import StringIO
import json
import os
import re
import sys
import threading
import tkinter as tk
from tkinter import BOTTOM, RIGHT, X, Y, Scrollbar, font
from tkinter import messagebox
import tkinter.ttk as ttk
from tkinter import simpledialog
from github import Github, GithubException
import configparser
import requests
import win32cred
from handlers.exceptions_handler import ExceptionsHandler
from message_type import MessageType
token = ''
GIT_HOSTNAME = 'github.com'
exceptions_handler = ExceptionsHandler()
class GitHubClient:
    def __init__(self, hostname, token):
        self.github = Github(base_url=f"https://api.{hostname}", login_or_token=token)
        self.user = self.github.get_user()
        self.username = self.user.login # this will throw exception if token is invalid

    def get_username(self):
        return self.username

    def get_organizations_names(self):
        orgs = []
        try:
            orgs = [org.login for org in self.user.get_orgs()]
        except Exception as e:
            handle_and_print_exception(e, 'No organizations found.')
        return orgs
    
    def get_organization_repos_names(self, org_name):
        repos = []
        try:
            repos = [repo.name for repo in self.github.get_organization(org_name).get_repos()]
        except Exception as e:
            err_desc = f"Authenticated user ('{self.username}') lacks the necessary permissions to access the list of repositories for organization: {org_name}"
            handle_and_print_exception(e, err_desc)
        return repos
    
    def get_organization_repo_branches(self, org_name, repo_name):
        branches = []
        try:
            branches = [branch.name for branch in self.github.get_organization(org_name).get_repo(repo_name).get_branches()]
        except Exception as e:
            err_desc = f"Authenticated user ('{self.username}') lacks the necessary permissions to access the list of branches for repository: '{org_name}{repo_name}'."
            handle_and_print_exception(e, err_desc)
        return branches
    
    def get_organization_repo_branch_gitmodules_content(self, org_name, repo_name, branch_name):
        file_content = None
        try:
            org = self.github.get_organization(org_name)
            repo = org.get_repo(repo_name)
            file_content = repo.get_contents('.gitmodules', ref=branch_name)
        except Exception as e:
            if isinstance(e, GithubException) and e.status == 404:
                return None
            else:
                handle_and_print_exception(e)
        return file_content.decoded_content.decode('utf-8') if file_content else None

    def get_organization_repo_branch_commit_sha(self, org_name, repo_name, branch_name):
        try:
            return self.github.get_organization(org_name).get_repo(repo_name).get_branch(branch_name).commit.sha
        except Exception as e:
            error_desc = f"Commit SHA not found.The branch may be empty, or the user ('{self.username}') lacks permissions to access the commit history for '{org_name}{repo_name}{branch_name}'."
            handle_and_print_exception(e, error_desc)
            return

    def organization_repo_create_branch(self, org_name, repo_name, new_branch_name, source_commit_sha):
        # refs/heads/new-branch is used to create a new branch
        try:
            self.github.get_organization(org_name).get_repo(repo_name).create_git_ref(ref=f"refs/heads/{new_branch_name}", sha=source_commit_sha)
        except Exception as e:
            error_desc = f"The new branch name ('{self.branch_name}') may already exist, or the user lacks permission to create branches."
            handle_and_print_exception(e, error_desc)
            
    def organization_repo_delete_branch(self, org_name, repo_name, branch_name):
        try:
            # Fetch the branch reference
            ref = self.github.get_organization(org_name).get_repo(repo_name).get_git_ref(f"heads/{branch_name}")
        except Exception as e:
            handle_and_print_exception(e, f"The specified Git reference for the branch '{branch_name}' does not exist.")
        try:
            # Delete the branch by deleting its reference
            ref.delete()
        except Exception as e:
            handle_and_print_exception(e, f"Unable to delete branch {branch_name}.")

    def get_repo_branches_structure(self, org_name, repo_name):
        repo = self.github.get_organization(org_name).get_repo(repo_name)
        structure = {}
        for branch in repo.get_branches():
            parts = branch.name.split('/')
            node = structure
            for part in parts:
                if part not in node:
                    node[part] = {}
                node = node[part]
        return structure
    
    #Retrieve the names of teams in the specified organization.
    def get_organization_teams(self, org_name):
        org = self.github.get_organization(org_name)
        return [team.name for team in org.get_teams()]

class GitHubRepoSubmoduleManager:
    def __init__(self, owner, repo_top, token):
        self.owner = owner # If repo is in organization then org is owner
        self.repo_top = repo_top # Repository for which the submodules are being managed
        self.token = token
        self.hostname = f'api.{GIT_HOSTNAME}'
        self.headers = {
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json',
        }

    def make_request(self, method, url, data=None):
        try:
            response = requests.request(method, url, headers=self.headers, data=json.dumps(data))
            response.raise_for_status()
            return response.json()
        except Exception as e:
            handle_and_print_exception(e, f"Unable to make request [{method}] on {url}")
            
    def fix_config_file_formatting(self, content):
        # Remove \n in front of [ - because of duplicates
        content = re.sub(r'\n(?=\[)', '', content)
        # Add \t in front of every line except one that starts with [ and also except empty lines
        content = re.sub(r'^(?!$|\[)', '\t', content, flags=re.MULTILINE)
        # Convert double \n\n to \n at the end of file
        return content.rstrip('\n')+'\n'

    def delete_submodule(self, repo_top_branch, repo_sub, path_to_submodule):
        # Get the commit hash of the parent repository
        parent_tree_sha = self.make_request('GET', f'https://{self.hostname}/repos/{self.owner}/{self.repo_top}/branches/{repo_top_branch}')['commit']['sha']

        # Get parent root tree list and try to find .gitmodules
        parent_tree_list = self.make_request('GET', f'https://{self.hostname}/repos/{self.owner}/{self.repo_top}/git/trees/{parent_tree_sha}')['tree']
        gitmodules_entry = next((entry for entry in parent_tree_list if entry['path'] == '.gitmodules'), None)

        gitmodules_config = configparser.ConfigParser(allow_no_value=True)
        if gitmodules_entry:
            # Get file blob for .gitmodules
            gitmodules_entry_blob = self.make_request('GET', f'https://{self.hostname}/repos/{self.owner}/{self.repo_top}/git/blobs/{gitmodules_entry["sha"]}')
            gitmodules_content = base64.b64decode(gitmodules_entry_blob['content'].rstrip('\n')).decode('utf-8')
            gitmodules_config.read_string(gitmodules_content)

            if f'submodule "{repo_sub}"' in gitmodules_config:
                del gitmodules_config[f'submodule "{repo_sub}"']
            else:
                # Nothing to delete
                return

            # If .gitmodules is now empty, delete it
            if len(gitmodules_config) == 1: # 1 is empty config for some strange reason (maybe becaouse of default config functionality)
                git_modules_blob_sha = None # This will delete file from tree
            else: # Update file
                gitmodules_output = StringIO()
                gitmodules_config.write(gitmodules_output)
                content_encoded = base64.b64encode(self.fix_config_file_formatting(gitmodules_output.getvalue()).encode('utf-8')).decode('utf-8') + '\n'
                # Create new .gitmodules file blob data
                gitmodules_entry_blob_data = {
                    "content": content_encoded,
                    "encoding": "base64"
                }

                git_modules_blob_sha = self.make_request('POST', f'https://{self.hostname}/repos/{self.owner}/{self.repo_top}/git/blobs', gitmodules_entry_blob_data)['sha']
        else:
            # No gitmodules file, nothing to delete
            return

        # Filter out the deleted submodule entry
        new_tree_entries = [
            entry for entry in parent_tree_list
            if entry['path'] != path_to_submodule
        ]

        # Check if .gitmodules entry exists and update it, otherwise add it
        gitmodules_updated = False
        for entry in new_tree_entries:
            if entry['path'] == '.gitmodules':
                entry['sha'] = git_modules_blob_sha
                gitmodules_updated = True
                break

        if not gitmodules_updated:
            new_tree_entries.append({
                "path": ".gitmodules",
                "mode": "100644",
                "type": "blob",
                "sha": git_modules_blob_sha,
            })

        # Create a git tree that updates/deletes the gitmodule file and deletes submodule reference in tree
        data = {
            'base_tree': parent_tree_sha,
            'tree': new_tree_entries
        }

        parent_tree_sha_new = self.make_request('POST', f'https://{self.hostname}/repos/{self.owner}/{self.repo_top}/git/trees', data)['sha']

        commit_message = f'Deleted {repo_sub} submodule'
        
        # Tree is recreated, just commit and update head
        self.commit_tree_and_update_head(repo_top_branch, parent_tree_sha, parent_tree_sha_new, commit_message)

    def add_or_update_submodule(self, repo_top_branch, repo_sub, path_to_submodule, sub_branch = None):
        # Get the commit hash of the parent repository
        parent_tree_sha = self.make_request('GET', f'https://{self.hostname}/repos/{self.owner}/{self.repo_top}/branches/{repo_top_branch}')['commit']['sha']

        # Get parent root tree list and try to find .gitmodules
        parent_tree_list = self.make_request('GET', f'https://{self.hostname}/repos/{self.owner}/{self.repo_top}/git/trees/{parent_tree_sha}')['tree']
        gitmodules_entry = next((entry for entry in parent_tree_list if entry['path'] == '.gitmodules'), None)
        path_to_submodule_splitted = path_to_submodule.split('/')

        tree_list = parent_tree_list
        for path_part in path_to_submodule_splitted:
            submodule_entry = next((entry for entry in tree_list if entry['path'] == path_part), None)
            if submodule_entry and submodule_entry['type'] == 'tree':
                # Get the tree 
                tree_sha = submodule_entry['sha']
                tree_list = self.make_request('GET', f'https://{self.hostname}/repos/{self.owner}/{self.repo_top}/git/trees/{tree_sha}')['tree']
            
        gitmodules_config = configparser.ConfigParser(allow_no_value=True)
        add_submodule_section = False
        update_submodule_branch = False
        if gitmodules_entry:
            # Get file blob for .gitmodules
            gitmodules_entry_blob = self.make_request('GET', f'https://{self.hostname}/repos/{self.owner}/{self.repo_top}/git/blobs/{gitmodules_entry["sha"]}')
            gitmodules_content = base64.b64decode(gitmodules_entry_blob['content'].rstrip('\n')).decode('utf-8')
            gitmodules_config.read_string(gitmodules_content)

            # Check do we have this submodule in gitmodules
            if f'submodule "{repo_sub}"' in gitmodules_config:
                if sub_branch and gitmodules_config[f'submodule "{repo_sub}"']['branch'] != sub_branch: # If submodule branch is specified and different it meand that we must update it
                    gitmodules_config[f'submodule "{repo_sub}"']['branch'] = sub_branch
                    update_submodule_branch = True
                else: # We take current branch set in gitmodules file
                    sub_branch = gitmodules_config[f'submodule "{repo_sub}"']['branch']
            else:
                # Add submodule section to existing file
                add_submodule_section = True
        else:
            # Add submodule section to new file
            add_submodule_section = True

        if sub_branch == None:
            # We should either get sub branch if (adding new submodule)/(updating branch) or have it in .gitmodules file if updating just submodule pointer
            return False

        if add_submodule_section: # No matter whether file is updated or added new blob must be created anyway (old file blob is left for child changeset)
            gitmodules_config.add_section(f'submodule "{repo_sub}"')
            gitmodules_config.set(f'submodule "{repo_sub}"', 'path', path_to_submodule)
            gitmodules_config.set(f'submodule "{repo_sub}"', 'url', f'../{repo_sub}.git')
            gitmodules_config.set(f'submodule "{repo_sub}"', 'branch', sub_branch)

        if add_submodule_section or update_submodule_branch:
            gitmodules_output = StringIO()
            gitmodules_config.write(gitmodules_output)
            content_encoded = base64.b64encode(self.fix_config_file_formatting(gitmodules_output.getvalue()).encode('utf-8')).decode('utf-8') + '\n'
            # Create .gitmodules file
            gitmodules_entry_blob_data = {
                "content": content_encoded,
                "encoding": "base64"
            }

            git_modules_blob_sha = self.make_request('POST', f'https://{self.hostname}/repos/{self.owner}/{self.repo_top}/git/blobs', gitmodules_entry_blob_data)['sha']
            gitmodules_tree_entry =  {
                    "path": ".gitmodules",
                    "mode": "100644",
                    "type": "blob",
                    "sha": git_modules_blob_sha,
                }
            
        # Get the commit hash from the submodule repository
        target_sub_sha = self.make_request('GET', f'https://{self.hostname}/repos/{self.owner}/{repo_sub}/branches/{sub_branch}')['commit']['sha'] 

        # Create a git tree that updates the submodule reference
        data = {
            'base_tree': parent_tree_sha,
            'tree': [
                {
                    'path': path_to_submodule,
                    'mode': '160000',
                    'type': 'commit',
                    'sha': target_sub_sha
                }
            ]
        }

        # Only if we added submodule or updated submodule branc add gitmodules blob
        if add_submodule_section or update_submodule_branch:
            # Add update of gitmodules
            data['tree'].append(gitmodules_tree_entry)
        else:
            # Check if submodule pointer changed
            if submodule_entry['sha'] == target_sub_sha:
                # Nothing to update
                return False

        parent_tree_sha_new = self.make_request('POST', f'https://{self.hostname}/repos/{self.owner}/{self.repo_top}/git/trees', data)['sha']

        operation_string = 'Added' if add_submodule_section else 'Updated'
        commit_message = f'{operation_string} {repo_sub} submodule'
        
        # Tree is recreated, just commit and update head
        self.commit_tree_and_update_head(repo_top_branch, parent_tree_sha, parent_tree_sha_new, commit_message)

        return True

    def commit_tree_and_update_head(self, parent_branch, parent_tree_sha, parent_tree_sha_new, commit_message):
        # Commit the tree
        data = {
            'message': commit_message,
            'tree': parent_tree_sha_new,
            'parents': [parent_tree_sha]
        }
        commit_sha = self.make_request('POST', f'https://{self.hostname}/repos/{self.owner}/{self.repo_top}/git/commits', data)['sha']

        # Update parent branch to point to your new commit
        data = {
            'sha': commit_sha
        }
        response = self.make_request('PATCH', f'https://{self.hostname}/repos/{self.owner}/{self.repo_top}/git/refs/heads/{parent_branch}', data)
        print_message(MessageType.INFO, f'Updated <b>{response["ref"]} to {response["object"]["sha"]}</b>')


class TreeviewTooltip:
    def __init__(self, github_client, org_combo, repo_combo, treeview, tooltip_func):
        self.github_client = github_client
        self.org_combo = org_combo
        self.repo_combo = repo_combo
        self.treeview = treeview
        self.tooltip_func = tooltip_func
        self.tip_window = None
        self.treeview.bind("<Button-1>", self.on_left_click)
        self.treeview.bind("<Leave>", self.on_leave)

    def on_left_click(self, event):
        item = self.treeview.identify_row(event.y)
        if not item:
            self.hide_tooltip()
            return

        if self.treeview.tag_has('has_tooltip', item):
            if not self.tip_window:
                self.show_tooltip(item, event.x, event.y)
        else:
            self.hide_tooltip()

    def show_tooltip(self, item, x, y):
        text = None
        try:
            text = self.tooltip_func(self.github_client, self.org_combo, self.repo_combo, self.treeview, item)
        except Exception as e:
            handle_and_print_exception(e)
        if text:
            self.tip_window = tw = tk.Toplevel(self.treeview)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x+20+self.treeview.winfo_rootx()}+{y+10+self.treeview.winfo_rooty()}")
            label = tk.Label(tw, text=text, justify=tk.LEFT, background="#ffffe0", relief=tk.SOLID, borderwidth=1, font=font.Font(family="Consolas", size=8))
            label.pack(ipadx=1)

    def hide_tooltip(self):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

    def on_leave(self, event):
        self.hide_tooltip()


def get_path(tree, item):
    path = []
    while item:
        path.append(tree.item(item, 'text'))
        item = tree.parent(item)
    return '/'.join(reversed(path))


def tooltip_text(github_client, org_combo, repo_combo, treeview, item):
    # This function should return the tooltip text for the given item
    org_name = org_combo.get()
    repo_name = repo_combo.get()
    branch_name = get_path(treeview, item)
    submodules_info = None
    try:
        # get submodules info
        submodules_info = get_submodules_info(github_client, org_name, repo_name, branch_name)
        submodules_info =[sub_m_info + (get_submodules_info(github_client, org_name, sub_m_info[1], sub_m_info[2]),) for sub_m_info in submodules_info]
        submodules_hierarchy_string = f"R:{repo_name} B:{branch_name}\n" + build_hierarchy(submodules_info, format_output, get_sublist)
        return submodules_hierarchy_string
    except Exception as e:
        handle_and_print_exception(e)
        # extend with sub sub module info
class App:
    # Initialize the application with GitHub client, organization, and repository details
    def __init__(self, root, github_client, org, repo, credentials_saved, config_path, team):
        self.root = root
        self.github_client = github_client
        self.default_org = org
        self.default_repo = repo
        self.default_team = team
        self.last_tree_item_rightclicked = None
        self.setup_ui()
        self.setup_actions()
        self.username = self.github_client.get_username()
        self.config_path = config_path
        print_message(MessageType.INFO, f'Connected to GitHub with user: <b>{self.username}</b>.')
        print_message(MessageType.INFO, f'Using organization: <b>{self.default_org}</b>, repository: <b>{self.default_repo}</b>')
        if credentials_saved:
            print_message(MessageType.INFO, "Credentials for <b>'BranchBrowser'</b> have been saved successfully.")

    def setup_ui(self):
        self.menu_bar = tk.Menu(self.root)
        self.refresh_menu = tk.Menu(self.menu_bar,tearoff=False)
        self.github_token_menu = tk.Menu(self.menu_bar,tearoff=False)
        self.github_token_menu.add_command(label="Update GitHub token", command=self.update_github_token)
        self.menu_bar.add_cascade(label="GitHub token", menu=self.github_token_menu)
        self.menu_bar.add_command(label="Refresh", command=self.refresh)
        self.menu_bar.add_command(label="Edit config", command=self.open_config_dialog)

        self.root.config(menu=self.menu_bar)
        self.treeview_frame = tk.Frame(self.root, width=300)
        self.treeview_frame.pack_propagate(False)
        self.treeview_frame.pack(side='left', fill='y')
        self.vertical_scrollbar = Scrollbar(self.treeview_frame, orient=tk.VERTICAL)
        self.vertical_scrollbar.pack(side=RIGHT, fill=Y)
        
        self.horizontal_scrollbar = Scrollbar(self.treeview_frame, orient=tk.HORIZONTAL)
        self.horizontal_scrollbar.pack(side=BOTTOM, fill=X)
        
        self.branches_tree = ttk.Treeview(self.treeview_frame, selectmode="none", yscrollcommand=self.vertical_scrollbar.set, xscrollcommand=self.horizontal_scrollbar.set)
        self.branches_tree.pack(fill=tk.BOTH, expand=True)
        self.branches_tree.column("#0", stretch=False)
        
        self.vertical_scrollbar.config(command=self.branches_tree.yview)
        self.horizontal_scrollbar.config(command=self.branches_tree.xview)
        
        self.contents_frame = tk.Frame(self.root)
        self.contents_frame.pack(side='right', fill='both', expand=True)
        self.menu = tk.Menu(self.contents_frame, tearoff=0)

        self.username = self.github_client.get_username()
        self.username_label = tk.Label(self.contents_frame, text=f"Logged in as: {self.username}")
        self.username_label.pack(side='top', fill='x')


        self.orgs = self.github_client.get_organizations_names()
        self.org_label = tk.Label(self.contents_frame, text="Organization:")
        self.org_label.pack(side='top', fill='x')
        self.org_combo = ttk.Combobox(self.contents_frame, values=self.orgs)
        self.org_combo['state'] = 'readonly'
        self.org_combo.pack(side='top', fill='x')

        self.repo_label = tk.Label(self.contents_frame, text="Repository:")
        self.repo_label.pack(side='top', fill='x')
        self.repo_combo = ttk.Combobox(self.contents_frame)
        self.repo_combo['state'] = 'readonly'
        self.repo_combo.pack(side='top', fill='x')

        # Initialize the tooltip functionality for the treeview
        TreeviewTooltip(self.github_client, self.org_combo, self.repo_combo, self.branches_tree, tooltip_text)

        self.log_label = tk.Label(self.contents_frame, text="Log:")
        self.log_label.pack(side='top', fill='x')
        log_text = tk.Text(self.contents_frame, state='disabled')  # Create a Text widget

        self.vertical_log_scrollbar = Scrollbar(self.contents_frame, orient=tk.VERTICAL, command=log_text.yview)
        self.vertical_log_scrollbar.pack(side=RIGHT, fill=Y)
        
        log_text.pack(side='top', fill='both', expand=True)
        log_text.config(yscrollcommand=self.vertical_log_scrollbar.set)
                
        # Redirect stdout to the Text widget
        sys.stdout = TextHandler(log_text)

    def recurse_children(self, item, open):
        self.branches_tree.item(item, open=open)  
        for child in self.branches_tree.get_children(item):
            self.recurse_children(child, open)

    def expand_all(self):
        item_sel = self.last_tree_item_rightclicked
        self.recurse_children(item_sel, True)

    def collapse_all(self):
        item_sel = self.last_tree_item_rightclicked
        self.recurse_children(item_sel, False)

    def setup_actions(self):
        self.branches_tree.bind('<Button-3>', self.on_right_click)
        self.org_combo.bind('<<ComboboxSelected>>', self.update_repos)
        self.repo_combo.bind('<<ComboboxSelected>>', self.update_tree)
        if self.default_org in self.orgs:
            org_index = self.orgs.index(self.default_org)
            self.org_combo.current(org_index)
            self.update_repos(None)

    # Refresh branches tree view with the latest branch structure for selected organization and repository
    def refresh_branches_by_config(self):
        org_name = self.org_combo.get()
        repo_name = self.repo_combo.get()
        branches_structure = self.github_client.get_repo_branches_structure(org_name, repo_name)
        self.clear_branches_tree()
        
        heading_text=f'Branches on {self.org_combo.get()}/{self.repo_combo.get()}'
        self.branches_tree.heading("#0", text = heading_text, anchor=tk.W)
        text_width = tk.font.Font().measure(heading_text)
        self.branches_tree.column("#0", width=text_width, stretch=False)
        self.populate_tree(self.branches_tree, branches_structure)


    def clear_branches_tree(self):
        self.branches_tree.delete(*self.branches_tree.get_children())

    # Recursively populate branches tree with nested branch structure
    def populate_tree(self, tree, node, parent=''):
        if isinstance(node, dict):
            for k, v in node.items():
                if len(v) != 0:
                    new_node = tree.insert(parent, 'end', text=k, tags=("branch_tree",))
                else:
                    new_node = tree.insert(parent, 'end', text=k, tags=("branch_tree", "has_tooltip",))
                self.populate_tree(tree, v, new_node)
        elif isinstance(node, list):
            for v in node:
                tree.insert(parent, 'end', text=v, tags=("branch_tree", "has_tooltip",))
                
    # Update repository combo box based on selected organization and set default if available
    def update_repos(self, event):
        org_name = self.org_combo.get()
        repos = self.github_client.get_organization_repos_names(org_name)
        self.repo_combo['values'] = repos
        if self.default_repo in repos:
            repo_index = repos.index(self.default_repo)
            self.repo_combo.current(repo_index)
        elif repos:
            self.repo_combo.current(0)
        
        self.update_tree(None)

    # Refresh tree view with branches from the selected repository
    def update_tree(self, event):
        self.refresh_branches_by_config()

    # Opens a configuration dialog for selecting organization, repository, and hostname.
    def open_config_dialog(self):
        config_dialog = tk.Toplevel(self.root)
        config_dialog.title("Edit Configuration")

        dialog_width = 300
        dialog_height = 300
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        position_top = int(screen_height / 2 - dialog_height / 2)
        position_left = int(screen_width / 2 - dialog_width / 2)

        config_dialog.geometry(f'{dialog_width}x{dialog_height}+{position_left}+{position_top}')

        organizations = self.github_client.get_organizations_names()  
        if not organizations:
            messagebox.showwarning("No Organizations", "No organizations found.")
            return

        org_label = tk.Label(config_dialog, text="Select GitHub organization:")
        org_label.pack(anchor='w',pady=5, padx=50)

        org_combobox = ttk.Combobox(config_dialog, values=organizations, width=30, state="readonly")
        org_combobox.set(self.default_org)  
        org_combobox.pack(anchor='w',pady=5, padx=50)

        repo_label = tk.Label(config_dialog, text="Select GitHub repository:")
        repo_label.pack(anchor='w',pady=5, padx=50)

        repo_combobox = ttk.Combobox(config_dialog, values=[], width=30, state="readonly")
        repo_combobox.set(self.default_repo)  
        repo_combobox.pack(anchor='w',pady=5, padx=50)

        team_label = tk.Label(config_dialog, text="Select team:")
        team_label.pack(anchor='w', pady=5, padx=50)

        team_combobox = ttk.Combobox(config_dialog, values=[], width=30,  state="readonly")
        team_combobox.set(self.default_team) 
        team_combobox.pack(anchor='w', pady=5, padx=50)

        git_hostname_label = tk.Label(config_dialog, text="Enter GitHub hostname:")
        git_hostname_label.pack(anchor='w',pady=5, padx=50)

        git_hostname_entry = tk.Entry(config_dialog, width=40)
        git_hostname_entry.insert(0, 'github.com')  
        git_hostname_entry.pack(anchor='w',pady=5, padx=50)
        
        def load_repos_and_teams(org_name, repo_combobox, team_combobox):
            repositories = self.github_client.get_organization_repos_names(org_name)
            if not repositories:
                messagebox.showwarning("No Repositories", "No repositories found for the selected organization.")
                return
            repo_combobox['values'] = repositories
            repo_combobox.set(self.default_repo) 
            
            teams = self.github_client.get_organization_teams(org_name)
            if not teams:
                messagebox.showwarning("No Teams", "No teams found for the selected organization.")
                return
            team_combobox['values'] = teams
            if self.default_team and self.default_team in teams:
                team_combobox.set(self.default_team)
            else:
                team_combobox.set(teams[0])  # Set to the first available team if default is not found

        def on_org_select(event):
            selected_org = org_combobox.get()
            load_repos_and_teams(selected_org, repo_combobox, team_combobox)

        org_combobox.bind("<<ComboboxSelected>>", on_org_select)

        # Initialize repositories and teams for the default organization on dialog open
        load_repos_and_teams(self.default_org, repo_combobox, team_combobox)

        def on_save():
            new_org = org_combobox.get()
            new_repo = repo_combobox.get()
            new_team = team_combobox.get()
            new_git_hostname = git_hostname_entry.get()

            if all([new_org, new_repo, new_git_hostname, new_team]):
                config = {
                    'default_organization': new_org,
                    'default_repository': new_repo,
                    'default_team': new_team,
                    'GIT_HOSTNAME': new_git_hostname
                }

                self.save_config(config)
                self.default_team = new_team
                messagebox.showinfo("Success", "Configuration updated and saved.")
                self.update_main_display(new_org, new_repo, new_team)
                self.refresh_branches_by_config()
                config_dialog.destroy()
            else:
                messagebox.showwarning("Input Error", "All fields must be provided.")

        save_button = tk.Button(config_dialog, text="Save", command=on_save)
        save_button.pack(side='left', pady=10, padx=50)

        def on_cancel():
            print("Configuration editing canceled")
            config_dialog.destroy()

        cancel_button = tk.Button(config_dialog, text="Cancel", command=on_cancel)
        cancel_button.pack(side='right',pady=10,padx=50)

    # Load configuration settings from 'config.json', or use defaults if file is missing or invalid
    @staticmethod
    def load_config():
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        if not os.path.exists(config_path):
            print(f"Config file {config_path} not found. Using default values.")
            return None
        
        try:
            with open(config_path, "r") as config_file:
                config = json.load(config_file)
                return config
        except json.JSONDecodeError:
            print(f"Error decoding JSON from config file {config_path}. Using default values.")
            return None  
        except IOError as e:
            print(f"IOError: {e} - There was an issue accessing the file {config_path}.")
            return None
        except Exception as e:
            print(f"Unexpected error loading config: {e}")
            return None
        except FileNotFoundError:
            print(f"Config file {config_path} not found. Using default values.")
            return None
          
    # Saves the provided configuration data to a file     
    def save_config(self, config):
        try:
            with open(self.config_path, "w") as config_file:
                json.dump(config, config_file, indent=4)
            print(f"Config saved to {self.config_path}")
        except TypeError as e:
            print(f"TypeError: {e} - The object is not serializable to JSON.")
        except IOError as e:
            print(f"IOError: {e} - There was an issue with the file {self.config_path}.")
        except ValueError as e:
            print(f"ValueError: {e} - The data is not valid for JSON serialization.")
        except json.JSONDecodeError as e:
            print(f"JSONDecodeError: {e} - There was an error decoding the JSON data.")
        except Exception as e:
            print(f"Unexpected error saving config: {e}")
            
    # Updates the main display with new organization and repository settings        
    def update_main_display(self, new_org, new_repo, team): 
        self.default_org = new_org
        self.default_repo = new_repo

        self.org_combo['values'] = self.github_client.get_organizations_names()
        self.repo_combo['values'] = self.github_client.get_organization_repos_names(self.default_org)

        self.org_combo.set(self.default_org)
        self.repo_combo.set(self.default_repo)
        print(f'Using organization: {self.default_org}, repository: {self.default_repo}, team: {team}') 
            
    def fetch_data(self):
        self.update_repos(None)
        self.orgs = self.github_client.get_organizations_names()
        self.org_combo['values'] = self.orgs
         
    def refresh(self):
        self.clear_branches_tree()
        self.branches_tree.heading("#0", text="Please wait. Refreshing data...", anchor=tk.W)
        thread = threading.Thread(target=self.fetch_data)
        thread.start()
                
    def on_right_click(self, event):
        self.menu.delete(0, 'end')  # Clear the menu

        item = self.branches_tree.identify('item', event.x, event.y)

        if len(self.branches_tree.get_children(item)) == 0:  # Check if the item is a leaf node (no children) 
            self.menu.add_command(label="Create Branch", command=self.create_branch)
            self.menu.add_command(label="Delete Branch", command=self.delete_branch)
            self.menu.add_command(label="Manage Submodules", command=self.manage_submodules)
            org_name = self.org_combo.get()
            repo_name = self.repo_combo.get()
            if org_name.endswith(repo_name):
                self.menu.add_command(label="Create Feature Branch", command=self.create_feature_branch)
            if org_name.endswith(repo_name):
                self.menu.add_command(label="Create Release Branch", command=self.create_release_branch)
        else:
            self.menu.add_command(label="Expand all", command=self.expand_all)
            self.menu.add_command(label="Colapse all", command=self.collapse_all)
            
        self.last_tree_item_rightclicked = item
        self.menu.post(event.x_root, event.y_root)

    def create_branch(self):
        org_name = self.org_combo.get()
        repo_name = self.repo_combo.get()
        selected_item = self.last_tree_item_rightclicked
        branch_name = get_path(self.branches_tree, selected_item)
        message = f"Creating branch from <b>{branch_name} on {org_name}/{repo_name}</b>."
        print_message(MessageType.INFO, message)
        new_branch = CloneDialog(self.root, self.github_client, org_name, repo_name, branch_name).result
        # Check the result
        if new_branch:
            message = f"New branch created: <b>{new_branch} on {org_name}/{repo_name}</b>."
            print_message(MessageType.INFO, message)
            self.update_tree(None) # Update tree to reflect changes
        else:
            message = f"Creating branch from <b>{branch_name} on {org_name}/{repo_name}</b> canceled!"
            print_message(MessageType.WARNING, message)

    def delete_branch(self):
        org_name = self.org_combo.get()
        repo_name = self.repo_combo.get()
        selected_item = self.last_tree_item_rightclicked
        branch_name = get_path(self.branches_tree, selected_item)
        message = f"Deleting branch from <b>{branch_name} on {org_name}/{repo_name}</b>."
        print_message(MessageType.INFO, message)
        result = DeleteDialog(self.root, self.github_client, org_name, repo_name, branch_name).result
        # Check the result
        if result:
            print_message(MessageType.INFO, f"Branch deleted: <b>{branch_name} on {org_name}/{repo_name}<b>.")
            self.branches_tree.delete(selected_item)
        else:
            message = f"Deleting branch <b>{branch_name} on {org_name}/{repo_name}</b> canceled!"
            print_message(MessageType.WARNING, message)
            
    def update_github_token(self):
        token_dialog = TokenDialog(self.root)
        updated_token = token_dialog.result
        if not updated_token:
            return
        try:
            # Checking if the entered GitHub token is valid
            test_github_client = GitHubClient(GIT_HOSTNAME, updated_token) 
            save_credentials("BranchBrowser", "github_token", updated_token)
            print("Credentials for 'BranchBrowser' have been saved successfully.")
        except Exception as e:
            handle_and_print_exception(e, 'Token not valid.')

        
    def manage_submodules(self):
        org_name = self.org_combo.get()
        repo_name = self.repo_combo.get()
        team_names = self.github_client.get_organization_teams(org_name)
        selected_item = self.last_tree_item_rightclicked
        branch_name = get_path(self.branches_tree, selected_item)
        print_message(MessageType.INFO, f"Manage submodules for <b>{branch_name} on {org_name}/{repo_name}</b>.")
        SubmoduleSelectorDialog(self.root, self.github_client, org_name, repo_name, team_names, branch_name, self.update_tree)

    
    def create_feature_branch(self):
        org_name = self.org_combo.get()
        repo_name = self.repo_combo.get()
        selected_item = self.last_tree_item_rightclicked
        branch_name = get_path(self.branches_tree, selected_item)
        print_message(MessageType.INFO, f"Create feature branch for <b>{branch_name} on {org_name}/{repo_name}</b>.")
        CreateFeatureBranchDialog(self.root, self.github_client, org_name, repo_name, branch_name, self.update_tree, self.config_path)

    def create_release_branch(self):
        org_name = self.org_combo.get()
        repo_name = self.repo_combo.get()
        selected_item = self.last_tree_item_rightclicked
        branch_name = get_path(self.branches_tree, selected_item)
        print_message(MessageType.INFO, f"Create release branch for <b>{branch_name} on {org_name}/{repo_name}</b>.")
        CreateReleaseBranchDialog(self.root, self.github_client, org_name, repo_name, branch_name, self.update_tree)
    

class TokenDialog(simpledialog.Dialog):
    def __init__(self, parent, message = None):
        self.message = message
        super().__init__(parent, "GitHub Token")

    def body(self, master):
        self.resizable(False, False)
        if self.message:
            tk.Label(master, text=self.message).grid(row=0, columnspan=2, sticky="w")
        tk.Label(master, text="Enter your GitHub token:").grid(row=1)
        self.token = tk.Entry(master, show='*', width=40)
        self.token.grid(row=1, column=1)
        return self.token # initial focus

    def apply(self):
        self.result = self.token.get()


class CloneDialog(simpledialog.Dialog):
    def __init__(self, parent, github_client, org_name, repo_name, branch_name):
        self.github_client = github_client
        self.org_name = org_name
        self.repo_name = repo_name
        self.branch_name = branch_name

        # Call the superclass's __init__ method
        super().__init__(parent)

    def body(self, master):
        self.resizable(False, False)
        self.title(f"Clone branch for {self.org_name}/{self.repo_name}")

        tk.Label(master, text="Enter new branch name:").grid(row=0)
        self.new_branch_name = tk.Entry(master, width=60)
        self.new_branch_name.insert(0, self.branch_name)
        self.new_branch_name.grid(row=0, column=1)

        tk.Label(master, text="Enter commit sha:").grid(row=1)
        self.source_commit_sha = tk.Entry(master, width=60)
        self.source_commit_sha.insert(0, self.github_client.get_organization_repo_branch_commit_sha(self.org_name, self.repo_name, self.branch_name))
        self.source_commit_sha.grid(row=1, column=1)

        return self.new_branch_name # initial focus

    def apply(self):
        self.github_client.organization_repo_create_branch(self.org_name, self.repo_name, self.new_branch_name.get(), self.source_commit_sha.get())
        self.result = self.new_branch_name.get()
        print_message(MessageType.INFO, f"Created new branch <b>{self.result}</b>.")
        


class DeleteDialog(simpledialog.Dialog):
    def __init__(self, parent, github_client, org_name, repo_name, branch_name):
        self.github_client = github_client
        self.org_name = org_name
        self.repo_name = repo_name
        self.branch_name = branch_name

        # Call the superclass's __init__ method
        super().__init__(parent)

    def body(self, master):
        self.resizable(False, False)
        self.title(f"Delete branch for {self.org_name}/{self.repo_name}")

        tk.Label(master, text=f"Are you sure you want to delete {self.branch_name}").grid(row=0)

    def apply(self):
        self.github_client.organization_repo_delete_branch(self.org_name, self.repo_name, self.branch_name)
        print_message(MessageType.INFO, f"Deleted branch <b>{self.branch_name}</b>.")
        self.result = self.branch_name


class RepoBranchListBoxInfo:
    def __init__(self, repo, branch, path = None, listbox_position = None):
        self._repo = repo
        self._branch = branch
        self._path = path
        self._listbox_position = listbox_position
        self._used = False

    def __str__(self):
        return f'R:{self._repo} B:{self._branch}'

    def __hash__(self):
        return hash(self._repo + self._branch)

    def __eq__(self, other):
        if isinstance(other,  RepoBranchListBoxInfo):
            return self._repo == other.repo and self._branch == other.branch
        return False

    def set_used(self, used):
        self._used = used

    @property
    def used(self):
        return self._used

    @property
    def position(self):
        return self._listbox_position

    @property
    def repo(self):
        return self._repo

    @property
    def path(self):
        return self._path

    @property
    def branch(self):
        return self._branch


class SubmoduleSelectorDialog(simpledialog.Dialog):
    def __init__(self, parent, github_client, org_name, repo_name, team_names, branch_name, update_tree):
        self.repo_branch_right_lb_info_map = dict()
        self.repo_branch_left_lb_info_list = list()

        self.github_client = github_client
        self.org_name = org_name
        self.repo_name = repo_name
        self.team_names = team_names
        self.branch_name = branch_name
        self.update_tree = update_tree

        # Call the superclass's __init__ method
        super().__init__(parent)

    def move_to_right(self):
        # Move selected item from left to right - add submodule
        selected = self.submodules_left_listbox.curselection()
        if selected:
            selected_item = self.submodules_left_listbox.get(selected)
            if selected_item in self.repo_branch_right_lb_info_map: # if we have item on right set set unused and set color to default (black)
                repo_branch_lb_info = self.repo_branch_right_lb_info_map[selected_item]
                self.repo_branches_right_listbox.itemconfig(repo_branch_lb_info.position, {'fg': 'black'})
                repo_branch_lb_info.set_used(False)
            self.submodules_left_listbox.delete(selected)

    def move_to_left(self):
        # Move selected item from right to left - remove submodule
        selected = self.repo_branches_right_listbox.curselection()
        if selected:
            selected_item = self.repo_branches_right_listbox.get(selected)
            repo_branch_lb_info = self.repo_branch_right_lb_info_map[selected_item]
            if not repo_branch_lb_info.used: # set used and mark red color
                self.repo_branches_right_listbox.itemconfig(repo_branch_lb_info.position, {'fg': 'red'})
                repo_branch_lb_info.set_used(True)
                self.submodules_left_listbox.insert(tk.END, selected_item)


    def extract_feature_versions(self, team_name):
        filtered_branches = [branch for branch in self.branches if branch.startswith(f"Features/{team_name}")]
        feature_versions = list({branch.split("/")[-2] for branch in filtered_branches})
        sorted_feature_versions = sorted(feature_versions, key=lambda v: float(v))
        return sorted_feature_versions

    def update_repo_branches_right_listbox(self, event = None):
        # Get the selected values of the repo name and branch type comboboxes
        repo_name = self.repos_combobox.get()
        branch_type = self.branch_type_combobox.get()

        if event and event.widget == self.repos_combobox:
            self.branches = self.github_client.get_organization_repo_branches(self.org_name, repo_name)
        elif event and event.widget == self.branch_type_combobox and branch_type == "Release":
            # Changing the text of the team/version label to "Version:"
            self.team_version_label.config(text="Version:")

            # Getting only the release branches
            release_branches = [branch for branch in self.branches if branch.startswith("Release")]
            # Getting the versions such as 1.0, 2.0 etc.
            versions = list({branch.split("/")[1] for branch in release_branches})
            # Sorting the versions by their numerical value
            sorted_versions = sorted(versions, key=lambda v: float(v))
            # Setting the extracted versions as the values for the team/version combobox
            self.team_version_combobox['values'] = sorted_versions
            self.team_version_combobox.current(0)

            # Removing the feature version label and combobox from the UI
            self.feature_version_label.grid_forget()
            self.feature_version_combobox.grid_forget()
        elif event and event.widget == self.branch_type_combobox and branch_type == "Features":
            # Changing the text of the team/version label to "Team:"
            self.team_version_label.config(text="Team:")
            
            # Setting the team names to be values for the team/version combobox
            self.team_version_combobox['values'] = self.team_names
            self.team_version_combobox.current(0)

            # Adding the feature version label and combobox back to the UI
            self.feature_version_label.grid(row=3, column=0, sticky="w", pady=(0, 5))
            self.feature_version_combobox.grid(row=3, column=1, pady=(0, 5))

        self.repo_branch_right_lb_info_map.clear()

        # Get the selected value of the team/version combobox
        team_version = self.team_version_combobox.get()

        # If any combobox other than feature version combobox changes and we are looking at feature branches
        # it should update the feature version combobox with the appropriate values
        if event and event.widget != self.feature_version_combobox and branch_type == "Features":
            sorted_feature_versions = self.extract_feature_versions(team_version)
            self.feature_version_combobox['values'] = sorted_feature_versions
            if len(sorted_feature_versions) > 0:
                self.feature_version_combobox.current(0)
            else:
                self.feature_version_combobox.set("")

        # Clear the listbox
        self.repo_branches_right_listbox.delete(0, tk.END)

        filtered_branches = [branch for branch in self.branches if branch.startswith(f"{branch_type}/{team_version}")]
        # If showing feature branches filter by feature version too
        if branch_type == "Features":
            # Get the selected value of the feature version combobox
            feature_version = self.feature_version_combobox.get()
            filtered_branches = [branch for branch in filtered_branches if feature_version in branch]

        # Update the repo branches right listbox based on the selected values of the comboboxes
        for index, branch in enumerate(filtered_branches):
            repo_branch_lb_info = RepoBranchListBoxInfo(repo_name, branch, listbox_position=index)
            repo_branch_lb_info.set_used(str(repo_branch_lb_info) in self.submodules_left_listbox.get(0, tk.END))
            self.repo_branch_right_lb_info_map[str(repo_branch_lb_info)] = repo_branch_lb_info
            self.repo_branches_right_listbox.insert(tk.END, repo_branch_lb_info)
            if repo_branch_lb_info.used:
                self.repo_branches_right_listbox.itemconfig(index, {'fg': 'red'})

    def init_submodules_left_listbox(self):
        submodules_info = get_submodules_info(self.github_client, self.org_name, self.repo_name, self.branch_name)

        for _, repo_name, branch_name, submodule_path in submodules_info:
            submodule_info = RepoBranchListBoxInfo(repo_name, branch_name, submodule_path)
            self.submodules_left_listbox.insert(tk.END, submodule_info)
            self.repo_branch_left_lb_info_list.append(submodule_info)

    def buttonbox(self):
        # Add the "Update" button
        w = tk.Button(self, text="Update", width=10, command=self.update_action)
        w.pack(side=tk.LEFT, padx=5, pady=5)
        super().buttonbox()  # Include the default OK and Cancel buttons

    def update_action(self):
        print_message(MessageType.INFO, f"Updating current submodules to HEAD revision on <b>{self.org_name}/{self.repo_name}/{self.branch_name}</b>.")
        original = set(self.repo_branch_left_lb_info_list)

        # Do the modification
        repo_submodule_manager = GitHubRepoSubmoduleManager(self.org_name, self.repo_name, token)

        updated = []
        for orig_submodule in original:
            if repo_submodule_manager.add_or_update_submodule(self.branch_name, orig_submodule.repo, orig_submodule.path):
                updated.append(orig_submodule.repo)

        print_message(MessageType.INFO, f"Updated <b>{updated}</b> submodules to HEAD revision on <b>{self.org_name}/{self.repo_name}/{self.branch_name}</b>.")
        super().cancel()

    def body(self, master):
        # Disable resizing of the dialog
        self.resizable(False, False)
        self.title(f'Manage submodules for {self.org_name}/{self.repo_name}/{self.branch_name}')

        # Create right container frame
        self.left_frame = tk.Frame(master, width=90, height=40)
        self.left_label = tk.Label(self.left_frame, text="Submodules:")
        # Create listboxes
        self.submodules_left_listbox = tk.Listbox(self.left_frame, width=90, height=40)

        # Create right container frame
        self.right_frame = tk.Frame(master, width=90, height=40)

        org_repos_names = self.github_client.get_organization_repos_names(self.org_name)
        org_repos_names.remove(self.repo_name)
        org_repos_names.sort()

        # Create combobox and label for repos names
        self.repo_label = tk.Label(self.right_frame, text="Repository:")
        self.repos_combobox = ttk.Combobox(self.right_frame, 
                                           width=75, 
                                           values=org_repos_names, 
                                           state="readonly")
        self.repos_combobox.bind('<<ComboboxSelected>>', self.update_repo_branches_right_listbox)
        # Set the first item as selected
        self.repos_combobox.current(0)

        # Create combobox and label for branch type (Feature/Release)
        self.branch_type_label = tk.Label(self.right_frame, text="Branch type:")
        self.branch_type_combobox = ttk.Combobox(self.right_frame, 
                                                 width=75, 
                                                 values=["Features", "Release"], 
                                                 state="readonly")
        self.branch_type_combobox.bind('<<ComboboxSelected>>', self.update_repo_branches_right_listbox)
        self.branch_type_combobox.current(0)

        # Create combobox and label for teams/versions
        self.team_version_label = tk.Label(self.right_frame, text="Team:")
        self.team_version_combobox = ttk.Combobox(self.right_frame, 
                                                  width=75, 
                                                  values=self.team_names, 
                                                  state="readonly")
        self.team_version_combobox.bind('<<ComboboxSelected>>', self.update_repo_branches_right_listbox)
        self.team_version_combobox.current(0)

        # Setting the initial value for branches
        self.branches = self.github_client.get_organization_repo_branches(self.org_name, self.repos_combobox.get())
        # Setting the initial values for the feature versions combobox
        sorted_feature_versions = self.extract_feature_versions(self.team_version_combobox.get())

        # Create combobox and label for feature versions
        self.feature_version_label = tk.Label(self.right_frame, text="Version:")
        self.feature_version_combobox = ttk.Combobox(self.right_frame, 
                                                     width=75, 
                                                     values=sorted_feature_versions, 
                                                     state="readonly")
        self.feature_version_combobox.bind('<<ComboboxSelected>>', self.update_repo_branches_right_listbox)
        self.feature_version_combobox.current(0)

        # Create right listbox
        self.repo_branches_right_listbox = tk.Listbox(self.right_frame, width=90, height=40)

        # Create buttons
        button_right = tk.Button(master, text=">", command=self.move_to_right)
        button_left = tk.Button(master, text="<", command=self.move_to_left)

        # Creating a layout of the components
        self.left_frame.grid(row=0, column=0, sticky="s")
        self.left_label.grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.submodules_left_listbox.grid(row=1, column=0)

        button_left.grid(row=0, column=1)
        button_right.grid(row=0, column=2)

        self.right_frame.grid(row=0, column=3)
        self.repo_label.grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.repos_combobox.grid(row=0, column=1, pady=(0, 5))
        self.branch_type_label.grid(row=1, column=0, sticky="w", pady=(0, 5))
        self.branch_type_combobox.grid(row=1, column=1, pady=(0, 5))
        self.team_version_label.grid(row=2, column=0, sticky="w", pady=(0, 5))
        self.team_version_combobox.grid(row=2, column=1, pady=(0, 5))
        self.feature_version_label.grid(row=3, column=0, sticky="w", pady=(0, 5))
        self.feature_version_combobox.grid(row=3, column=1, pady=(0, 5))
        self.repo_branches_right_listbox.grid(row=4, column=0, columnspan=2)

        # Initialize current state of submodules for current org/repo/branch
        self.init_submodules_left_listbox()

        # Call the update_listbox function
        self.update_repo_branches_right_listbox()

    def cancel(self, event=None):
        print_message(MessageType.WARNING, f"Manage submodules for <b>{self.branch_name} on {self.org_name}/{self.repo_name}</b> canceled!")
        super().cancel()  # Ensure the base class cancel method is called

    def apply(self, event=None):
        # Show a processing popup
        self.processing_popup = tk.Toplevel(self)
        self.processing_popup.geometry("200x50")
        tk.Label(self.processing_popup, text="Processing... Please wait").pack()
        self.processing_popup.protocol("WM_DELETE_WINDOW", lambda: None) # Disable the close button
        self.processing_popup.grab_set()  # Make the popup modal

        self.submodules_left_listbox_val = self.submodules_left_listbox.get(0, tk.END)

        threading.Thread(target=self.process).start()

    def process(self):
        try:
            # Perform your action here
            print_message(MessageType.INFO, "Modifying submodules...")
            original = set(self.repo_branch_left_lb_info_list)
            modified = set([RepoBranchListBoxInfo(item.split()[0][2:], item.split()[1][2:]) for item in self.submodules_left_listbox_val])
            added = modified - original
            deleted = original - modified

            # Do the modification
            repo_submodule_manager = GitHubRepoSubmoduleManager(self.org_name, self.repo_name, token)

            for del_submodule in deleted:
                repo_submodule_manager.delete_submodule(self.branch_name, del_submodule.repo, del_submodule.path)

            for add_submodule in added:
                calculated_path = calculate_submodule_path(self.org_name, add_submodule.repo)
                repo_submodule_manager.add_or_update_submodule(self.branch_name, add_submodule.repo, calculated_path, add_submodule.branch)

            print_message(MessageType.INFO, f"Submodules updated for <b>{self.branch_name} on {self.org_name}/{self.repo_name}</b>.")
            # Convert the lists to strings
            deleted_str = ', '.join([item.repo for item in deleted])
            added_str = ', '.join([item.repo for item in added])
            # Print the result
            text = f"{MessageType.INFO.value} Added: <b>{added_str}</b> ; Deleted: <b>{deleted_str}</b>"
            print_message(MessageType.INFO, text)
            self.update_tree(None) # Update tree to reflect changes
        except Exception as e:
            handle_and_print_exception(e)

        finally:
            # Close the processing popup
            self.processing_popup.destroy()
            
class CreateFeatureBranchDialog(simpledialog.Dialog):
    def __init__(self, parent, github_client, org_name, repo_name, branch_name, update_tree, config_path):

        self.github_client = github_client
        self.org_name = org_name
        self.repo_name = repo_name
        self.branch_name = branch_name
        self.update_tree = update_tree

        if isinstance(config_path, str):
            try:
                with open(config_path, 'r') as file:
                    self.config = json.load(file)
            except IOError:
                print("Error: There was an issue reading the file.")
            except json.JSONDecodeError:
                print("Error: The file is not a valid JSON.")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
        else:
            self.config = config_path

        self.include_push = tk.BooleanVar(value=True) 
        # StringVar to hold the real-time preview of the path
        self.path_preview = tk.StringVar()
        self.default_team = self.config.get("default_team", "")
        # Call the superclass's __init__ method
        super().__init__(parent)

    def body(self, master):
        self.resizable(False, False)
        self.title(f'Create feature branch for {self.org_name}/{self.repo_name}/{self.branch_name}')

        tk.Label(master, text="Prefix that will be replaced by feature branch prefix:").grid(row=0, sticky='e')
        self.search_branch_prefix = tk.Entry(master, width=60)
        self.search_branch_prefix.insert(0, "Release")
        self.search_branch_prefix.grid(row=0, column=1)
        
        # Read-only entry for "Features"
        tk.Label(master, text="Feature branch prefix:").grid(row=1, sticky='e')
        self.feature_branch_prefix = tk.Entry(master, width=60)
        self.feature_branch_prefix.insert(0, "Features")
        self.feature_branch_prefix.configure(state='readonly')  
        self.feature_branch_prefix.grid(row=1, column=1, sticky='w')

        # Dropdown for team names
        tk.Label(master, text="Select team:").grid(row=3, column=0, sticky='e') 
        self.team_dropdown = ttk.Combobox(master, values=[], width=57, state="readonly")
        self.team_dropdown.grid(row=3, column=1, sticky='w')

        # Populate the dropdown with team names from GitHub
        self.populate_team_dropdown()

        # Checkbox for optional "Push" option
        tk.Label(master, text="Enable push option:").grid(row=4, column=0, sticky='e')
        self.include_push = tk.BooleanVar(value=True)  # Default is checked
        self.push_checkbox = tk.Checkbutton(master, variable=self.include_push)
        self.push_checkbox.grid(row=4, column=1, sticky='w')

        # Editable entry for "Feature-Bug"
        tk.Label(master, text="Feature/Bug description:").grid(row=5, column=0, sticky='e')
        self.feature_bug_entry = tk.Entry(master, width=60)
        self.feature_bug_entry.insert(0, "Feature-Bug")  # Default text
        self.feature_bug_entry.grid(row=5, column=1, sticky='w')

        # Preview label to display the real-time generated path
        tk.Label(master, text="Feature path preview:").grid(row=7, column=0, sticky='e')
        self.replace_feature_branch_prefix = tk.Entry(master, textvariable=self.path_preview, fg="blue",width=60, state="readonly")
        self.replace_feature_branch_prefix.grid(row=7, column=1, sticky='w')

        # Set up listeners to update the preview when fields change
        self.team_dropdown.bind("<<ComboboxSelected>>", lambda event: self.update_path_preview())
        self.feature_bug_entry.bind("<KeyRelease>", lambda event: self.update_path_preview())
        self.push_checkbox.config(command=self.update_path_preview)

        # Message to show when a space is entered
        self.space_warning = tk.Label(master, text="", fg="red")
        self.space_warning.grid(row=6, column=1, sticky='w')

        # Validation for the feature_bug_entry field
        self.feature_bug_entry.bind("<KeyRelease>", self.validate_no_space)

        # Initial preview setup
        self.update_path_preview()

        # get submodules info - only 1st level
        self.submodules_info = get_submodules_info(self.github_client, self.org_name, self.repo_name, self.branch_name)

        tk.Label(master, text="List of branches from which feature branches will be created:", font=('TkDefaultFont', 10, 'bold')).grid(row=8, sticky='w')

        submodules_hierarchy_string = f"R:{self.repo_name} B:{self.branch_name}\n" + build_hierarchy(self.submodules_info, format_output, get_sublist)

        tk.Label(master, text=submodules_hierarchy_string, justify=tk.LEFT, anchor='w', font=font.Font(family="Consolas", size=10)).grid(row=9, sticky='w')
    
    def validate_no_space(self, event):
        text = self.feature_bug_entry.get()
        
        # If there's a space in the text, highlight the entry and show the warning
        if ' ' in text:
            self.feature_bug_entry.config(bg="red")
            self.space_warning.config(text="Spaces are not allowed!")
        else:
            self.feature_bug_entry.config(bg="white")
            self.space_warning.config(text="")  # Clear the warning message when valid
        self.update_path_preview()
        
    # Use the GitHubClient to get team names for the organization
    def populate_team_dropdown(self):
        try:
            team_names = self.github_client.get_organization_teams(self.org_name)
            self.team_dropdown['values'] = team_names or []
            if self.default_team in team_names:
                    self.team_dropdown.set(self.default_team)
            else:
                    self.team_dropdown.set(team_names[0]) 
        except Exception as e:
            print(f"Error fetching team names: {e}")
            self.team_dropdown['values'] = []

    # Updates the path preview based on the selected feature prefix,
    # team name, and feature bug, including the "Push" option if selected.
    def update_path_preview(self):
        feature_prefix = self.feature_branch_prefix.get()
        team_name = self.team_dropdown.get()
        feature_bug = self.feature_bug_entry.get()

        if self.include_push.get():
            push_selected = "Push"
        else:
            push_selected = ""  # If "Push" is not selected, remove it entirely from the path

        # Build the path preview with or without "Push" between team_name and feature_bug
        if push_selected:
            full_path = os.path.join(feature_prefix, team_name, push_selected, feature_bug)
        else:
            full_path = os.path.join(feature_prefix, team_name, feature_bug)

        full_path = full_path.replace('\\', '/')
        self.path_preview.set(full_path)

    def cancel(self, event=None):
        print_message(MessageType.WARNING, f"Create feature branch for <b>{self.branch_name} on {self.org_name}/{self.repo_name}</b> canceled!")
        super().cancel()  # Ensure the base class cancel method is called

    def apply(self, event=None):
        # Show a processing popup
        self.processing_popup = tk.Toplevel(self.master)
        self.processing_popup.geometry("200x50")
        tk.Label(self.processing_popup, text="Processing... Please wait").pack()
        self.processing_popup.protocol("WM_DELETE_WINDOW", lambda: None) # Disable the close button
        self.processing_popup.grab_set()  # Make the popup modal

        self.search_branch_prefix_val = self.search_branch_prefix.get()
        self.replace_feature_branch_prefix_val = self.replace_feature_branch_prefix.get()

        threading.Thread(target=self.process).start()

    def process(self):
        try:
            # Perform your action here
            print_message(MessageType.INFO, "Creating feature branch structure...")

            # Create feature branch for submodule
            new_branch_name = self.branch_name.replace(self.search_branch_prefix_val, self.replace_feature_branch_prefix_val)

            # Validate if prefix replace will actually change branch name
            if new_branch_name == self.branch_name:
                print_message(MessageType.WARNING, f'Replace search branch prefix:<b>{self.search_branch_prefix_val}</b> has no effect on branch: <b>{self.branch_name}</b>. Nothing is being replaced.')
                return

            branch_commit_sha = self.github_client.get_organization_repo_branch_commit_sha(self.org_name, self.repo_name, self.branch_name)
            self.github_client.organization_repo_create_branch(self.org_name, self.repo_name, new_branch_name, branch_commit_sha)
            print_message(MessageType.INFO, f"Created new branch <b>{new_branch_name}</b> on top repo <b>{self.repo_name}</b>.")

            for sub_m_info in self.submodules_info:
                sub_m_repo_name = sub_m_info[1]
                sub_m_branch_name = sub_m_info[2]

                # Creeate feature branch for submodule
                new_sub_m_branch_name = sub_m_branch_name.replace(self.search_branch_prefix_val, self.replace_feature_branch_prefix_val)
                branch_commit_sha = self.github_client.get_organization_repo_branch_commit_sha(self.org_name, sub_m_repo_name, sub_m_branch_name)
                self.github_client.organization_repo_create_branch(self.org_name, sub_m_repo_name, new_sub_m_branch_name, branch_commit_sha)
                print_message(MessageType.INFO, f"Created new branch <b>{new_sub_m_branch_name}</b> on sub repo <b>{sub_m_repo_name}</b>.")

                # Now on new feature branch on top level connect all submodules with its new feature branches
                repo_submodule_manager = GitHubRepoSubmoduleManager(self.org_name, self.repo_name, token)
                # delete old submodule 
                repo_submodule_manager.delete_submodule(new_branch_name, sub_m_info[0], sub_m_info[3])
                # add new submodule
                repo_submodule_manager.add_or_update_submodule(new_branch_name, sub_m_info[0], sub_m_info[3], new_sub_m_branch_name)

            print_message(MessageType.INFO, f"Feature branch structure created for <b>{self.branch_name} on {self.org_name}/{self.repo_name}</b>.")
            self.update_tree(None) # Update tree to reflect changes

        except Exception as e:
            handle_and_print_exception(e)
        finally:
            # Close the processing popup
            self.processing_popup.destroy()    

class CreateReleaseBranchDialog(simpledialog.Dialog):
    def __init__(self, parent, github_client, org_name, repo_name, branch_name, update_tree):

        self.github_client = github_client
        self.org_name = org_name
        self.repo_name = repo_name
        self.branch_name = branch_name
        self.update_tree = update_tree

        # Call the superclass's __init__ method
        super().__init__(parent)

    def body(self, master):
        # Disable resizing of the dialog
        self.resizable(False, False)
        self.title(f'Create release branch for {self.org_name}/{self.repo_name}/{self.branch_name}')

        tk.Label(master, text="Enter search pattern (pattern that will be replaced by replacement pattern in every branch name):").grid(row=0, sticky='w')
        self.search_branch_pattern = tk.Entry(master, width=60)
        self.search_branch_pattern.insert(0, self.branch_name)
        self.search_branch_pattern.grid(row=0, column=1)

        tk.Label(master, text="Enter replacement pattern (pattern that will replace search pattern in every branch name):").grid(row=1, sticky='w')
        self.replace_branch_pattern = tk.Entry(master, width=60)
        self.replace_branch_pattern.insert(0, self.branch_name)
        self.replace_branch_pattern.grid(row=1, column=1)

        # get submodules info
        self.submodules_info = get_submodules_info(self.github_client, self.org_name, self.repo_name, self.branch_name)
        # extend with sub sub module info
        self.submodules_info =[sub_m_info + (get_submodules_info(self.github_client, self.org_name, sub_m_info[1], sub_m_info[2]),) for sub_m_info in self.submodules_info]

        tk.Label(master, text="List of branches from which new branches will be created:", font=('TkDefaultFont', 10, 'bold')).grid(row=2, sticky='w')

        submodules_hierarchy_string = f"R:{self.repo_name} B:{self.branch_name}\n" + build_hierarchy(self.submodules_info, format_output, get_sublist)

        tk.Label(master, text=submodules_hierarchy_string, justify=tk.LEFT, anchor='w', font=font.Font(family="Consolas", size=10)).grid(row=3, sticky='w')

    def cancel(self, event=None):
        print_message(MessageType.WARNING, f"Create release branch for <b>{self.branch_name} on {self.org_name}/{self.repo_name}</b> canceled!")
        super().cancel()  # Ensure the base class cancel method is called

    def apply(self, event=None):
        # Show a processing popup
        self.processing_popup = tk.Toplevel(self.master)
        self.processing_popup.geometry("200x50")
        tk.Label(self.processing_popup, text="Processing... Please wait").pack()
        self.processing_popup.protocol("WM_DELETE_WINDOW", lambda: None) # Disable the close button
        self.processing_popup.grab_set()  # Make the popup modal

        self.search_branch_pattern_val = self.search_branch_pattern.get()
        self.replace_branch_pattern_val = self.replace_branch_pattern.get()

        threading.Thread(target=self.process).start()

    def process(self):
        try:
            # Perform your action here
            print_message(MessageType.INFO, "Creating release branch structure...")

            # Creeate release branch for submodule
            new_branch_name = self.branch_name.replace(self.search_branch_pattern_val, self.replace_branch_pattern_val)

            # Validate if pattern replace will actually change branch name
            if new_branch_name == self.branch_name:
                print_message(MessageType.WARNING, f'Replace search branch pattern:<b>{self.search_branch_pattern_val}</b> has no effect on branch: <b>{self.branch_name}</b>. Nothing is being replaced.')
                return

            branch_commit_sha = self.github_client.get_organization_repo_branch_commit_sha(self.org_name, self.repo_name, self.branch_name)
            self.github_client.organization_repo_create_branch(self.org_name, self.repo_name, new_branch_name, branch_commit_sha)
            print_message(MessageType.INFO, f"Created new branch <b>{new_branch_name}</b> on top repo <b>{self.repo_name}</b>.")

            for sub_m_info in self.submodules_info:
                sub_m_repo_name = sub_m_info[1]
                sub_m_branch_name = sub_m_info[2]

                # Creeate release branch for submodule
                new_sub_m_branch_name = sub_m_branch_name.replace(self.search_branch_pattern_val, self.replace_branch_pattern_val)
                branch_commit_sha = self.github_client.get_organization_repo_branch_commit_sha(self.org_name, sub_m_repo_name, sub_m_branch_name)
                self.github_client.organization_repo_create_branch(self.org_name, sub_m_repo_name, new_sub_m_branch_name, branch_commit_sha)
                print_message(MessageType.INFO, f"Created new branch <b>{new_sub_m_branch_name}</b> on sub repo <b>{sub_m_repo_name}</b>.")

                for sub_sub_m_info in sub_m_info[4]:
                    sub_sub_m_repo_name = sub_sub_m_info[1]
                    sub_sub_m_branch_name = sub_sub_m_info[2]

                    # Creeate release branch for sub submodule
                    new_sub_sub_m_branch_name = sub_sub_m_branch_name.replace(self.search_branch_pattern_val, self.replace_branch_pattern_val)
                    branch_commit_sha = self.github_client.get_organization_repo_branch_commit_sha(self.org_name, sub_sub_m_repo_name, sub_sub_m_branch_name)
                    self.github_client.organization_repo_create_branch(self.org_name, sub_sub_m_repo_name, new_sub_sub_m_branch_name, branch_commit_sha)
                    print_message(MessageType.INFO, f"Created new branch <b>{new_sub_sub_m_branch_name}</b> on sub sub repo <b>{sub_sub_m_repo_name}</b>.")

                    # Now on new feature branch on first level submodule connect all sub submodules with its new feature branches
                    repo_submodule_manager = GitHubRepoSubmoduleManager(self.org_name, sub_m_repo_name, token)
                    # delete old submodule 
                    repo_submodule_manager.delete_submodule(new_sub_m_branch_name, sub_sub_m_info[0], sub_sub_m_info[3])
                    # add new submodule
                    repo_submodule_manager.add_or_update_submodule(new_sub_m_branch_name, sub_sub_m_info[0], sub_sub_m_info[3], new_sub_sub_m_branch_name)

                # Now on new feature branch on top level connect all submodules with its new feature branches
                repo_submodule_manager = GitHubRepoSubmoduleManager(self.org_name, self.repo_name, token)
                # delete old submodule 
                repo_submodule_manager.delete_submodule(new_branch_name, sub_m_info[0], sub_m_info[3])
                # add new submodule
                repo_submodule_manager.add_or_update_submodule(new_branch_name, sub_m_info[0], sub_m_info[3], new_sub_m_branch_name)

            print_message(MessageType.INFO, f"Release branch structure created for <b>{self.branch_name} on {self.org_name}/{self.repo_name}</b>.")
            self.update_tree(None) # Update tree to reflect changes

        except Exception as e:
            handle_and_print_exception(e)
        finally:
            # Close the processing popup
            self.processing_popup.destroy()         


def get_submodules_info(github_client, org_name, repo_name, branch_name):
    gitmodules_content = github_client.get_organization_repo_branch_gitmodules_content(org_name, repo_name, branch_name)
    gitmodules_config = configparser.ConfigParser(allow_no_value=True)
    gitmodules_config.read_string(gitmodules_content)

    submodules_info = []
    for section in gitmodules_config.sections():
        if "submodule" in section:
            # Extract the submodule name
            submodule_name = section.split('"')[1]
            
            # Get the path and url of the submodule
            submodule_path = gitmodules_config.get(section, "path")
            url = gitmodules_config.get(section, "url")

            # Calculate repo name from url
            repo_name = url.split("/")[-1].replace('.git', '')
            
            # The branch is optional, so we need to check if it exists
            if gitmodules_config.has_option(section, "branch"):
                branch_name = gitmodules_config.get(section, "branch")
                if branch_name == '.':
                    branch_name = branch_name  # default branch from top repo
            else:
                branch_name = branch_name  # default branch from top repo
    
            # Add the submodule info to the list
            submodules_info.append((submodule_name, repo_name, branch_name, submodule_path))

    return submodules_info


# Calculate submodule path (folder) - default is same as submodule repo name
def calculate_submodule_path(org_name, sub_repo_name):
    calculated_path = sub_repo_name

    return calculated_path


def build_hierarchy(strings, format_output, get_sublist, prefix=''):
    hierarchy = ''  # Initialize an empty string to build the hierarchy
    total_items = len(strings)
    
    for index, item in enumerate(strings, start=1):
        is_last = index == total_items  # Check if this is the last item
        
        # Use the format_output function to format the current item string
        formatted_item = format_output(item)
        if is_last:
            hierarchy += f"{prefix}╚═══{formatted_item}\n"
        else:
            hierarchy += f"{prefix}╠═══{formatted_item}\n"
        
        # Use the get_sublist function to get the sublist from the current item
        sublist = get_sublist(item)
        if sublist is not None:
            new_prefix = prefix + ("    " if is_last else "║   ")
            hierarchy += build_hierarchy(sublist, format_output, get_sublist, new_prefix)
    
    return hierarchy


def format_output(item):
    return f"R:{item[1]} B:{item[2]}" # 1 = repository name, 2 = branch name 


def get_sublist(item):
    return item[4] if len(item) > 4 and isinstance(item[4], list) else None  # 4 = sublist if exist

class TextHandler(object):
    def __init__(self, widget):
        self.widget = widget
        
    def write(self, s):
        # Enable the Text widget for editing
        self.widget.config(state='normal')
        if not isinstance(s, str):
            try:
                s = str(s)
            except Exception as e:
                handle_and_print_exception(e, 'Text message must be a string.')

        # Define tags
        bold_font = font.Font(self.widget, self.widget.cget("font"))
        bold_font.configure(weight="bold")
        self.widget.tag_configure("bold", font=bold_font)
        self.widget.tag_configure("error", foreground="red")
        self.widget.tag_configure("warning", foreground="orange")
        self.widget.tag_configure("info", foreground="black")

        # Helper function to parse <b> tags and apply bold formatting
        def parse_and_insert_with_tags(text, color_tag=None):
            start = 0
            while start < len(text):
                open_tag = text.find("<b>", start)
                close_tag = text.find("</b>", open_tag)

                if open_tag == -1 or close_tag == -1:  # No more <b> tags
                    self.widget.insert(tk.END, text[start:], color_tag)
                    break

                # Insert text before <b> tag
                self.widget.insert(tk.END, text[start:open_tag], color_tag)

                # Insert bold text
                bold_text = text[open_tag + 3:close_tag]
                self.widget.insert(tk.END, bold_text, ("bold", color_tag) if color_tag else "bold")

                # Update the start index to after the </b> tag
                start = close_tag + 4
                
        # Don't print if there are only blank spaces
        if s.strip(" /t/r") == "":
            return
        # Add timestamp and apply color to the entire message
        if s != '\n':
            # Get current date and time
            now = datetime.datetime.now()
            timestamp = now.strftime("%d/%m/%Y %H:%M:%S.%f")[:-3]

            if s.startswith(MessageType.ERROR.value):
                full_message = f"{timestamp} {s}"
                parse_and_insert_with_tags(full_message, "error")
            elif s.startswith(MessageType.WARNING.value):
                full_message = f"{timestamp} {s}"
                parse_and_insert_with_tags(full_message, "warning")
            elif s.startswith(MessageType.INFO.value):
                full_message = f"{timestamp} {s}"
                parse_and_insert_with_tags(full_message, "info")
            else:
                full_message = f"{timestamp} {s}"
                parse_and_insert_with_tags(full_message)
        else:
            self.widget.insert(tk.END, s)

        # Disable the Text widget after inserting text and scroll to the end
        self.widget.config(state='disabled')
        self.widget.see(tk.END)
        
    def flush(self):
        pass
# Load configuration settings from 'config.json', or use defaults if file is missing or invalid
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if not os.path.exists(config_path):
        message = f"Config file <b>{config_path}</b> not found. Using default values."
        print_message(MessageType.WARNING, message)
        return None
    
    try:
        with open(config_path, "r") as config_file:
            config = json.load(config_file)
            return config
    except json.JSONDecodeError as e:
        handle_and_print_exception(e, 'Error decoding JSON!')
        return None
#Returns the default value if available, 
#otherwise selects the first available option with a message.   
def select_default_or_first(default_value, available_values, entity_name):
    if default_value in available_values:
        return default_value
    else:
        message = f"Default <b>{entity_name} '{default_value}'</b> not found. Using the first available <b>{entity_name}</b>."
        print_message(MessageType.WARNING, message)
        return available_values[0]

def save_credentials(credential_name, username, password):
    credential = {
        'Type': win32cred.CRED_TYPE_GENERIC,
        'TargetName': credential_name,
        'UserName': username,
        'CredentialBlob': password,
        'Persist': win32cred.CRED_PERSIST_LOCAL_MACHINE
    }
    win32cred.CredWrite(credential)
    print(f"Credentials for '{credential_name}' saved successfully.")

def get_credentials(credential_name):
    try:
        credential = win32cred.CredRead(credential_name, win32cred.CRED_TYPE_GENERIC)
        username = credential['UserName']
        password = credential['CredentialBlob'].decode('utf-16')
        return username, password
    except Exception as e:
        handle_and_print_exception(e, 'Can\'t get credentials from Windows Credential Manager.')
        return None,None

def print_message(type, message):
    print(type.value + ' ' + message) 
    
def handle_and_print_exception(e, desc = None):
    type, message = exceptions_handler.handle(e, desc)
    print_message(type, message)
        
def main():
    global token
    root = tk.Tk(screenName='BranchBrowser')
    root.title("BranchBrowser")
    root.geometry('1200x800')  # Set the size of the window
    root.withdraw()
    
    token_entered_via_token_dialog = False
    token_dialog_message = None
    token_expired = False
    username, password = get_credentials("BranchBrowser")
    while(True):
        # If there are no credentials saved (first use or the app) or the token exists but is expired
        if not (username and password) or (username and password and token_expired): 
            token_dialog = TokenDialog(root, token_dialog_message) # Shows the dialog with a message
            token = token_dialog.result
            # If the user clicks "Cancel" or just closes the window
            if not token: 
                return
            token_entered_via_token_dialog = True
        elif username and password:
            token = password

        try:
            github_client = GitHubClient(GIT_HOSTNAME, token)
            if token_entered_via_token_dialog:
                save_credentials("BranchBrowser", "github_token", token)
            break
        except Exception as e:
            if username and password and not token_expired:
                token_dialog_message = "Token has expired"
                token_expired = True
            else:
                token_dialog_message = "Wrong credentials. Entered token is not valid."
            
    # Show a dialog asking for the GitHub token if not already set
    if not token:
        token_dialog = TokenDialog(root)
        token = token_dialog.result
        if not token:
            print("No token provided. Exiting...")
            return

    root.deiconify()
    root.title("BranchBrowser")
    root.geometry('1400x800')  # Set the size of the window
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        config = App.load_config()
        if config is None:
            print("Configuration loading failed. Exiting...")
            return
        
        default_team = config.get("default_team") if config else "default_team"
        git_hostname = config.get("GIT_HOSTNAME", "github.com") if config else GIT_HOSTNAME
        # Initialize GitHub client with provided token and hostname
        github_client = GitHubClient(git_hostname, token)
        # Load configuration and get default organization/repository
        default_org = config.get("default_organization") if config else None
        default_repo = config.get("default_repository") if config else None

        # Get list of available organizations
        available_organizations = github_client.get_organizations_names()
        app_org = []
        app_org = select_default_or_first(default_org, available_organizations, "organization")

        # Get list of repositories for the selected organization
        available_repositories = github_client.get_organization_repos_names(app_org)
        app_repo = select_default_or_first(default_repo, available_repositories, "repository")

        # Get list of available teams for the selected organization (optional, if required)
        available_teams = github_client.get_organization_teams(app_org) 
        app_team = select_default_or_first(default_team, available_teams, "team")

        app = App(root, github_client, app_org, app_repo, token_entered_via_token_dialog, config_path, app_team)  #, app_team

        # Populate combo boxes with available organizations and repositories
        app.org_combo['values'] = available_organizations
        app.repo_combo['values'] = available_repositories

        # Set selected organization and repository in the UI
        app.org_combo.set(app_org)
        app.repo_combo.set(app_repo)
    except Exception as e:
            handle_and_print_exception(e, None)
        
    root.mainloop()

if __name__ == "__main__":
    main()