#!/usr/bin/env python3
"""generate_index.py - 从 episode JSON 生成 index.html（加载更多分页）"""
import os, json, glob

EPISODES_DIR = "episodes"
OUTPUT = "index.html"
INITIAL_SHOW = 5   # 默认显示最新 N 条

episodes = []
seen_links = set()  # 去重：同 link 只取第一次出现
# 新格式 episode_*.json（优先）
for f in sorted(glob.glob(f"{EPISODES_DIR}/episode_*.json")):
    with open(f, encoding="utf-8") as fp:
        ep = json.load(fp)
    link = ep.get("link", "")
    if link in seen_links:
        continue
    seen_links.add(link)
    mp3 = ep.get("audio_file", "")
    local_path = os.path.join(EPISODES_DIR, mp3)
    deployed_path = os.path.join("docs", EPISODES_DIR, mp3)
    if mp3 and (os.path.exists(local_path) or os.path.exists(deployed_path)):
        size = os.path.getsize(local_path if os.path.exists(local_path) else deployed_path)
        if size > 100000:
            episodes.append(ep)
# 旧格式 osp-podcast-*.json（从未重写的老 episode）
for f in sorted(glob.glob(f"docs/{EPISODES_DIR}/osp-podcast-*.json")) + \
         sorted(glob.glob(f"{EPISODES_DIR}/osp-podcast-*.json")):
    with open(f, encoding="utf-8") as fp:
        ep = json.load(fp)
    link = ep.get("link", "")
    if link in seen_links:
        continue
    seen_links.add(link)
    mp3 = ep.get("audio_file", "")
    local_path = os.path.join(EPISODES_DIR, mp3)
    deployed_path = os.path.join("docs", EPISODES_DIR, mp3)
    if mp3 and (os.path.exists(local_path) or os.path.exists(deployed_path)):
        path = local_path if os.path.exists(local_path) else deployed_path
        size = os.path.getsize(path)
        if size > 100000:
            episodes.append(ep)

episodes.sort(key=lambda x: x.get("date", ""), reverse=True)

html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>开源派技术播客</title>
<meta name="description" content="每周自动抓取 osp.io 最新文章，生成中文播客，由 AI 主播播报">
<link rel="alternate" type="application/rss+xml" title="开源派技术播客" href="feed.xml">
<script defer src="https://data.herebuy.us/tracker.js" data-site-id="podcast-herebuy"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fafafa; color: #333; max-width: 720px; margin: 0 auto; padding: 20px; }
  header { text-align: center; margin-bottom: 32px; padding: 24px 0; border-bottom: 1px solid #eee; }
  h1 { font-size: 24px; font-weight: 600; margin-bottom: 8px; }
  .subtitle { color: #888; font-size: 14px; }
  .rss-link { display: inline-block; margin-top: 12px; padding: 6px 14px; background: #e67e22; color: #fff; border-radius: 20px; font-size: 13px; text-decoration: none; }
  .episode { background: #fff; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
  .episode.hidden { display: none; }
  .episode-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .date { color: #888; font-size: 13px; }
  .title { font-size: 17px; font-weight: 500; margin-bottom: 12px; line-height: 1.4; }
  .audio-row audio { width: 100%; height: 40px; }
  /* 隐藏原生 audio 下载按钮 */
  audio::-webkit-media-controls-download-button { display: none !important; }
  audio::-webkit-media-controls { overflow: hidden; }
  .read-original { color: #666; font-size: 13px; text-decoration: none; }
  .read-original:hover { color: #0077cc; }
  #load-more { display: none; width: 100%; padding: 12px; margin-top: 8px; background: #f0f0f0; border: none; border-radius: 8px; font-size: 14px; color: #666; cursor: pointer; }
  #load-more:hover { background: #e0e0e0; }
  #load-more.visible { display: block; }
  footer { text-align: center; color: #aaa; font-size: 12px; margin-top: 32px; }
</style>
</head>
<body>
<header>
  <h1>🎙️ 开源派技术播客</h1>
  <p class="subtitle">每周自动抓取 osp.io 最新文章，生成中文播客，由 AI 主播播报</p>
  <a class="rss-link" href="feed.xml">📡 RSS 订阅</a>
</header>
<main>
'''

for i, ep in enumerate(episodes):
    date = ep.get("date", "")[:10]
    title = ep.get("title", "")
    link = ep.get("link", "")
    mp3 = ep.get("audio_file", "")
    mp3_url = f"https://podcast.herebuy.us/episodes/{mp3}"
    hidden = 'class="episode hidden"' if i >= INITIAL_SHOW else 'class="episode"'
    html += f'''  <div {hidden}>
    <div class="episode-header">
      <span class="date">📅 {date}</span>
      <a class="read-original" href="{link}" target="_blank">📖 阅读原文</a>
    </div>
    <h2 class="title">{title}</h2>
    <div class="audio-row">
      <audio controls preload="none" controlsList="nodownload" src="{mp3_url}"></audio>
    </div>
  </div>
'''

hidden_count = max(0, len(episodes) - INITIAL_SHOW)
init_count = INITIAL_SHOW
html += f'''</main>
<button id="load-more" class="{"visible" if hidden_count > 0 else ""}">
  加载更多 ({hidden_count} 条)
</button>
<footer>© 2026 开源派 · <a href="https://osp.io">osp.io</a></footer>
<script>
  const btn = document.getElementById('load-more');
  const hidden = document.querySelectorAll('.episode.hidden');
  let showing = {init_count};
  btn && btn.addEventListener('click', () => {{
    hidden.forEach((el, i) => {{
      if (i < showing) el.style.display = 'block';
    }});
    showing += {init_count};
    if (showing >= hidden.length) btn.style.display = 'none';
  }});
</script>
</body>
</html>'''

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Generated {OUTPUT}: {len(episodes)} episodes ({hidden_count} hidden)")