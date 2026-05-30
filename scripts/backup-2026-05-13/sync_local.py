#!/usr/bin/env python3
"""
sync_local.py - 本地自主生成播客后的同步脚本
用法: python scripts/sync_local.py [episode_json]
不带参数：同步 episodes/ 下所有新的 mp3+json
带参数：只同步指定 episode json

流程：
  1. 更新 feed.xml（合并远程 feed + 本地 episodes/）
  2. 复制 mp3 + json 到 docs/episodes/
  3. 重新生成 index.html
  4. git add + commit + push
"""
import os
import sys
import subprocess
import json

EPISODES_DIR = "episodes"
DOCS_EPISODES_DIR = "docs/episodes"
FEED_FILE = "feed.xml"
INDEX_SCRIPT = "scripts/build_index_html.py"


def get_local_new_episodes():
    """找出 episodes/ 下有 mp3+json 的本地生成 episodes"""
    episodes = []
    if not os.path.isdir(EPISODES_DIR):
        print(f"  目录 {EPISODES_DIR} 不存在")
        return episodes
    for f in os.listdir(EPISODES_DIR):
        if not f.endswith(".json") or f == "last_article.json":
            continue
        path = os.path.join(EPISODES_DIR, f)
        try:
            with open(path) as fp:
                data = json.load(fp)
            if data.get("audio_file"):
                mp3_path = os.path.join(EPISODES_DIR, data["audio_file"])
                if os.path.exists(mp3_path):
                    episodes.append(data)
                    print(f"  ✓ {data.get('title', f)}")
                else:
                    print(f"  ✗ {f}: mp3 不存在 ({data.get('audio_file')})")
        except Exception as e:
            print(f"  ! {f}: {e}")
    return episodes


def run_cmd(cmd, desc=""):
    print(f"  $ {cmd}")
    r = os.system(cmd)
    if r != 0:
        print(f"  ❌ {desc} 失败 (exit {r})")
        return False
    return True


def main():
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    print("📡 读取本地 episodes/")
    eps = get_local_new_episodes()
    if not eps:
        print("没有找到新的本地 episodes，无需同步")
        return

    print(f"\n🔄 更新 feed.xml...")
    if not run_cmd(f"python3 scripts/update_rss.py", "update_rss"):
        return

    print(f"\n📋 复制文件到 docs/episodes/...")
    os.makedirs(DOCS_EPISODES_DIR, exist_ok=True)
    for ep in eps:
        mp3 = ep.get("audio_file", "")
        json_f = ep.get("id", "")
        if json_f:
            json_f = f"episode_{json_f}.json"
        else:
            # 从 path 反推
            for fj in os.listdir(EPISODES_DIR):
                if fj.endswith(".json"):
                    try:
                        with open(os.path.join(EPISODES_DIR, fj)) as f:
                            d = json.load(f)
                            if d.get("audio_file") == mp3:
                                json_f = fj
                                break
                    except:
                        pass
        if mp3:
            run_cmd(f"cp {EPISODES_DIR}/{mp3} {DOCS_EPISODES_DIR}/", f"cp mp3")
        if json_f:
            run_cmd(f"cp {EPISODES_DIR}/{json_f} {DOCS_EPISODES_DIR}/", f"cp json")

    print(f"\n🏠 重新生成 index.html...")
    if not run_cmd(f"python3 {INDEX_SCRIPT}", "build_index"):
        return

    print(f"\n📦 git commit...")
    titles = ", ".join(e.get("title", "?")[:20] for e in eps)
    run_cmd(f'git add -A && git commit -m "sync: {titles}"', "commit")

    print(f"\n🚀 git push...")
    if not run_cmd("git push origin main", "push"):
        return

    print(f"\n✅ 同步完成！{len(eps)} 个 episode 已推送")
    print("   CI 将自动部署到 podcast.herebuy.us")


if __name__ == "__main__":
    main()
