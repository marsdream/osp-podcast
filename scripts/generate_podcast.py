#!/usr/bin/env python3
"""
generate_podcast.py - 生成 osp.io 播客音频
从 osp.io RSS 获取文章，用 AI 生成播客对话脚本，Edge-TTS 合成音频
"""
import os
import sys
import json
import re
import subprocess
import argparse
import shutil
from datetime import datetime

try:
    import feedparser
except ImportError:
    print("ERROR: feedparser not installed. Run: pip install feedparser")
    sys.exit(1)

# 用 Podcast-Generator 的 JSON prompt 技术
PODCAST_PROMPT_TEMPLATE = """* **Output Format:** No explanatory text！Make sure the language of the output content is Chinese

<podcast_generation_system>
You are a master podcast scriptwriter, adept at transforming diverse input content into a lively, engaging, and natural-sounding conversation between multiple distinct podcast hosts.

<input>
  <podcast_settings>
    <num_speakers>2</num_speakers>
    <turn_pattern>random</turn_pattern>
  </podcast_settings>
  <source_content>
{{content}}
  </source_content>
</input>

<guidelines>
1. **Distinct Host Personas:**
   * Speaker 0 (主播/女声): 引导对话，热情活泼，像朋友聊天，风格轻松
   * Speaker 1 (专家/男声): 技术深度，用通俗语言解释，有深度但不装

2. **Natural Dialogue:** 使用真实口语，像两个人在咖啡馆聊天。不要"首先、其次、最后"。用"咱们、其实、你知道吗、对对对"。

3. **Pure Dialog Only:** dialog 字段里只放对话内容，不要任何角色前缀。不要"主播："、"专家："、"speaker："这类标签。

4. **No Self-Reference by Name:** 对话中禁止 Speaker 自己提及自己的名字。梅梅不能说出"梅梅"二字，开源君不能说出"开源君"二字。名字只能由对方提起（打招呼、问观点等场景）。例如："开源君，你怎么看"是正确的（梅梅提起对方名字）；"梅梅，你觉得呢"也是正确的（开源君提起对方名字）。但梅梅自己的 dialog 里不能出现"梅梅"，开源君自己的 dialog 里不能出现"开源君"。

5. **Random Turn Pattern:** 两人自然交替，类似真实聊天节奏。

6. **Duration:** 约 3-5 分钟的对话量，内容要充实。
</guidelines>

<output_format>
{{
"podcast_transcripts": [
  {{
    "speaker_id": 0,
    "dialog": "大家好，欢迎来到开源派！今天我们来聊聊"
  }},
  {{
    "speaker_id": 1,
    "dialog": "对，这个话题很有意思，我来给大家讲讲"
  }}
]
}}
</output_format>
</podcast_generation_system>

Transform the source material into a lively and engaging podcast conversation. The final output is a JSON string without code blocks. No explanatory text!
"""

# speaker_id → Edge-TTS voice
SPEAKER_VOICES = {
    0: "zh-CN-XiaoxiaoNeural",   # 女声-晓晓
    1: "zh-CN-YunyangNeural",    # 男声-云扬
}

# 模板路径（GitHub Actions 会把仓库 checkout 下来）
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
INTRO_FILE = os.path.join(TEMPLATE_DIR, "intro.mp3")
OUTRO_FILE = os.path.join(TEMPLATE_DIR, "outro.mp3")


def fetch_article_content(url, target_link=None):
    """通过 feedparser 获取文章内容
    
    Args:
        url: RSS feed URL
        target_link: 如果指定，只返回 link 匹配的那篇文章；否则返回 entry[0]
    """
    feed = feedparser.parse(url)
    if not feed.entries:
        return None, None, ""

    if target_link:
        # 遍历找到匹配的文章
        for entry in feed.entries:
            entry_link = entry.get("link", "")
            if entry_link == target_link:
                content = ""
                if hasattr(entry, "content") and entry.content:
                    content = entry.content[0].value
                elif hasattr(entry, "summary"):
                    content = entry.summary
                else:
                    content = entry.get("description", "")
                # 尝试解析 published date 用于 episode_id
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    import time
                    published = datetime(*entry.published_parsed[:6])
                return entry.title, content, entry_link, published
        # 没找到匹配的，返回 None
        print(f"WARNING: target_link={target_link} not found in RSS, falling back to entry[0]")
    
    # 默认返回 entry[0]
    entry = feed.entries[0]
    content = ""
    if hasattr(entry, "content") and entry.content:
        content = entry.content[0].value
    elif hasattr(entry, "summary"):
        content = entry.summary
    else:
        content = entry.get("description", "")
    published = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        import time
        published = datetime(*entry.published_parsed[:6])
    return entry.title, content, entry.get("link", ""), published


