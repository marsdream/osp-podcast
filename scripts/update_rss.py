#!/usr/bin/env python3
"""
update_rss.py - 更新 RSS Feed
读取 episodes/ 目录下的 JSON 元数据，生成 feed.xml
"""
import os
import json
import xml.etree.ElementTree as ET
from datetime import datetime

EPISODES_DIR = "episodes"
RSS_FILE = "feed.xml"
PODCAST_TITLE = "开源派技术播客"
PODCAST_DESC = "每周自动抓取 osp.io 最新文章，生成中文播客，由 AI 主播播报"
PODCAST_LINK = "https://marsdream.github.io/osp-podcast/"


def get_episodes():
    """读取所有 episode JSON 元数据"""
    episodes = []
    for f in os.listdir(EPISODES_DIR):
        if f.startswith("episode_") and f.endswith(".json"):
            path = os.path.join(EPISODES_DIR, f)
            with open(path) as fp:
                episodes.append(json.load(fp))
    episodes.sort(key=lambda x: x.get("date", ""), reverse=True)
    return episodes


def build_rss(episodes):
    """构建 RSS XML"""
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
        ET.SubElement(item, "description").text = ep.get("script", "")[:500]
        ET.SubElement(item, "pubDate").text = ep.get("date", "")

        audio_file = ep.get("audio_file", "")
        if audio_file:
            audio_path = f"{PODCAST_LINK}episodes/{audio_file}"
            audio_size = 0
            full_path = os.path.join(EPISODES_DIR, audio_file)
            if os.path.exists(full_path):
                audio_size = os.path.getsize(full_path)
            ET.SubElement(item, "enclosure", url=audio_path,
                         type="audio/mpeg", length=str(audio_size))

    return rss


def indent(elem, level=0):
    """美化 XML 缩进"""
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
    episodes = get_episodes()
    print(f"Found {len(episodes)} episodes")

    rss = build_rss(episodes)
    indent(rss)
    tree = ET.ElementTree(rss)
    tree.write(RSS_FILE, encoding="utf-8", xml_declaration=True)

    print(f"RSS updated: {RSS_FILE}")


if __name__ == "__main__":
    main()
