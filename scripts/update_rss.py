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

EPISODES_DIR = "episodes"
RSS_FILE = "feed.xml"
REMOTE_FEED = os.environ.get("PODCAST_FEED_URL", "https://podcast.herebuy.us/feed.xml")
PODCAST_TITLE = "开源派技术播客"
PODCAST_DESC = "每周自动抓取 osp.io 最新文章，生成中文播客，由 AI 主播播报"
CF_AUDIO_BASE = "https://podcast.herebuy.us"
PODCAST_LINK = os.environ.get("PODCAST_BASE_URL", "https://podcast.herebuy.us/")


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
            enclosure = entry.get("enclosure", {})
            if enclosure:
                ep["enclosure_url"] = enclosure.get("url", "")
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


def build_rss(remote_episodes, local_episodes):
    """合并远程 episodes 和本地新生成的 episodes"""
    # 用本地新生成的覆盖远程已有的（同一标题）
    merged = {}
    for ep in remote_episodes:
        title = ep.get("title", "")
        if title not in local_episodes:
            merged[title] = ep

    for title, ep in local_episodes.items():
        merged[title] = {
            "title": ep.get("title", "untitled"),
            "date": ep.get("date", ""),
            "audio_file": ep.get("audio_file", ""),
            "description": "",
        }

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

    for ep in episodes:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = ep.get("title", "untitled")
        ET.SubElement(item, "description").text = ep.get("description", "")[:500]
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


if __name__ == "__main__":
    main()
