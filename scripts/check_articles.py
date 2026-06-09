#!/usr/bin/env python3
"""
check_articles.py - 检查 osp.io 是否有新文章
总是返回 0，has_new=true/false 通过 GITHUB_OUTPUT 传递
"""
import feedparser
import json
import os
import sys
import subprocess

RSS_URL = "https://osp.io/feed"
STATE_FILE = "last_article.json"


def gh_output(key, value):
    """只写入 GITHUB_OUTPUT 文件（格式: key=value）"""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def fetch_gh_pages_episode_links():
    """通过 git archive 获取 gh-pages 上所有 episode JSON 的 link 字段"""
    import io
    import tarfile
    
    links = set()
    
    # 先确保本地有完整的 gh-pages
    subprocess.run(
        ["git", "fetch", "origin", "gh-pages:gh-pages"],
        capture_output=True, text=True
    )
    
    # 使用 git archive 获取 gh-pages 的文件列表
    result = subprocess.run(
        ["git", "archive", "--prefix=gh-pages/", "gh-pages"],
        capture_output=True, timeout=30
    )
    if result.returncode != 0:
        print(f"git archive failed: {result.stderr[:200]}")
        return links
    
    try:
        tar = tarfile.open(fileobj=io.BytesIO(result.stdout), mode='r')
        for member in tar.getmembers():
            path = member.name
            if path.endswith(".json") and not path.startswith("gh-pages/docs/"):
                f = tar.extractfile(member)
                if f:
                    try:
                        data = json.loads(f.read().decode("utf-8"))
                        link = data.get("link", "")
                        if link:
                            links.add(link)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
        tar.close()
    except Exception as e:
        print(f"tar parse error: {e}")
    
    return links


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        print("No entries found in RSS feed")
        gh_output("has_new", "false")
        return 0

    # 通过 git archive 读取 gh-pages 上的 episode JSON 文件
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