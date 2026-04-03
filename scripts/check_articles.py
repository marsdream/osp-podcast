#!/usr/bin/env python3
"""
check_articles.py - 检查 osp.io 是否有新文章
总是返回 0，has_new=true/false 通过 GITHUB_OUTPUT 传递

去重策略：对比 osp.io 最新文章标题 和 GitHub Pages feed.xml 第一个 episode 的标题。
如果标题相同，说明已经生成过，跳过。
"""
import os
import sys
import feedparser

RSS_URL = "https://osp.io/feed"
FEED_URL = "https://podcast.herebuy.us/feed.xml"


def gh_output(key, value):
    """只写入 GITHUB_OUTPUT 文件（格式: key=value）"""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    # 读取 osp.io RSS 最新文章标题
    osp_feed = feedparser.parse(RSS_URL)
    if not osp_feed.entries:
        print("No entries found in osp.io RSS")
        gh_output("has_new", "false")
        return 0

    latest = osp_feed.entries[0]
    latest_title = latest.title
    latest_link = latest.link

    print(f"Latest osp.io article: {latest_title}")
    print(f"  link: {latest_link}")

    # 读取 GitHub Pages feed.xml 最新 episode 标题
    try:
        page_feed = feedparser.parse(FEED_URL)
        if page_feed.entries:
            latest_episode_title = page_feed.entries[0].get("title", "")
            print(f"Latest feed episode : {latest_episode_title}")

            # 标题相同 → 已生成过，跳过
            if latest_title == latest_episode_title:
                print("No new articles — already in feed, skipping generation")
                gh_output("has_new", "false")
                return 0
        else:
            print("Feed has no episodes yet — will generate first episode")
    except Exception as e:
        print(f"  (could not read feed.xml, proceeding anyway: {e})")

    print(f"New article: {latest_title}")
    gh_output("has_new", "true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
