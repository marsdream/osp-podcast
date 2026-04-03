#!/usr/bin/env python3
"""
check_articles.py - 检查 osp.io 是否有新文章
总是返回 0，has_new=true/false 通过 GITHUB_OUTPUT 传递
检测到新文章后，把 last_article.json 推回 GitHub main 分支，避免重复生成
"""
import feedparser
import json
import os
import sys
import base64
import requests

RSS_URL = "https://osp.io/feed"
STATE_FILE = "last_article.json"
REPO = "marsdream/osp-podcast"
BRANCH = "main"


def gh_output(key, value):
    """只写入 GITHUB_OUTPUT 文件（格式: key=value）"""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def github_api_get(path):
    """GitHub REST API GET"""
    token = os.environ.get("GITHUB_TOKEN")
    url = f"https://api.github.com/{path}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def github_api_put(path, payload):
    """GitHub REST API PUT (create/update file)"""
    token = os.environ.get("GITHUB_TOKEN")
    url = f"https://api.github.com/{path}"
    headers = {"Content-Type": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    resp = requests.put(url, headers=headers, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def push_state_file(article_data):
    """把 last_article.json 推回 GitHub main 分支"""
    content = json.dumps(article_data, ensure_ascii=False, indent=2)

    # 获取当前文件的 SHA（如果存在）
    existing = github_api_get(f"repos/{REPO}/contents/{STATE_FILE}?ref={BRANCH}")
    payload = {
        "message": f"chore: update article state to {article_data['title'][:30]}",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": BRANCH,
    }
    if existing:
        payload["sha"] = existing["sha"]

    try:
        result = github_api_put(f"repos/{REPO}/contents/{STATE_FILE}", payload)
        print(f"  → pushed state to GitHub: {result.get('commit', {}).get('sha', 'ok')[:7]}")
    except Exception as e:
        print(f"  → failed to push state: {e}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        print("No entries found in RSS feed")
        gh_output("has_new", "false")
        return 0

    latest = feed.entries[0]
    latest_id = latest.get("id") or latest.link
    latest_title = latest.title
    latest_link = latest.link

    # 检查是否有新文章
    has_new = True
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            last = json.load(f)
        if last.get("id") == latest_id:
            print("No new articles — skipping generation")
            gh_output("has_new", "false")
            return 0

    # 保存新文章信息
    article_data = {
        "id": latest_id,
        "title": latest_title,
        "link": latest_link,
    }
    with open(STATE_FILE, "w") as f:
        json.dump(article_data, f, ensure_ascii=False, indent=2)

    print(f"New article: {latest_title}")

    # 推回 GitHub，避免下次重复生成
    push_state_file(article_data)

    gh_output("has_new", "true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
