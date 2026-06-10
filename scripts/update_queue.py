#!/usr/bin/env python3
"""Update queue: remove first article, commit and push to repo"""
import json, subprocess, sys, os

state_file = "last_article.json"
if not os.path.exists(state_file):
    print("No queue file, nothing to update")
    sys.exit(0)

with open(state_file) as f:
    queue = json.load(f)

if isinstance(queue, list) and len(queue) > 0:
    removed = queue.pop(0)
    with open(state_file, "w") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
    print(f"Removed '{removed['title']}' from queue, {len(queue)} remaining")

    subprocess.run(["git", "add", state_file], check=True)
    result = subprocess.run(
        ["git", "commit", "-m", f"chore: dequeue article '{removed['title']}'\n\nAuto-commit by CI after generating podcast episode."],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("Queue commit done, pushing...")
        push = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
        if push.returncode == 0:
            print("Queue pushed successfully")
        else:
            print(f"Push note: {push.stderr[:100]}")
    else:
        print(f"Commit note: {result.stderr[:100]}")

    # Trigger next workflow run if queue still has articles
    if len(queue) > 0:
        next_link = queue[0]["link"]
        print(f"Queue has {len(queue)} remaining, triggering next run for: {next_link}")
        import urllib.request
        token = os.environ.get("GITHUB_TOKEN")
        repo = os.environ.get("GITHUB_REPOSITORY", "marsdream/osp-podcast")
        if token:
            url = f"https://api.github.com/repos/{repo}/actions/workflows/generate-podcast.yml/dispatch"
            data = json.dumps({"ref": "main"}).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
                },
                method="POST"
            )
            try:
                with urllib.request.urlopen(req) as resp:
                    print(f"Next workflow triggered: {resp.status}")
            except Exception as e:
                print(f"Trigger note (may already be running): {e}")
elif isinstance(queue, dict):
    # Single article, just remove the file
    subprocess.run(["git", "rm", "-f", state_file], capture_output=True, text=True)
    print("Removed single-article queue")
    subprocess.run(["git", "commit", "-m", "chore: clear empty queue after processing\n\nAuto-commit by CI."], capture_output=True, text=True)
    push = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
    print(f"Push: {push.returncode}")
else:
    print("Queue is empty or invalid, nothing to do")