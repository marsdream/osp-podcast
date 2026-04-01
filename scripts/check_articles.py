#!/usr/bin/env python3
"""
check_articles.py - 检查 osp.io 是否有新文章
返回 0 总是（GitHub Actions 用 GITHUB_OUTPUT 判断）
"""
import feedparser
import json
import os
import sys

RSS_URL = "https://osp.io/feed"
STATE_FILE = "last_article.json"


def write_github_output(key, value):
    """写入 GitHub Actions GITHUB_OUTPUT"""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def main():
    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        print("No entries found in RSS feed", file=sys.stderr)
        write_github_output("has_new", "false")
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
            has_new = False

    if has_new:
        # 保存新文章信息（generate_podcast.py --auto 会读取这个文件）
        article_data = {
            "id": latest_id,
            "title": latest_title,
            "link": latest_link,
        }
        with open(STATE_FILE, "w") as f:
            json.dump(article_data, f, ensure_ascii=False, indent=2)
        print(f"New article found: {latest_title}")

    # GitHub Actions: always exit 0, use output to decide next step
    write_github_output("has_new", "true" if has_new else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
