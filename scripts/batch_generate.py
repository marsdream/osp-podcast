#!/usr/bin/env python3
"""batch_generate.py - 每轮最多处理3篇文章的播客生成"""
import os
import sys
import json
import subprocess

MAX_PER_RUN = 3

def main():
    # 从 GITHUB_OUTPUT 读取 new_articles
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    new_articles_json = ""

    if github_output and os.path.exists(github_output):
        with open(github_output) as f:
            for line in f:
                if line.startswith("new_articles="):
                    new_articles_json = line[len("new_articles="):].strip()
                    break

    if not new_articles_json:
        print("No new_articles found in GITHUB_OUTPUT")
        return 0

    articles = json.loads(new_articles_json)
    to_process = articles[:MAX_PER_RUN]

    if not to_process:
        print("No articles to process")
        return 0

    print(f"Processing {len(to_process)} article(s) this run")
    for i, a in enumerate(to_process):
        print(f"[{i+1}/{len(to_process)}] {a['title']}")
        result = subprocess.run([
            sys.executable, "scripts/generate_podcast.py",
            "--link", a["link"],
            "--base-url", "https://api.deepseek.com/v1",
            "--model", "deepseek-chat"
        ], env={**os.environ})
        if result.returncode != 0:
            print(f"  FAILED: exit {result.returncode}")
        else:
            print(f"  OK")

    return 0

if __name__ == "__main__":
    sys.exit(main())