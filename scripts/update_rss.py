#!/usr/bin/env python3
"""
update_rss.py - 更新 RSS Feed
策略：读取远程 feed.xml + 本地 episodes/ 目录做合并
这样即使 episodes/ 只有本次生成的少数文件，也不会丢失历史 episodes
"""
import os
import sys
import json
import xml.etree.ElementTree as ET
import feedparser
from datetime import datetime
from email.utils import parsedate_to_datetime

EPISODES_DIR = "episodes"
RSS_FILE = "feed.xml"
REMOTE_FEED = os.environ.get("PODCAST_FEED_URL", "https://podcast.herebuy.us/feed.xml")
PODCAST_TITLE = "开源派技术播客"
PODCAST_DESC = "每周自动抓取 osp.io 最新文章，生成中文播客，由 AI 主播播报"
CF_AUDIO_BASE = "https://podcast.herebuy.us"
PODCAST_LINK = os.environ.get("PODCAST_BASE_URL", "https://podcast.herebuy.us/")
# 播客封面图（Apple Podcasts 要求 1400x1400 ~ 3000x3000）
PODCAST_COVER_URL = "https://raw.githubusercontent.com/marsdream/osp-podcast/main/cover.png"


def get_remote_episodes():
    """从远程 feed.xml 读取已有的 episodes"""
    try:
        feed = feedparser.parse(REMOTE_FEED)
        episodes = []
        for entry in feed.entries:
            ep = {
                "title": entry.title,
                "date": entry.get("published") or entry.get("updated", ""),
                "enclosure_url": "",
                "description": getattr(entry, "summary", "")[:500] if hasattr(entry, "summary") else "",
            }
            # feedparser 用 entry.enclosures（列表）访问 enclosure，而非 entry.get("enclosure")
            if entry.get("enclosures"):
                ep["enclosure_url"] = entry.enclosures[0].href
            # osp.io 原文链接
            ep["link"] = entry.get("link", "")
            episodes.append(ep)
        print(f"  远程 feed 有 {len(episodes)} 个 episodes")
        return episodes
    except Exception as e:
        print(f"  读取远程 feed 失败: {e}，从头开始")
        return []


def get_local_episodes():
    """从本地 episodes/ 目录读取新生成的 episodes（覆盖远程的）"""
    episodes = {}
    if not os.path.isdir(EPISODES_DIR):
        return episodes
    for f in os.listdir(EPISODES_DIR):
        if not f.endswith(".json") or f == "last_article.json":
            continue
        path = os.path.join(EPISODES_DIR, f)
        try:
            with open(path) as fp:
                data = json.load(fp)
            # 新生成的 episodes 有 audio_file 字段
            if data.get("audio_file"):
                key = data.get("title", "")
                episodes[key] = data
        except Exception:
            pass
    print(f"  本地 episodes/ 有 {len(episodes)} 个新生成的")
    return episodes


def get_episode_link(ep):
    """获取 episode 对应的 osp.io 原文链接"""
    # 本地 episodes/ 有 link 字段
    if ep.get("link"):
        return ep["link"]
    # 远程 feed entries 有 link 字段
    if ep.get("enclosure_url"):
        # 从 enclosure_url 提取 osp.io 文章 ID 做简单映射
        # enclosure_url 格式: https://podcast.herebuy.us/episodes/xxx.mp3
        return ""
    return ""


def build_rss(remote_episodes, local_episodes):
    """合并远程 episodes 和本地新生成的 episodes

    重要：只有音频文件真实存在于 episodes/ 目录的 episode 才会被加入 feed。
    防止本地 TTS 生成失败（无音频文件）时仍将不完整的 entry 写入 feed。
    """
    merged = {}
    for ep in remote_episodes:
        title = ep.get("title", "")
        if title not in local_episodes:
            merged[title] = ep

    for title, ep in local_episodes.items():
        audio_file = ep.get("audio_file", "")
        local_path = os.path.join(EPISODES_DIR, audio_file)
        if audio_file and os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
            merged[title] = {
                "title": ep.get("title", "untitled"),
                "date": ep.get("date", ""),
                "audio_file": audio_file,
                "description": "",
                "link": ep.get("link", ""),
            }
        else:
            print(f"  [警告] 跳过 '{title}'：audio_file='{audio_file}' 但本地文件不存在或为空，"
                  f"不写入 feed（防止无音频 entry）")

    # 按日期倒序排列
    episode_list = list(merged.values())
    episode_list.sort(key=lambda x: x.get("date", ""), reverse=True)
    return episode_list


