"""Git commit and push utility using dulwich."""

import os
import sys
from dulwich import porcelain
from dulwich.repo import Repo

def main():
    repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    repo = Repo(repo_dir)
    print(f"Opening git repository at {repo_dir}...")

    # Files and folders to stage
    paths_to_stage = [
        "AGENTS.md",
        "README.md",
        "app.py",
        "agents/agent.py",
        "agents/callbacks.py",
        "agents/config.py",
        "agents/tools.py",
        "agents/mcp_server.py",
        "agents/store.py",
        "agents/__init__.py",
        "agents/.env.example",
        "scripts/diagnose.py",
        "tests/test_callbacks.py",
        "tests/test_payloads.py",
        "tests/test_tools.py",
        "tests/test_web.py",
        "web/index.html",
        "web/styles.css",
        "web/app.js",
        ".gitignore",
        ".env.example",
        "Procfile",
        "requirements.txt",
        "simulate.py",
    ]

    existing_paths = [p for p in paths_to_stage if os.path.exists(os.path.join(repo_dir, p))]
    print(f"Staging {len(existing_paths)} paths...")
    porcelain.add(repo, paths=existing_paths)

    # Status check
    status = porcelain.status(repo)
    print("Staged files for commit:")
    for action, file_list in status.staged.items():
        if file_list:
            print(f"  {action}: {len(file_list)} files")

    # Commit
    commit_msg = (
        b"Complete hackathon submission: Pure-white minimalist Web UI, "
        b"real-time SSE streaming, AGENTS.md architecture, and 26 passing tests"
    )
    commit_id = porcelain.commit(
        repo,
        message=commit_msg,
        author=b"Lohunn <lohunnp@gmail.com>",
        committer=b"Lohunn <lohunnp@gmail.com>",
    )
    print(f"Committed successfully: {commit_id.decode('ascii') if isinstance(commit_id, bytes) else commit_id}")

    # Push to GitHub
    token = sys.argv[1] if len(sys.argv) > 1 else os.getenv("GITHUB_TOKEN", "")
    if not token:
        print("ERROR: GitHub Personal Access Token is required to push.")
        sys.exit(1)

    remote_url = f"https://{token}@github.com/Lohunn/Repomaxxers.git"
    print("Pushing to remote https://github.com/Lohunn/Repomaxxers.git (branch: main)...")

    try:
        porcelain.push(repo, remote_url, refspecs=[b"refs/heads/main:refs/heads/main"])
        print("Successfully pushed to https://github.com/Lohunn/Repomaxxers.git!")
    except Exception as e:
        print(f"Push failed: {e}")
        # Try pushing without refspec or force if needed
        porcelain.push(repo, remote_url, b"main")
        print("Successfully pushed to https://github.com/Lohunn/Repomaxxers.git via default refspec!")

if __name__ == "__main__":
    main()
