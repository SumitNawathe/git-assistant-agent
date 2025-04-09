import subprocess
import requests
import openai
import os
import re
import json
from pathlib import Path
from dotenv import load_dotenv

# load vars.env file, which is a sibling to this file
script_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=script_dir / "vars.env")

# load environment variables
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

def get_repo_from_git():
    remote_url = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], text=True).strip()
    match = re.search(r"[:/]([\w.-]+/[\w.-]+)(?:\.git)?$", remote_url)
    ans = match.group(1) if match else None
    return ans.split('.git')[0] if ans else None

def commit_and_push_changes(commit_message=None):
    if not commit_message:
        diff = subprocess.check_output(["git", "diff"], text=True)
        commit_message = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "user", "content": f"Summarize the following changes into a short commit message:\n{diff}"}
            ]
        ).choices[0].message.content.strip()

    # TODO: refactor to not use subprocess
    subprocess.run(["git", "add", "-A"])
    subprocess.run(["git", "commit", "-m", commit_message])
    subprocess.run(["git", "push"])
    return commit_message

def create_pull_request(base="main", title=None, body=None):
    branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
    diff = subprocess.check_output(["git", "diff", f"origin/{base}...{branch}"], text=True)

    if not title or not body:
        completion = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "user", "content": f"Generate a pull request title and body for this diff:\n{diff}"}
            ]
        ).choices[0].message.content.strip()
        match = re.match(r"(?s)(.*?)\n\n(.*)", completion)
        title, body = match.groups() if match else ("Update code", completion)

    url = f"https://api.github.com/repos/{get_repo_from_git()}/pulls"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Accept": "application/vnd.github+json"
    }
    data = {
        "title": title,
        "head": branch,
        "base": base,
        "body": body
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()

def explain_changes():
    diff = subprocess.check_output(["git", "diff"], text=True)
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "user", "content": f"Explain the following git diff:\n{diff}"}
        ]
    )
    return response.choices[0].message.content.strip()

def suggest_review_comments():
    diff = subprocess.check_output(["git", "diff"], text=True)
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful code reviewer."},
            {"role": "user", "content": f"Provide inline review comments for this diff:\n{diff}"}
        ]
    )
    return response.choices[0].message.content.strip()

def summarize_todos():
    files = subprocess.check_output(["git", "ls-files"], text=True)
    all_lines = []
    for file in files.split('\n')[:-1]:
        with open(file.strip(), 'r') as f:
            all_lines.extend(f.readlines())
    all_lines = '\n'.join(list(filter(lambda line: 'TODO' in line, all_lines)))
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "user", "content": f"Summarize and prioritize these TODO comments:\n{all_lines}"}
        ]
    )
    return response.choices[0].message.content.strip()

def generate_release_notes(base_ref="origin/main", head_ref="HEAD"):
    log = subprocess.check_output(["git", "log", f"{base_ref}..{head_ref}", "--pretty=format:%s"], text=True)
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an expert software release note writer."},
            {"role": "user", "content": f"Generate markdown release notes for the following commits:\n{log}"}
        ]
    )
    return response.choices[0].message.content.strip()

def create_github_issue_from_error_log(error_log):
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You write GitHub issues from error logs."},
            {"role": "user", "content": f"Generate GitHub issue title, body, and labels from this log:\n{error_log}"}
        ]
    ).choices[0].message.content.strip()

    match = re.match(r"Title:\s*(.*?)\n+Body:\s*(.*?)\n+Labels:\s*(.*)", response, re.DOTALL)
    if not match:
        return {"error": "Could not parse response", "raw": response}

    title, body, labels_str = match.groups()
    labels = [l.strip() for l in labels_str.split(",")]

    url = f"https://api.github.com/repos/{get_repo_from_git()}/issues"
    # TODO: refactor header out
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    data = {"title": title, "body": body, "labels": labels}

    resp = requests.post(url, json=data, headers=headers)
    return {"issue_url": resp.json().get("html_url"), "status": resp.status_code}

tools = [
    {
        "type": "function",
        "function": {
            "name": "commit_and_push_changes",
            "description": "Commit all current changes and push to remote.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "The commit message. If not provided, one will be generated from the git diff."},
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_pull_request",
            "description": "Create a pull request with a detailed summary. The default base branch (the branch being merged into) is 'main'. If the title and body are not provided, they will be generated automatically from the diff.",
            "parameters": {
                "type": "object",
                "properties": {
                    "base": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "explain_changes",
            "description": "Asks OpenAI model to explain the current git diff.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_review_comments",
            "description": "Asks OpenAI model to suggest inline review comments for the current git diff.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_todos",
            "description": "Asks OpenAI model to summarize and prioritize the TODO comments.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_release_notes",
            "description": "Generates release notes based on the git log. The default base_ref is origin/main, and the default head_ref is 'HEAD'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "base_ref": {"type": "string"},
                    "head_ref": {"type": "string"},
				},
                "required": []
            }
        }
    }
]

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "instructions",
        help="Instructions to the agent",
        type=str
    )
    args = parser.parse_args()
    
    messages = [
        {
            'role': 'system',
            'content': 'You are a helpful assistant that helps developers with git commands, repository management, and the software development lifecycle. You may depend on the tools provided to you; you do not need to provide optional arguments if you do not have context.'
		},
        {
            'role': 'user',
            'content': f"{args.instructions}"
		}
	]
    response = openai.chat.completions.create(
		model="gpt-4",
		messages=messages,
		tools=tools,
		tool_choice="auto",
	)
    message = response.choices[0].message
    print(f"{message=}")
    
    if message.tool_calls:
        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            if function_name == "commit_and_push_changes":
                print(f"Taking action: commit and push changes")
                commit_message = function_args.get("message")
                commit_and_push_changes(commit_message)
            elif function_name == "create_pull_request":
                print(f"Taking action: create pull request")
                base = function_args.get("base", "main")
                title = function_args.get("title")
                body = function_args.get("body")
                create_pull_request(base, title, body)
            elif function_name == "explain_changes":
                print(f"Taking action: explain changes")
                explain_changes()
            elif function_name == "suggest_review_comments":
                print(f"Taking action: suggest review comments")
                suggest_review_comments()
            elif function_name == "summarize_todos":
                print(f"Taking action: summarize todos")
                summarize_todos()
            elif function_name == "generate_release_notes":
                print(f"Taking action: generate release notes")
                base_ref = function_args.get("base_ref", "origin/main")
                head_ref = function_args.get("head_ref", "HEAD")
                generate_release_notes(base_ref, head_ref)
    else:
        print(message.content)
