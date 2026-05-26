#!/usr/bin/env python3
"""
check_articles.py - 检查 osp.io 是否有新文章
总是返回 0，has_new=true/false 通过 GITHUB_OUTPUT 传递
"""
import feedparser
import json
import os
import sys

RSS_URL = "https://osp.io/feed"
STATE_FILE = "last_article.json"


def gh_output(key, value):
    """只写入 GITHUB_OUTPUT 文件（格式: key=value）"""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


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
    gh_output("has_new", "true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
