#!/usr/bin/env python3
"""
check_articles.py - 检查 osp.io 是否有新文章（支持多篇）
总是返回 exit 0，检测结果通过 GITHUB_OUTPUT 传递：
  has_new=true/false
  new_links=URL1,URL2,...  （仅有新文章时）
  skipped=N   （跳过的文章数）
"""
import os
import sys
import feedparser

RSS_URL = "https://osp.io/feed"
FEED_URL = "https://podcast.herebuy.us/feed.xml"
MAX_ARTICLES = 5  # 最多检查最近 N 篇


def gh_output(key, value):
    """写入 GITHUB_OUTPUT"""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def get_feed_article_ids_with_audio(feed_url):
    """获取 podcast feed 里已有音频的 article_id 集合。

    article_id 从 URL link 里提取（如 .../12345 → 12345）。
    只有带 audio enclosure 的条目才认为已生成，避免 enclosure 丢失时误重试。
    """
    try:
        import re
        pf = feedparser.parse(feed_url)
        ids = set()
        for e in pf.entries:
            if hasattr(e, 'enclosures') and e.enclosures:
                for enc in e.enclosures:
                    if enc.get('type', '').startswith('audio/'):
                        # 从 link 里提取 article_id（如 https://osp.io/archives/12345）
                        m = re.search(r'/(\d+)/?$', e.get('link', ''))
                        if m:
                            ids.add(m.group(1))
                        break
        return ids
    except Exception:
        return set()


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    osp_feed = feedparser.parse(RSS_URL)
    if not osp_feed.entries:
        print("No entries found in osp.io RSS")
        gh_output("has_new", "false")
        return 0

    existing_ids = get_feed_article_ids_with_audio(FEED_URL)
    print(f"Podcast feed already has {len(existing_ids)} episodes")

    new_links = []
    skipped = 0
    for entry in osp_feed.entries[:MAX_ARTICLES]:
        import re
        m = re.search(r'/(\d+)/?$', entry.link)
        article_id = m.group(1) if m else None
        if article_id and article_id in existing_ids:
            print(f"  [skip] [{article_id}] {entry.title.strip()}")
            skipped += 1
        else:
            print(f"  [new]  [{article_id}] {entry.title.strip()} -> {entry.link}")
            new_links.append(entry.link)

    gh_output("skipped", str(skipped))

    if not new_links:
        print("No new articles — all up to date")
        gh_output("has_new", "false")
        return 0

    gh_output("has_new", "true")
    gh_output("new_links", ",".join(new_links))
    print(f"New articles to generate: {len(new_links)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