def make_rss_xml(episodes):
    rss = ET.Element("rss", version="2.0")
    rss.set("xmlns:itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = PODCAST_TITLE
    ET.SubElement(channel, "description").text = PODCAST_DESC
    ET.SubElement(channel, "link").text = PODCAST_LINK
    ET.SubElement(channel, "language").text = "zh-CN"
    ET.SubElement(channel, "itunes:category", text="Technology")
    ET.SubElement(channel, "itunes:author").text = "开源派"
    # Apple Podcasts 频道封面图
    ET.SubElement(channel, "itunes:image", href=PODCAST_COVER_URL)

    for ep in episodes:
        item = ET.SubElement(channel, "item")
        ep_title = ep.get("title", "untitled")
        ep_desc = ep.get("description", "")[:500] or f"开源派技术播客：{ep_title}。收听更多精彩开源技术内容，请访问 https://osp.io"
        ET.SubElement(item, "title").text = ep_title
        ET.SubElement(item, "description").text = ep_desc
        # itunes:summary 支持更长内容，Apple Podcasts 显示为 Show Notes
        ET.SubElement(item, "itunes:summary").text = ep_desc
        ET.SubElement(item, "pubDate").text = ep.get("date", "")

        audio_file = ep.get("audio_file", "")
        if audio_file:
            audio_url = f"{CF_AUDIO_BASE}/episodes/{audio_file}"
            # 获取本地文件大小
            audio_size = 0
            local_path = os.path.join(EPISODES_DIR, audio_file)
            if os.path.exists(local_path):
                audio_size = os.path.getsize(local_path)
            elif ep.get("enclosure_url"):
                audio_url = ep.get("enclosure_url")
            ET.SubElement(item, "enclosure", url=audio_url,
                         type="audio/mpeg", length=str(audio_size))
        elif ep.get("enclosure_url"):
            ET.SubElement(item, "enclosure", url=ep["enclosure_url"],
                         type="audio/mpeg", length="0")
        # 添加 osp.io 原文链接
        ep_link = ep.get("link", "")
        if ep_link:
            ET.SubElement(item, "link").text = ep_link
        # 每集封面图（与频道封面相同，Apple 会自动适配）
        ET.SubElement(item, "itunes:image", href=PODCAST_COVER_URL)

    return rss


def indent(elem, level=0):
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for child in elem:
            indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def make_index_html(episodes):
    """生成 episodes 列表页 index.html"""
    episodes_html = ""
    for ep in episodes:
        title = ep.get("title", "untitled")
        date_raw = ep.get("date", "")
        # 格式化日期显示
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_raw)
            date_display = dt.strftime("%Y-%m-%d")
        except Exception:
            date_display = date_raw[:10] if date_raw else "?"
        link = ep.get("link", "")
        audio_file = ep.get("audio_file", "")
        enclosure_url = ep.get("enclosure_url", "")
        audio_url = ""
        if audio_file:
            audio_url = f"{CF_AUDIO_BASE}/episodes/{audio_file}"
        elif enclosure_url:
            audio_url = enclosure_url

        title_escaped = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        article_link_html = f'<a href="{link}" target="_blank" style="color:#666;font-size:13px;">📖 阅读原文</a>' if link else ""

        if audio_url:
            audio_html = f'''
        <div class="audio-row">
          <audio controls preload="none" src="{audio_url}"></audio>
        </div>'''
        else:
            audio_html = '<div class="audio-row"><span style="color:#999;font-size:13px;">⏳ 音频生成中...</span></div>'

        episodes_html += f'''
    <div class="episode">
      <div class="episode-header">
        <span class="date">📅 {date_display}</span>
        {article_link_html}
      </div>
      <h2 class="title">{title_escaped}</h2>
      {audio_html}
    </div>'''

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{PODCAST_TITLE}</title>
<meta name="description" content="{PODCAST_DESC}">
<link rel="alternate" type="application/rss+xml" title="{PODCAST_TITLE}" href="feed.xml">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #fafafa; color: #333; max-width: 720px; margin: 0 auto; padding: 20px; }}
  header {{ text-align: center; margin-bottom: 32px; padding: 24px 0; border-bottom: 1px solid #eee; }}
  h1 {{ font-size: 24px; font-weight: 600; margin-bottom: 8px; }}
  .subtitle {{ color: #888; font-size: 14px; }}
  .rss-link {{ display: inline-block; margin-top: 12px; padding: 6px 14px; background: #e67e22; color: #fff; border-radius: 20px; font-size: 13px; text-decoration: none; }}
  .episode {{ background: #fff; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .episode-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
  .date {{ color: #888; font-size: 13px; }}
  .title {{ font-size: 17px; font-weight: 500; margin-bottom: 12px; line-height: 1.4; }}
  .audio-row audio {{ width: 100%; height: 40px; }}
  footer {{ text-align: center; color: #aaa; font-size: 12px; margin-top: 32px; }}
</style>
</head>
<body>
<header>
  <h1>{PODCAST_TITLE}</h1>
  <p class="subtitle">{PODCAST_DESC}</p>
  <a class="rss-link" href="feed.xml">📡 RSS 订阅</a>
</header>
<main>
{episodes_html}
</main>
<footer>
  <p>由 AI 自动生成 · 更新于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</footer>
</body>
</html>"""
    return html


def main():
    print("读取远程 feed...")
    remote = get_remote_episodes()
    print("读取本地 episodes/...")
    local = get_local_episodes()
    episodes = build_rss(remote, local)
    print(f"合并后共 {len(episodes)} 个 episodes")

    rss = make_rss_xml(episodes)
    indent(rss)
    tree = ET.ElementTree(rss)
    tree.write(RSS_FILE, encoding="utf-8", xml_declaration=True)
    print(f"RSS updated: {RSS_FILE}")

    # 生成 index.html
    index_html = make_index_html(episodes)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"index.html updated ({len(episodes)} episodes)")


if __name__ == "__main__":
    main()
