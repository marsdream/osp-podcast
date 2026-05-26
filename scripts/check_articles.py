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
STATE_FILE = "processed_articles.json"  # 追踪所有已处理文章 ID


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

    # 读取所有已处理文章 ID 集合
    processed_ids = set()
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            data = json.load(f)
            processed_ids = set(data.get("processed_ids", []))

    # 找出所有未处理的新文章（按 RSS 顺序，最旧的在前）
    new_articles = []
    for entry in feed.entries:
        article_id = entry.get("id") or entry.link
        if article_id not in processed_ids:
            new_articles.append({
                "id": article_id,
                "title": entry.title,
                "link": entry.link,
            })

    if not new_articles:
        print("No new articles — all caught up")
        gh_output("has_new", "false")
        return 0

    print(f"Found {len(new_articles)} new article(s)")
    for a in new_articles:
        print(f"  - {a['title']}")

    # 先更新 STATE_FILE（避免同一次运行重复处理）
    all_processed = processed_ids | {a["id"] for a in new_articles}
    with open(STATE_FILE, "w") as f:
        json.dump({"processed_ids": list(all_processed)}, f, ensure_ascii=False, indent=2)

    # 通过 GITHUB_OUTPUT 传递新文章列表（JSON 数组）
    articles_json = json.dumps(new_articles, ensure_ascii=False)
    gh_output("has_new", "true")
    gh_output("new_articles", articles_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
