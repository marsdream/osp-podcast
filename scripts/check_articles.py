#!/usr/bin/env python3
"""
check_articles.py - 检查 osp.io 是否有新文章
总是返回 0，has_new=true/false 通过 GITHUB_OUTPUT 传递
"""
import feedparser
import json
import os
import sys
import urllib.request

RSS_URL = "https://osp.io/feed"
STATE_FILE = "last_article.json"
GITHUB_REPO = "marsdream/osp-podcast"


def gh_output(key, value):
    """只写入 GITHUB_OUTPUT 文件（格式: key=value）"""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def get_gh_pages_tree_sha():
    """获取 gh-pages 分支的 tree SHA"""
    import subprocess
    result = subprocess.run(
        ["git", "ls-remote", "origin", "gh-pages"],
        capture_output=True, text=True, cwd=os.path.dirname(__file__)
    )
    if result.returncode == 0:
        # 返回格式: sha\trefs/heads/gh-pages
        parts = result.stdout.strip().split()
        if parts:
            return parts[0]
    return None


def fetch_gh_pages_episode_links():
    """通过 GitHub API 获取 gh-pages 上所有 episode JSON 的 link 字段"""
    import subprocess
    
    # 使用 git archive 直接获取 gh-pages 的内容
    # 或者通过 GitHub API tree
    result = subprocess.run(
        ["git", "fetch", "origin", "gh-pages:gh-pages", "--depth=1"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"git fetch gh-pages failed: {result.stderr[:200]}")
        return set()
    
    # 读取 gh-pages 分支上的 episode JSON 文件
    result = subprocess.run(
        ["git", "show", "gh-pages:episode_20260609.json"],
        capture_output=True, text=True
    )
    
    links = set()
    # 用 git ls-tree 获取 gh-pages 上所有 .json 文件
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "gh-pages"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            if line.endswith(".json") and not line.startswith("docs/"):
                # 这是个 episode JSON 文件（不在 docs/ 下）
                file_result = subprocess.run(
                    ["git", "show", f"gh-pages:{line}"],
                    capture_output=True, text=True
                )
                if file_result.returncode == 0:
                    try:
                        data = json.loads(file_result.stdout)
                        link = data.get("link", "")
                        if link:
                            links.add(link)
                    except json.JSONDecodeError:
                        pass
    return links


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        print("No entries found in RSS feed")
        gh_output("has_new", "false")
        return 0

    # 通过 git 直接读取 gh-pages 上的 episode JSON 文件
    existing_links = fetch_gh_pages_episode_links()
    print(f"Found {len(existing_links)} existing episodes on gh-pages")

    # 遍历所有 RSS entry，找到第一个没有生成过 episode 的文章
    new_article = None
    for entry in feed.entries:
        article_id = entry.get("id") or entry.link
        title = entry.title
        link = entry.link

        if link not in existing_links:
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