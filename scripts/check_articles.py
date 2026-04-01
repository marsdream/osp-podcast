#!/usr/bin/env python3
"""
check_articles.py - 检查 osp.io 是否有新文章
返回 0 表示有新文章，1 表示没有新文章
"""
import feedparser
import json
import os
import sys

RSS_URL = "https://osp.io/feed"
STATE_FILE = "last_article.json"
OUTPUT_FILE = os.environ.get("GITHUB_OUTPUT", os.path.join(os.path.dirname(__file__), "..", "last_article.json"))


def main():
    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        print("No entries found in RSS feed", file=sys.stderr)
        return 1

    latest = feed.entries[0]
    latest_id = latest.get("id") or latest.link
    latest_title = latest.title
    latest_link = latest.link

    # 检查是否有新文章
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            last = json.load(f)
        if last.get("id") == latest_id:
            print("No new articles")
            return 1

    # 保存新文章信息
    article_data = {
        "id": latest_id,
        "title": latest_title,
        "link": latest_link,
    }
    with open(STATE_FILE, "w") as f:
        json.dump(article_data, f, ensure_ascii=False, indent=2)

    # 输出 GitHub Actions 环境变量
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"ARTICLE_TITLE={latest_title}\n")
            f.write(f"ARTICLE_LINK={latest_link}\n")
            f.write(f"ARTICLE_ID={latest_id}\n")

    print(f"New article found: {latest_title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
