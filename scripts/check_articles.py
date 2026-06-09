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


def episode_exists(article_id):
    """检查是否有对应 episode 文件（osp-podcast-YYYYMMDD.json 或 episode_YYYYMMDD*.json）"""
    if not os.path.exists("episodes"):
        return False
    for fname in os.listdir("episodes"):
        if fname.endswith(".json"):
            return True
    return False


def extract_date_from_link(link):
    """从文章链接提取日期部分，如 /archives/10444 -> 20260605（近似）"""
    # osp.io 文章 link 格式: https://osp.io/archives/XXXXX
    # 我们用 article id 的发布时间来匹配，但更可靠的方式是扫描已有 episode 文件
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        print("No entries found in RSS feed")
        gh_output("has_new", "false")
        return 0

    # 遍历所有 RSS entry，找到第一个没有生成过 episode 的文章
    # 这样即使 entry[0] 是已处理的，entry[N] 也会被找到
    new_article = None
    for entry in feed.entries:
        article_id = entry.get("id") or entry.link
        title = entry.title
        link = entry.link

        # 检查是否已有 episode 文件（通过扫描 episodes/ 目录）
        # episode 文件命名: osp-podcast-YYYYMMDD_*.json 或 episode_YYYYMMDD*.json
        # 简单策略：检查 episodes/ 目录是否有对应日期的文件
        # 更可靠：检查是否有任何 episode JSON 包含此 article 的 link
        # Scan top-level episode JSON files (gh-pages structure: episode_YYYYMMDD*.json, osp-podcast-*.json)
        # Also scan docs/episodes/ (for mp3s)
        scan_dirs = ["docs", "."]  # docs/ has JSONs from rsync, . has top-level episode JSONs
        found = False
        for scan_dir in scan_dirs:
            if not os.path.isdir(scan_dir):
                continue
            for fname in os.listdir(scan_dir):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(scan_dir, fname)
                try:
                    with open(fpath) as f:
                        ep_data = json.load(f)
                    if ep_data.get("link") == link:
                        found = True
                        break
                except (json.JSONDecodeError, IOError):
                    continue
            if found:
                break

        if not found:
            new_article = {"id": article_id, "title": title, "link": link}
            break

    if new_article is None:
        print("No new articles — all already have episodes, skipping generation")
        gh_output("has_new", "false")
        return 0

    # 更新 state file
    with open(STATE_FILE, "w") as f:
        json.dump(new_article, f, ensure_ascii=False, indent=2)

    print(f"New article: {new_article['title']}")
    gh_output("has_new", "true")
    gh_output("new_article_link", new_article["link"])
    return 0


if __name__ == "__main__":
    sys.exit(main())