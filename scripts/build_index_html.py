#!/usr/bin/env python3
"""
build_index_html.py - 根据 feed.xml 生成首页 index.html
"""
import os
import xml.etree.ElementTree as ET

FEED_FILE = "feed.xml"
OUTPUT_FILE = "docs/index.html"
AUDIO_BASE = "https://podcast.herebuy.us"

PODCAST_TITLE = "开源派技术播客"
PODCAST_DESC = "每周自动抓取 osp.io 最新文章，AI 主播播报"


def parse_feed():
    tree = ET.parse(FEED_FILE)
    root = tree.getroot()
    items = []
    for item in root.findall('.//item'):
        title_el = item.find('title')
        enclosure_el = item.find('enclosure')
        pubdate_el = item.find('pubDate')
        link_el = item.find('link')
        # link 可能在 link 标签或 href 属性里
        osp_link = link_el.text if link_el is not None else ""
        if not osp_link and link_el is not None:
            osp_link = link_el.get('href', '')
        title = title_el.text if title_el is not None else "无标题"
        audio_url = enclosure_el.get('url') if enclosure_el is not None else ""
        pub_date = pubdate_el.text if pubdate_el is not None else ""
        # 简化日期显示
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pub_date)
            date_str = dt.strftime('%Y-%m-%d')
        except Exception:
            date_str = pub_date[:10] if len(pub_date) >= 10 else pub_date
        items.append({'title': title, 'audio_url': audio_url, 'date': date_str, 'osp_link': osp_link})
    return items


def build_html(items):
    INITIAL_COUNT = 5  # 首次显示的节目数
    episodes_html = ""
    for i, ep in enumerate(items):
        title_link = ep.get('osp_link') or ep.get('audio_url') or '#'
        extra_class = "lazy-hidden" if i >= INITIAL_COUNT else ""
        if ep['audio_url']:
            episodes_html += f"""<li class="episode-item {extra_class}" {'style="display:none"' if i >= INITIAL_COUNT else ''}>
  <a href="{title_link}" target="_blank">{ep['title']}</a>
  <div class="date">📅 {ep['date']}</div>
  <audio controls src="{ep['audio_url']}"><a href="{ep['audio_url']}">下载音频</a></audio>
</li>\n"""
        else:
            episodes_html += f"""<li class="episode-item {extra_class}" {'style="display:none"' if i >= INITIAL_COUNT else ''}>
  <a href="{title_link}" target="_blank">{ep['title']}</a>
  <div class="date">📅 {ep['date']}</div>
</li>\n"""

    load_more_btn = f"""<button id="load-more-btn" onclick="loadMoreEpisodes()" style="display:block; width:100%; margin-top:1rem; padding:0.8rem; background:#0077cc; color:#fff; border:none; border-radius:10px; font-size:1rem; cursor:pointer;">
  查看更多节目（共 {len(items)} 期，展示前 {INITIAL_COUNT} 期）
</button>""" if len(items) > INITIAL_COUNT else ""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{PODCAST_TITLE}</title>
<!-- Counterscale Analytics -->
<script defer src="https://data.herebuy.us/tracker.js" data-site-id="podcast-herebuy"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 800px; margin: 0 auto; padding: 2rem 1rem; background: #f8f9fa; color: #222; }}
  h1 {{ color: #1a1a2e; margin-bottom: 0.5rem; }}
  .subtitle {{ color: #666; font-size: 1rem; margin-bottom: 2rem; }}
  .subtitle a {{ color: #0077cc; text-decoration: none; }}
  .subscribe {{ background: #fff; padding: 1.5rem; border-radius: 14px; margin: 1.5rem 0; box-shadow: 0 2px 12px rgba(0,0,0,0.07); }}
  .subscribe h2 {{ margin: 0 0 1rem 0; font-size: 1.1rem; color: #333; }}
  .subscribe a {{ display: inline-block; margin: 0.3rem 0.4rem 0.3rem 0; padding: 0.45rem 1rem; background: #0077cc; color: #fff; border-radius: 8px; text-decoration: none; font-size: 0.88rem; }}
  .subscribe a.rss {{ background: #f48024; }}
  .subscribe a:hover {{ opacity: 0.85; }}
  h2 {{ font-size: 1.2rem; color: #1a1a2e; margin: 2rem 0 1rem; }}
  .episodes {{ list-style: none; padding: 0; }}
  .episodes li {{ background: #fff; margin: 0.85rem 0; padding: 1.1rem 1.3rem; border-radius: 12px; box-shadow: 0 1px 6px rgba(0,0,0,0.05); }}
  .episodes li a {{ font-weight: 600; font-size: 1.05rem; color: #1a1a1a; text-decoration: none; }}
  .episodes li a:hover {{ color: #0077cc; }}
  .episodes li .date {{ color: #999; font-size: 0.82rem; margin: 0.35rem 0 0.5rem; }}
  audio {{ width: 100%; margin-top: 0.4rem; border-radius: 8px; }}
  .no-audio {{ color: #999; font-size: 0.85rem; margin-top: 0.4rem; }}
  footer {{ text-align: center; color: #aaa; font-size: 0.8rem; margin: 3rem 0 1rem; }}
  footer a {{ color: #999; text-decoration: none; }}
  #load-more-btn {{ background: #fff; color: #0077cc; border: 2px solid #0077cc; margin-top: 1rem; }}
  #load-more-btn:hover {{ background: #0077cc; color: #fff; }}
</style>
</head>
<body>
<h1>🎙️ {PODCAST_TITLE}</h1>
<p class="subtitle">每周自动抓取 <a href="https://osp.io">osp.io</a> 最新文章，AI 主播播报</p>

<div class="subscribe">
  <h2>📻 订阅播客</h2>
  <a href="feed.xml" class="rss">📡 RSS 订阅</a>
  <a href="https://podcasts.apple.com/podcast/idYOURID">🍎 Apple Podcasts</a>
  <a href="https://open.spotify.com/show/YOURID">💙 Spotify</a>
  <a href="https://www.xiaoyuzhoufm.com/podcast/YOURID">🌙 小宇宙</a>
</div>

<h2>📋 最新节目</h2>
<ul class="episodes">
{episodes_html if episodes_html else '<li>暂无节目，稍后刷新</li>'}
</ul>
{load_more_btn}

<footer>
  <a href="https://osp.io">开源派 OSP.IO</a> · 由 AI 自动生成
</footer>

<script>
function loadMoreEpisodes() {{
  var hidden = document.querySelectorAll('.lazy-hidden');
  hidden.forEach(function(el) {{
    el.style.display = '';
    el.classList.remove('lazy-hidden');
  }});
  document.getElementById('load-more-btn').style.display = 'none';
}}
</script>
</body>
</html>"""
    return html


if __name__ == '__main__':
    os.makedirs('docs', exist_ok=True)
    items = parse_feed()
    html = build_html(items)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Generated {OUTPUT_FILE} with {len(items)} episodes")
