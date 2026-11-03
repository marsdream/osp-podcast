#!/usr/bin/env python3
"""
update_queue.py - 出队 + 触发下一轮

修复（2026-11-04）：
  原逻辑无条件 pop(0) 出队。但 generate_podcast.py 也已经 pop(0) 过 —— 同一篇文章
  被出队两次，等于每处理一篇就丢一篇（72 → 71 → 70）。加上 429 失败的文章也被
  弹出，队列里已有 12 篇已发布的僵尸条目。

新逻辑：
  - generate_podcast.py 把「本轮处理的文章」写入 episode_result.json
    （成功才有 episode_id，失败写 error）
  - 本脚本只移除 **episode_result.json 里确认成功** 的那一篇
  - 失败的文章留在队列里，下轮重试（最多 MAX_ATTEMPTS 次后移到队尾，避免卡死队首）
  - 顺带清理「已发布但仍在队列」的僵尸条目
"""
import json
import os
import subprocess
import sys

STATE_FILE = "last_article.json"
RESULT_FILE = "episode_result.json"
MAX_ATTEMPTS = 3
ATTEMPT_KEY = "_attempts"


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def commit_and_push(message):
    subprocess.run(["git", "add", "-f", STATE_FILE], check=False)
    result = subprocess.run(
        ["git", "commit", "-m", message],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("Queue commit done, pushing...")
        push = subprocess.run(
            ["git", "push", "origin", "main"], capture_output=True, text=True
        )
        if push.returncode == 0:
            print("Queue pushed successfully")
        else:
            print(f"Push note: {push.stderr[:200]}")
    else:
        print(f"Commit note: {result.stderr[:200]}")


def trigger_next(repo, token):
    import urllib.request

    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/"
        "generate-podcast.yml/dispatch"
    )
    data = json.dumps({"ref": "main"}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"Next workflow triggered: {resp.status}")
    except Exception as e:
        print(f"Trigger note (may already be running): {e}")


def main():
    queue = load_json(STATE_FILE, None)
    if not isinstance(queue, list):
        print("Queue is empty or invalid, nothing to do")
        return 0

    if not queue:
        print("Queue empty, nothing to do")
        return 0

    result = load_json(RESULT_FILE, {})
    processed_link = result.get("link")
    succeeded = bool(result.get("success")) and bool(result.get("episode_id"))

    # ── 清理僵尸条目：已发布但仍留在队列里的文章 ──────────────────
    published = set(result.get("published_links", []))
    if published:
        before = len(queue)
        queue = [a for a in queue if a.get("link") not in published]
        if len(queue) != before:
            print(f"Removed {before - len(queue)} zombie entries (already published)")

    # ── 出队：只移除本轮真正成功的那一篇 ──────────────────────────
    if succeeded and processed_link:
        new_queue = []
        removed = None
        for a in queue:
            if removed is None and a.get("link") == processed_link:
                removed = a
                continue
            new_queue.append(a)
        if removed is not None:
            queue = new_queue
            print(f"Removed '{removed['title']}' from queue, {len(queue)} remaining")
        else:
            # generate_podcast.py 已自己 pop 过（老行为），队列里找不到就跳过
            print(f"Processed article already dequeued: {processed_link}")
    else:
        # 失败：文章留在队列里，记录尝试次数；超上限后移到队尾，避免卡死队首
        if processed_link:
            for a in queue:
                if a.get("link") == processed_link:
                    attempts = a.get(ATTEMPT_KEY, 0) + 1
                    a[ATTEMPT_KEY] = attempts
                    print(f"Generation failed for '{a['title']}' (attempt {attempts})")
                    if attempts >= MAX_ATTEMPTS:
                        queue.remove(a)
                        queue.append(a)
                        print(
                            f"  attempt limit {MAX_ATTEMPTS} reached "
                            "— moved to end of queue"
                        )
                    break
        else:
            print(
                "No episode_result.json — generation may not have run; "
                "keeping queue intact"
            )

    # 写回队列
    with open(STATE_FILE, "w") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

    if succeeded and processed_link:
        commit_and_push(
            f"chore: dequeue article '{result.get('title', processed_link)}'\n\n"
            "Auto-commit by CI after generating podcast episode."
        )
    else:
        print("Not dequeuing (generation did not succeed) — queue kept")

    # 触发下一轮
    if len(queue) > 0:
        next_link = queue[0]["link"]
        print(
            f"Queue has {len(queue)} remaining, "
            f"triggering next run for: {next_link}"
        )
        token = os.environ.get("GITHUB_TOKEN")
        repo = os.environ.get("GITHUB_REPOSITORY", "marsdream/osp-podcast")
        if token:
            trigger_next(repo, token)
    else:
        print("Queue empty — no next run needed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