def generate_script(title, content, api_key=None, base_url=None, model=None):
    """调用 OpenAI 兼容 API 生成播客脚本（JSON 格式）"""
    try:
        import openai
    except ImportError:
        print("ERROR: openai not installed. Run: pip install openai")
        return None, None

    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        print("ERROR: OPENAI_API_KEY not set")
        return None, None

    url = base_url or os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    model_name = model or os.environ.get("LLM_MODEL", "qwen/qwen-plus")

    print(f"Using LLM: {model_name} via {url}")

    client = openai.OpenAI(api_key=key, base_url=url)

    # Podcast-Generator 风格的 XML prompt
    prompt = PODCAST_PROMPT_TEMPLATE.replace("{{content}}", content[:4000])

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "你是一个专业的中文播客编剧。"},
            {"role": "user", "content": prompt}
        ],
        max_tokens=3000,
        temperature=0.7
    )

    raw = response.choices[0].message.content

    # 提取 JSON（去掉 markdown code blocks）
    raw = raw.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    try:
        data = json.loads(raw)
        transcripts = data.get("podcast_transcripts", [])
        print(f"解析到 {len(transcripts)} 段对话")
        return transcripts, raw
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}")
        print(f"Raw: {raw[:300]}")
        return None, raw


def synthesize_audio(text, voice, output_path):
    """用 edge-tts 生成音频"""
    cmd = [
        sys.executable, "-m", "edge_tts",
        "--text", text,
        "--voice", voice,
        "--write-media", output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"TTS error: {result.stderr}", file=sys.stderr)
        return False
    return True


def has_intro_outro():
    """检查是否有片头片尾音乐模板"""
    return os.path.exists(INTRO_FILE) and os.path.exists(OUTRO_FILE)


def add_intro_outro(input_mp3, output_mp3):
    """给音频加上片头片尾音乐（淡入淡出）"""
    if not has_intro_outro():
        # 没有模板就直接复制
        shutil.copy2(input_mp3, output_mp3)
        return

    intro = INTRO_FILE
    outro = OUTRO_FILE

    # 拼接：intro + content + outro
    concat_file = output_mp3 + ".concat.txt"
    abs_input = os.path.abspath(input_mp3)
    abs_intro = os.path.abspath(intro)
    abs_outro = os.path.abspath(outro)

    with open(concat_file, "w") as f:
        f.write(f"file '{abs_intro}'\n")
        f.write(f"file '{abs_input}'\n")
        f.write(f"file '{abs_outro}'\n")

    # 用 filter_complex 实现淡入淡出
    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-filter_complex",
        "[0]afade=t=in:st=0:d=1[intro];[1]apad=whole_dur=1[content];[2]afade=t=out:st=0:d=1[outro];[intro][content][outro]concat=n=3:v=0:a=1[out]",
        "-map", "[out]",
        "-codec:a", "libmp3lame", "-b:a", "128k",
        output_mp3
    ], capture_output=True, text=True)

    # 如果 filter_complex 失败，尝试简单拼接
    if result.returncode != 0:
        print(f"Filter failed, using simple concat: {result.stderr[:200]}")
        result = subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_file,
            "-codec:a", "libmp3lame", "-b:a", "128k",
            output_mp3
        ], capture_output=True, text=True)

    os.remove(concat_file)
    if result.returncode == 0:
        print(f"Added intro/outro music to final output")
    else:
        print(f"Intro/outro merge failed: {result.stderr[:200]}")



def make_episode_id(article_date, link, title):
    """Generate unique episode_id from date + article slug (avoids same-day collisions)"""
    import re as _re
    date_str = article_date.strftime("%Y%m%d") if article_date else datetime.now().strftime("%Y%m%d")
    m = _re.search(r'/archives/([\w-]+)', link)
    if m:
        slug = m.group(1)
    else:
        slug = _re.sub(r'[^\w\u4e00-\-\uff00]+', '_', title)[:30]
    return f"{date_str}_{slug}"

