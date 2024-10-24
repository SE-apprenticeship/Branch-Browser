import base64
import datetime
from io import StringIO
import json
import re
import sys
import threading
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import simpledialog
from github import Github, UnknownObjectException
import configparser
import requests

token = ''
GIT_HOSTNAME = 'github.com'

class GitHubClient:
    def __init__(self, hostname, token):
        self.github = Github(base_url=f"https://api.{hostname}", login_or_token=token)
        self.user = self.github.get_user()
        self.username = self.user.login # this will throw exception if token is invalid
    
    def get_username(self):
        return self.username

    def get_organizations_names(self):
        return [org.login for org in self.user.get_orgs()]

    def get_organization_repos_names(self, org_name):
        return [repo.name for repo in self.github.get_organization(org_name).get_repos()]

    def get_organization_repo_branches(self, org_name, repo_name):
        return [branch.name for branch in self.github.get_organization(org_name).get_repo(repo_name).get_branches()]

    def get_organization_repo_branch_gitmodules_content(self, org_name, repo_name, branch_name):
        try:
            file_content = self.github.get_organization(org_name).get_repo(repo_name).get_contents('.gitmodules', ref=branch_name)
            return file_content.decoded_content.decode()
        except UnknownObjectException:
            return ''

    def get_organization_repo_branch_commit_sha(self, org_name, repo_name, branch_name):
        return self.github.get_organization(org_name).get_repo(repo_name).get_branch(branch_name).commit.sha

    def organization_repo_create_branch(self, org_name, repo_name, new_branch_name, source_commit_sha):
        # refs/heads/new-branch is used to create a new branch
        self.github.get_organization(org_name).get_repo(repo_name).create_git_ref(ref=f"refs/heads/{new_branch_name}", sha=source_commit_sha)

    def organization_repo_delete_branch(self, org_name, repo_name, branch_name):
        # Fetch the branch reference
        ref = self.github.get_organization(org_name).get_repo(repo_name).get_git_ref(f"heads/{branch_name}")
        # Delete the branch by deleting its reference
        ref.delete()

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
        response = requests.request(method, url, headers=self.headers, data=json.dumps(data))
        response.raise_for_status()
        return response.json()
    
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

        # Create a git tree that updates/deletes the gitmodule file and deletes submodule reference in tree
        data = {
            'base_tree': parent_tree_sha,
            'tree': [
                {
                    "path": ".gitmodules",
                    "mode": "100644",
                    "type": "blob",
                    "sha": git_modules_blob_sha,
                },
                {
                    'path': path_to_submodule,
                    'mode': '160000',
                    'type': 'commit',
                    'sha': None
                }
            ]
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

        print(f'Updated {response["ref"]} to {response["object"]["sha"]}')


class App:
    def __init__(self, root, github_client):
        self.root = root
        self.github_client = github_client
        self.last_tree_item_rightclicked = None
        self.setup_ui()
        self.setup_actions()
        print(f'Connected to GitHub with user: {self.username}.')

    def setup_ui(self):
        self.frame = tk.Frame(self.root, width=400)
        self.frame.pack(side='left', fill='y')

        self.branches_tree = ttk.Treeview(self.frame, selectmode="none")
        self.branches_tree.pack(fill='both', expand=True)
        self.branches_tree.column("#0", width=300)

        self.menu = tk.Menu(self.root, tearoff=0)

        self.username = self.github_client.get_username()
        self.username_label = tk.Label(self.root, text=f"Logged in as: {self.username}")
        self.username_label.pack(side='top', fill='x')

        self.orgs = self.github_client.get_organizations_names()
        self.org_label = tk.Label(self.root, text="Organization:")
        self.org_label.pack(side='top', fill='x')
        self.org_combo = ttk.Combobox(self.root, values=self.orgs)
        self.org_combo['state'] = 'readonly'
        self.org_combo.pack(side='top', fill='x')

        self.repo_label = tk.Label(self.root, text="Repository:")
        self.repo_label.pack(side='top', fill='x')
        self.repo_combo = ttk.Combobox(self.root)
        self.repo_combo['state'] = 'readonly'
        self.repo_combo.pack(side='top', fill='x')

        self.log_label = tk.Label(self.root, text="Log:")
        self.log_label.pack(side='top', fill='x')
        text = tk.Text(self.root, state='disabled')  # Create a Text widget
        text.pack(side='top', fill='both', expand=True)
        # Redirect stdout to the Text widget
        sys.stdout = TextHandler(text)


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
        if self.orgs:
            self.org_combo.current(0)
            self.update_repos(None)
            self.update_tree(None)

    def populate_tree(self, tree, node, parent=''):
        if type(node) == dict:
            for k,v in node.items():
                new_node = tree.insert(parent, 'end', text=k, tags=("branch_tree",))
                self.populate_tree(tree, v, new_node)
        elif type(node) == list:
            for v in node:
                tree.insert(parent, 'end', text=v, tags=("branch_tree",))

    def update_repos(self, event):
        org_name = self.org_combo.get()
        repos = self.github_client.get_organization_repos_names(org_name)
        self.repo_combo['values'] = repos
        if repos:
            self.repo_combo.current(0)
            self.update_tree(None)

    def update_tree(self, event):
        org_name = self.org_combo.get()
        repo_name = self.repo_combo.get()
 
        branches_structure = self.github_client.get_repo_branches_structure(org_name, repo_name)

        self.branches_tree.delete(*self.branches_tree.get_children())
        self.branches_tree.heading("#0", text=f'Branches on {org_name}/{repo_name}')

        self.populate_tree(self.branches_tree, branches_structure)

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
        else:
            self.menu.add_command(label="Expand all", command=self.expand_all)
            self.menu.add_command(label="Colapse all", command=self.collapse_all)
            
        self.last_tree_item_rightclicked = item
        self.menu.post(event.x_root, event.y_root)

    def get_path(self, tree, item):
        path = []
        while item:
            path.append(tree.item(item, 'text'))
            item = tree.parent(item)
        return '/'.join(reversed(path))

    def create_branch(self):
        org_name = self.org_combo.get()
        repo_name = self.repo_combo.get()
        selected_item = self.last_tree_item_rightclicked
        branch_name = self.get_path(self.branches_tree, selected_item)
        print(f"Creating branch from {branch_name} on {org_name}/{repo_name}...")
        new_branch = CloneDialog(self.root, self.github_client, org_name, repo_name, branch_name).result
        # Check the result
        if new_branch:
            print(f"New branch crated: {new_branch} on {org_name}/{repo_name}.")
            self.update_tree(None) # Update tree to reflect changes
        else:
            print(f"Creating branch from {branch_name} on {org_name}/{repo_name} canceled!")

    def delete_branch(self):
        org_name = self.org_combo.get()
        repo_name = self.repo_combo.get()
        selected_item = self.last_tree_item_rightclicked
        branch_name = self.get_path(self.branches_tree, selected_item)
        print(f"Deleting branch from {branch_name} on {org_name}/{repo_name}...")
        result = DeleteDialog(self.root, self.github_client, org_name, repo_name, branch_name).result
        # Check the result
        if result:
            print(f"Branch deleted: {branch_name} on {org_name}/{repo_name}.")
            self.update_tree(None) # Update tree to reflect changes
        else:
            print(f"Deleting branch {branch_name} on {org_name}/{repo_name} canceled!")
    
    def manage_submodules(self):
        org_name = self.org_combo.get()
        repo_name = self.repo_combo.get()
        selected_item = self.last_tree_item_rightclicked
        branch_name = self.get_path(self.branches_tree, selected_item)
        print(f"Manage submodules for {branch_name} on {org_name}/{repo_name}...")
        SubmoduleSelectorDialog(self.root, self.github_client, org_name, repo_name, branch_name, self.update_tree)

    
    def create_feature_branch(self):
        org_name = self.org_combo.get()
        repo_name = self.repo_combo.get()
        selected_item = self.last_tree_item_rightclicked
        branch_name = self.get_path(self.branches_tree, selected_item)
        print(f"Create feature branch for {branch_name} on {org_name}/{repo_name}...")
        CreateFeatureBranchDialog(self.root, self.github_client, org_name, repo_name, branch_name, self.update_tree)
    

class TokenDialog(simpledialog.Dialog):
    def body(self, master):
        self.resizable(False, False)
        self.title("GitHub Token")
        tk.Label(master, text="Enter your GitHub token:").grid(row=0)
        self.token = tk.Entry(master, show='*', width=40)
        self.token.grid(row=0, column=1)
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
        print("Created new branch.")
        self.result = self.new_branch_name.get()


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
        print(f"Deleted branch {self.branch_name}.")
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
    def __init__(self, parent, github_client, org_name, repo_name, branch_name, update_tree):
        self.repo_branch_right_lb_info_map = dict()
        self.repo_branch_left_lb_info_list = list()

        self.github_client = github_client
        self.org_name = org_name
        self.repo_name = repo_name
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


    def update_repo_branches_right_listbox(self, event = None):
        self.repo_branch_right_lb_info_map.clear()

        # Get the selected value of the repo name combobox
        repo_name = self.repos_combobox.get()

        # Clear the listbox
        self.repo_branches_right_listbox.delete(0, tk.END)

        branches = self.github_client.get_organization_repo_branches(self.org_name, repo_name)

        # Update the repo branches right listbox based on the repo name selected value
        for index, branch in enumerate(branches):
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
        print(f"Updating current submodules to HEAD revision on {self.org_name}/{self.repo_name}/{self.branch_name}...")
        original = set(self.repo_branch_left_lb_info_list)

        # Do the modification
        repo_submodule_manager = GitHubRepoSubmoduleManager(self.org_name, self.repo_name, token)

        updated = []
        for orig_submodule in original:
            if repo_submodule_manager.add_or_update_submodule(self.branch_name, orig_submodule.repo, orig_submodule.path):
                updated.append(orig_submodule.repo)

        print(f"Updated {updated} submodules to HEAD revision.")


    def body(self, master):
        # Disable resizing of the dialog
        self.resizable(False, False)
        self.title(f'Manage submodules for {self.org_name}/{self.repo_name}/{self.branch_name}')

        # Create right container frame
        self.left_frame = tk.Frame(master, width=90, height=50)
        self.left_label = tk.Label(self.left_frame, text="Submodules:")
        # Create listboxes
        self.submodules_left_listbox = tk.Listbox(self.left_frame, width=90, height=50)

        # Create right container frame
        self.right_frame = tk.Frame(master, width=90, height=50)

        org_repos_names = self.github_client.get_organization_repos_names(self.org_name)
        org_repos_names.remove(self.repo_name)

        # Create combobox
        self.repos_combobox = ttk.Combobox(self.right_frame, width=87, values=org_repos_names)
        self.repos_combobox['state'] = 'readonly'
        self.repos_combobox.bind('<<ComboboxSelected>>', self.update_repo_branches_right_listbox)
        # Set the first item as selected
        self.repos_combobox.current(0)

        # Create right listbox
        self.repo_branches_right_listbox = tk.Listbox(self.right_frame, width=90, height=50)

        # Create buttons
        button_right = tk.Button(master, text=">", command=self.move_to_right)
        button_left = tk.Button(master, text="<", command=self.move_to_left)

        # Pack widgets
        self.left_frame.pack(side=tk.LEFT)
        self.left_label.pack()
        self.submodules_left_listbox.pack()

        button_left.pack(side=tk.LEFT)
        button_right.pack(side=tk.LEFT)

        self.right_frame.pack(side=tk.LEFT)
        self.repos_combobox.pack()
        self.repo_branches_right_listbox.pack()

        # Initialize current state of submodules for current org/repo/branch
        self.init_submodules_left_listbox()

        # Call the update_listbox function
        self.update_repo_branches_right_listbox()

    def cancel(self, event=None):
        print(f"Manage submodules for {self.branch_name} on {self.org_name}/{self.repo_name} canceled!")
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
            print("Modifying submodules...")
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

            print(f"Submodules updated for {self.branch_name} on {self.org_name}/{self.repo_name}.")
            # Convert the lists to strings
            deleted_str = ', '.join([item.repo for item in deleted])
            added_str = ', '.join([item.repo for item in added])
            # Print the result
            print(f"Added: {added_str} ; Deleted: {deleted_str}")
            self.update_tree(None) # Update tree to reflect changes

        except Exception as e:
            print(e)
        finally:
            # Close the processing popup
            self.processing_popup.destroy()


class CreateFeatureBranchDialog(simpledialog.Dialog):
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
        self.title(f'Create feature branch for {self.org_name}/{self.repo_name}/{self.branch_name}')

        tk.Label(master, text="Enter replace search prefix (prefix that will be replaced by feature branch prefix):").grid(row=0, sticky='w')
        self.search_branch_prefix = tk.Entry(master, width=60)
        self.search_branch_prefix.insert(0, self.branch_name)
        self.search_branch_prefix.grid(row=0, column=1)

        tk.Label(master, text="Enter feature branch prefix (Features/TeamName[/Feature-BugName]):").grid(row=1, sticky='w')
        self.replace_feature_branch_prefix = tk.Entry(master, width=60)
        self.replace_feature_branch_prefix.insert(0, "Features/TeamName/Feature-Bug")
        self.replace_feature_branch_prefix.grid(row=1, column=1)

        # get submodules info
        self.submodules_info = get_submodules_info(self.github_client, self.org_name, self.repo_name, self.branch_name)
        # extend with sub sub module info
        self.submodules_info =[sub_m_info + (get_submodules_info(self.github_client, self.org_name, sub_m_info[1], sub_m_info[2]),) for sub_m_info in self.submodules_info]

        tk.Label(master, text="List of branches from which feature branches will be created:", font=('TkDefaultFont', 10, 'bold')).grid(row=2, sticky='w')

        tk.Label(master, text=f"R:{self.repo_name} B:{self.branch_name}").grid(row=3, sticky='w')
        row_ind = 4
        for sub_m_info in self.submodules_info:
            tk.Label(master, text=f"\tR:{sub_m_info[1]} B:{sub_m_info[2]}").grid(row=row_ind, sticky='w')
            for sub_sub_m_info in sub_m_info[4]:
                row_ind += 1
                tk.Label(master, text=f"\t\tR:{sub_sub_m_info[1]} B:{sub_sub_m_info[2]}").grid(row=row_ind, sticky='w')
            row_ind += 1

    def cancel(self, event=None):
        print(f"Create feature branch for {self.branch_name} on {self.org_name}/{self.repo_name} canceled!")
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
            print("Creating feature branch structure...")

            # Creeate feature branch for submodule
            new_branch_name = self.branch_name.replace(self.search_branch_prefix_val, self.replace_feature_branch_prefix_val)

            # Validate if prefix replace will actually change branch name
            if new_branch_name == self.branch_name:
                print(f'Replace search branch prefix:{self.search_branch_prefix_val} has no effect on branch: {self.branch_name}. Nothing is being replaced.')
                return

            branch_commit_sha = self.github_client.get_organization_repo_branch_commit_sha(self.org_name, self.repo_name, self.branch_name)
            self.github_client.organization_repo_create_branch(self.org_name, self.repo_name, new_branch_name, branch_commit_sha)
            print(f"Created new branch {new_branch_name} on top repo {self.repo_name}.")

            for sub_m_info in self.submodules_info:
                sub_m_repo_name = sub_m_info[1]
                sub_m_branch_name = sub_m_info[2]

                # Creeate feature branch for submodule
                new_sub_m_branch_name = sub_m_branch_name.replace(self.search_branch_prefix_val, self.replace_feature_branch_prefix_val)
                branch_commit_sha = self.github_client.get_organization_repo_branch_commit_sha(self.org_name, sub_m_repo_name, sub_m_branch_name)
                self.github_client.organization_repo_create_branch(self.org_name, sub_m_repo_name, new_sub_m_branch_name, branch_commit_sha)
                print(f"Created new branch {new_sub_m_branch_name} on sub repo {sub_m_repo_name}.")


                for sub_sub_m_info in sub_m_info[4]:
                    sub_sub_m_repo_name = sub_sub_m_info[1]
                    sub_sub_m_branch_name = sub_sub_m_info[2]

                    # Creeate feature branch for sub submodule
                    new_sub_sub_m_branch_name = sub_sub_m_branch_name.replace(self.search_branch_prefix_val, self.replace_feature_branch_prefix_val)
                    branch_commit_sha = self.github_client.get_organization_repo_branch_commit_sha(self.org_name, sub_sub_m_repo_name, sub_sub_m_branch_name)
                    self.github_client.organization_repo_create_branch(self.org_name, sub_sub_m_repo_name, new_sub_sub_m_branch_name, branch_commit_sha)
                    print(f"Created new branch {new_sub_sub_m_branch_name} on sub sub repo {sub_sub_m_repo_name}.")

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

            print(f"Feature branch created for {self.branch_name} on {self.org_name}/{self.repo_name}.")
            self.update_tree(None) # Update tree to reflect changes

        except Exception as e:
            print(e)
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


# Calculate submodule path (folder) - default is same as submodule repo name, ADMS have exception for non Product
def calculate_submodule_path(org_name, sub_repo_name):
    calculated_path = sub_repo_name

    # Add some custom logic if submodule does not go into folder named as itself
    
    return calculated_path


class TextHandler(object):
    def __init__(self, widget):
        self.widget = widget

    def write(self, s):
        self.widget.config(state='normal')  # Enable the Text widget

        if s != '\n':
             # Get current date and time
            now = datetime.datetime.now()
            timestamp = now.strftime("%d/%m/%Y %H:%M:%S.%f")[:-3]  # Format date and time
            self.widget.insert(tk.END, timestamp + " " + s)
        else:
            self.widget.insert(tk.END, s)

        self.widget.config(state='disabled')  # Disable the Text widget after inserting text
        self.widget.see(tk.END)

    def flush(self):
        pass


def main():
    root = tk.Tk(screenName ='BranchBrowser')
    root.title("BranchBrowser")
    root.geometry('1200x800')  # Set the size of the window
    root.withdraw()
    
    # Show a dialog asking for the GitHub token
    token_dialog = TokenDialog(root)

    global token
    token  = token_dialog.result

    root.deiconify()
    root.title("BranchBrowser")
    root.geometry('1400x800')  # Set the size of the window

    if not token:
        print("No token provided. Exiting...")
        return
  
    try:
        github_client = GitHubClient(GIT_HOSTNAME, token)
    except Exception as e:
        print(f"{str(e)}. Exiting...")
        return

    app = App(root, github_client)

    root.mainloop()


if __name__ == "__main__":
    main()
