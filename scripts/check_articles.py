#!/usr/bin/env python3
"""
check_articles.py - 检查 osp.io 是否有新文章
写入 has_new.txt 供后续步骤判断
"""
import feedparser
import json
import os

RSS_URL = "https://osp.io/feed"
STATE_FILE = "last_article.json"
OUTPUT_FILE = "has_new.txt"


def main():
    try:
        feed = feedparser.parse(RSS_URL)
        if not feed.entries:
            print("ERROR: No entries in RSS feed", flush=True)
            with open(OUTPUT_FILE, "w") as f:
                f.write("false")
            return

        latest = feed.entries[0]
        latest_id = latest.get("id") or latest.link
        latest_title = latest.title
        latest_link = latest.link

        has_new = True
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                last = json.load(f)
            if last.get("id") == latest_id:
                print("No new articles — skipping", flush=True)
                has_new = False

        if has_new:
            article_data = {
                "id": latest_id,
                "title": latest_title,
                "link": latest_link,
            }
            with open(STATE_FILE, "w") as f:
                json.dump(article_data, f, ensure_ascii=False, indent=2)
            print(f"New article found: {latest_title}", flush=True)

        with open(OUTPUT_FILE, "w") as f:
            f.write("true" if has_new else "false")
        print(f"has_new={has_new}", flush=True)

    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()
        with open(OUTPUT_FILE, "w") as f:
            f.write("false")


if __name__ == "__main__":
    main()