def main():
    parser = argparse.ArgumentParser(description="生成 osp.io 播客")
    parser.add_argument("--title", help="文章标题")
    parser.add_argument("--link", help="文章链接")
    parser.add_argument("--auto", action="store_true", help="自动从 RSS 获取最新文章")
    parser.add_argument("--api-key", help="API Key（默认从 OPENAI_API_KEY 环境变量读取）")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1", help="API Base URL")
    parser.add_argument("--model", default="qwen/qwen-plus", help="模型名称")
    parser.add_argument("--output-dir", default="episodes", help="输出目录")
    args = parser.parse_args()

    # 获取文章
    title = ""
    content = ""
    link = ""
    article_date = None

    if args.auto:
        print("从 osp.io RSS 获取最新文章...")
        # 优先用 check_articles.py 输出的 NEW_ARTICLE_LINK 环境变量
        new_article_link = os.environ.get("NEW_ARTICLE_LINK", "")
        if new_article_link:
            print(f"Using NEW_ARTICLE_LINK: {new_article_link}")
            result = fetch_article_content("https://osp.io/feed", target_link=new_article_link)
            title, content, link, article_date = result
        else:
            print("NEW_ARTICLE_LINK not set, falling back to RSS entry[0]")
            result = fetch_article_content("https://osp.io/feed")
            title, content, link, article_date = result
        if not title:
            print("ERROR: 无法获取文章内容")
            sys.exit(1)
        print(f"文章: {title}")
    elif args.link:
        result = fetch_article_content("https://osp.io/feed", target_link=args.link)
        title, content, link, article_date = result
        if not title:
            print("ERROR: 无法获取文章内容")
            sys.exit(1)
        print(f"文章: {title}")
    else:
        print("ERROR: 需要 --auto 或 --link")
        sys.exit(1)

    # 生成脚本
    print("生成播客脚本...")
    transcripts, raw_script = generate_script(
        title, content,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model
    )
    if not transcripts:
        print("ERROR: 脚本生成失败")
        sys.exit(1)

    # episode_id 用日期+slug，避免同一天多篇文章互相覆盖
    episode_id = make_episode_id(article_date, link, title)
    print(f"Using episode_id: {episode_id}")

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    temp_files = []
    for i, item in enumerate(transcripts):
        speaker_id = item.get("speaker_id", 0)
        text = item.get("dialog", "").strip()
        if not text:
            continue
        voice = SPEAKER_VOICES.get(speaker_id, SPEAKER_VOICES[0])
        temp_file = os.path.join(output_dir, f"temp_{episode_id}_{i}.mp3")
        temp_files.append((speaker_id, voice, temp_file, text))

    print(f"生成 {len(temp_files)} 段音频...")

    # 并行生成
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(synthesize_audio, text, voice, temp_file): (speaker_id, text[:40])
            for speaker_id, voice, temp_file, text in temp_files
        }
        for future in concurrent.futures.as_completed(futures):
            speaker_id, snippet = futures[future]
            try:
                success = future.result()
                role = "女声" if speaker_id == 0 else "男声"
                print(f"  [{'✓' if success else '✗'}] {role}: {snippet}...")
            except Exception as e:
                print(f"  [✗] {e}")

    # 合并音频（裸音频，无模板）
    concat_file = os.path.join(output_dir, f"concat_{episode_id}.txt")
    with open(concat_file, "w") as f:
        for _, _, temp_file, _ in temp_files:
            if os.path.exists(temp_file):
                f.write(f"file '{os.path.abspath(temp_file)}'\n")

    content_mp3 = os.path.join(output_dir, f"content_{episode_id}.mp3")
    result = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file, "-codec:a", "libmp3lame", "-b:a", "128k", content_mp3
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"FFmpeg merge error: {result.stderr}")
        sys.exit(1)

    # 清理临时文件
    for _, _, temp_file, _ in temp_files:
        if os.path.exists(temp_file):
            os.remove(temp_file)
    os.remove(concat_file)

    # 加入片头片尾
    final_mp3 = os.path.join(output_dir, f"osp-podcast-{episode_id}.mp3")
    print("Adding intro/outro music...")
    add_intro_outro(content_mp3, final_mp3)

    # 清理中间文件
    if os.path.exists(content_mp3):
        os.remove(content_mp3)

    print(f"播客生成完成: {final_mp3}")
    print(f"文件大小: {os.path.getsize(final_mp3) / 1024:.1f} KB")
    print(f"Queue management delegated to update_queue.py step")

    # 保存元数据
    meta = {
        "id": episode_id,
        "title": title,
        "link": link,
        "date": article_date.isoformat() if article_date else datetime.now().isoformat(),
        "audio_file": os.path.basename(final_mp3),
        "file_size_kb": os.path.getsize(final_mp3) // 1024,
        "num_segments": len(temp_files),
        "has_intro_outro": has_intro_outro()
    }
    # episode_*.json - used by update_rss.py
    with open(os.path.join(output_dir, f"episode_{episode_id}.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    # osp-podcast-*.json - used by generate_index.py (alias, same content)
    with open(os.path.join(output_dir, f"osp-podcast-{episode_id}.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()