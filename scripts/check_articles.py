#!/usr/bin/env python3
"""
check_articles.py - 检查 osp.io 是否有新文章
总是返回 0，has_new=true/false 通过 GITHUB_OUTPUT 传递

去重策略：检查 osp.io 最新文章是否已在 feed.xml 里出现过。
如果 article_id（URL 或 guid）已在 feed.xml 的 episode 里，则跳过生成。
"""
import feedparser
import json
import os
import sys

RSS_URL = "https://osp.io/feed"
FEED_URL = "https://marsdream.github.io/osp-podcast/feed.xml"


def gh_output(key, value):
    """只写入 GITHUB_OUTPUT 文件（格式: key=value）"""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    # 读取 osp.io RSS
    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        print("No entries found in RSS feed")
        gh_output("has_new", "false")
        return 0

    latest = feed.entries[0]
    latest_id = latest.get("id") or latest.link
    latest_title = latest.title
    latest_link = latest.link

    # 读取 GitHub Pages 上的 feed.xml，检查最新 episode
    try:
        page_feed = feedparser.parse(FEED_URL)
        if page_feed.entries:
            latest_episode = page_feed.entries[0]
            episode_id = latest_episode.get("id") or latest_episode.link
            print(f"Latest osp.io article : {latest_title[:40]} [{latest_id}]")
            print(f"Latest feed episode  : {latest_episode.title[:40]} [{episode_id}]")
            if episode_id == latest_id:
                print("No new articles — skipping generation")
                gh_output("has_new", "false")
                return 0
    except Exception as e:
        print(f"  (could not read feed.xml, proceeding anyway: {e})")

    print(f"New article: {latest_title}")
    gh_output("has_new", "true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
