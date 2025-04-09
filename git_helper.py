# dev_agent.py

import subprocess
import requests
import openai
import os
import re
import json
from pathlib import Path
from dotenv import load_dotenv

# Load vars.env file, which is a sibling to this file
script_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=script_dir / "vars.env")

# Load environment variables
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

# Extract GitHub repo from git remote
def get_repo_from_git():
    remote_url = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], text=True).strip()
    match = re.search(r"[:/]([\w.-]+/[\w.-]+)(?:\.git)?$", remote_url)
    return match.group(1) if match else None

REPO = get_repo_from_git()

### TOOL 1: Commit with message and push
def commit_and_push_changes(commit_message=None):
    if not commit_message:
        diff = subprocess.check_output(["git", "diff"], text=True)
        commit_message = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "user", "content": f"Summarize the following changes into a short commit message:\n{diff}"}
            ]
        ).choices[0].message.content.strip()

    subprocess.run(["git", "add", "-A"])
    subprocess.run(["git", "commit", "-m", commit_message])
    subprocess.run(["git", "push"])
    return commit_message


### TOOL 2: Create pull request
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

    url = f"https://api.github.com/repos/{REPO}/pulls"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    data = {
        "title": title,
        "head": branch,
        "base": base,
        "body": body
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()


### TOOL 3: Explain changes
def explain_changes():
    diff = subprocess.check_output(["git", "diff"], text=True)
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "user", "content": f"Explain the following git diff:\n{diff}"}
        ]
    )
    return response.choices[0].message.content.strip()


### TOOL 4: Suggest review comments
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


### TOOL 5: Summarize TODO comments
def summarize_todos():
    grep_output = subprocess.check_output(["grep", "-r", "TODO", "./"], text=True, stderr=subprocess.DEVNULL)
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "user", "content": f"Summarize and prioritize these TODO comments:\n{grep_output}"}
        ]
    )
    return response.choices[0].message.content.strip()


### TOOL 6: Generate release notes
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


### TOOL 7: Create GitHub issue from error log
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

    url = f"https://api.github.com/repos/{REPO}/issues"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    data = {"title": title, "body": body, "labels": labels}

    resp = requests.post(url, json=data, headers=headers)
    return {"issue_url": resp.json().get("html_url"), "status": resp.status_code}


# CLI entry point
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", help="Which command to run", choices=[
        "commit_and_push", "create_pr", "explain_changes", "review_comments",
        "summarize_todos", "release_notes", "create_issue"])
    parser.add_argument("--message", help="Optional commit message or error log")
    args = parser.parse_args()

    match args.command:
        case "commit_and_push":
            print(commit_and_push_changes(args.message))
        case "create_pr":
            print(create_pull_request())
        case "explain_changes":
            print(explain_changes())
        case "review_comments":
            print(suggest_review_comments())
        case "summarize_todos":
            print(summarize_todos())
        case "release_notes":
            print(generate_release_notes())
        case "create_issue":
            if not args.message:
                print("Please provide --message with an error log")
            else:
                print(create_github_issue_from_error_log(args.message))
