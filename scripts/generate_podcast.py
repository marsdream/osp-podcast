#!/usr/bin/env python3
"""
generate_podcast.py - 生成 osp.io 播客音频
从 osp.io RSS 获取文章，用 AI 生成播客对话脚本，Edge-TTS 合成音频，拼接片头片尾
"""
import os
import sys
import json
import re
import subprocess
import argparse
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
    <turn_pattern>strict_alternating</turn_pattern>
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

4. **Random Turn Pattern:** 两人自然交替，类似真实聊天节奏。

5. **Duration:** 约 3-5 分钟的对话量，内容要充实。
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

# 片头片尾音乐（相对于 repo 根目录）
TEMPLATE_DIR = "templates"
INTRO_FILE = "templates/intro.mp3"
OUTRO_FILE = "templates/outro.mp3"


def fetch_article_content(url):
    """通过 feedparser 获取文章内容"""
    feed = feedparser.parse(url)
    if feed.entries:
        entry = feed.entries[0]
        content = ""
        if hasattr(entry, "content") and entry.content:
            content = entry.content[0].value
        elif hasattr(entry, "summary"):
            content = entry.summary
        else:
            content = entry.get("description", "")
        return entry.title, content, entry.get("link", "")
    return None, None, ""


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


def concat_audio(input_files, output_file):
    """用 ffmpeg 拼接多个音频文件"""
    concat_file = output_file + ".txt"
    with open(concat_file, "w") as f:
        for path in input_files:
            if os.path.exists(path):
                f.write(f"file '{os.path.abspath(path)}'\n")

    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-codec:a", "libmp3lame", "-b:a", "192k",
        output_file
    ], capture_output=True, text=True)

    os.remove(concat_file)
    if result.returncode != 0:
        print(f"FFmpeg concat error: {result.stderr}")
        return False
    return True


def ensure_template(template_path, repo_dir):
    """如果模板文件不在本地，从 GitHub 下载"""
    if os.path.exists(template_path):
        return True
    name = os.path.basename(template_path)
    url = f"https://raw.githubusercontent.com/marsdream/osp-podcast/main/templates/{name}"
    print(f"  模板 {name} 不在本地，从 GitHub 下载...")
    result = subprocess.run(
        ["curl", "-sL", "-o", template_path, url],
        capture_output=True, text=True
    )
    return os.path.exists(template_path)


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

    # 确定 repo 根目录（脚本所在目录的父目录）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.dirname(script_dir)

    # 获取文章
    title = ""
    content = ""
    link = ""

    if args.auto:
        print("从 osp.io RSS 获取最新文章（自动去重）...")
        # 获取 feed.xml 里已有的 episode 标题
        try:
            existing_feed = feedparser.parse("https://podcast.herebuy.us/feed.xml")
            existing_titles = {e.title for e in existing_feed.entries}
            print(f"Feed 已有 {len(existing_titles)} 个 episode，去重中...")
        except Exception as e:
            existing_titles = set()
            print(f"(无法读取 feed.xml，跳过去重: {e})")

        # 遍历 osp.io RSS，找第一个未生成的 article
        osp_feed = feedparser.parse("https://osp.io/feed")
        title, content, link = None, None, ""
        for entry in osp_feed.entries[:10]:
            t = entry.title.strip()
            if t in existing_titles:
                print(f"  [跳过] {t} (已在 feed 中)")
                continue
            # 找到第一篇新的
            if hasattr(entry, "content") and entry.content:
                c = entry.content[0].value
            elif hasattr(entry, "summary"):
                c = entry.summary
            else:
                c = entry.get("description", "")
            title, content, link = t, c, entry.get("link", "")
            print(f"  [新文] {title} -> {link}")
            break

        if not title:
            print("没有新文章需要生成，退出。")
            sys.exit(0)
        print(f"文章: {title}")
    elif args.link:
        title, content, link = fetch_article_content(args.link)
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

    # 强制交替：如果LLM生成的不是严格交替，强行纠正
    forced = []
    for i, item in enumerate(transcripts):
        item = dict(item)
        item['speaker_id'] = i % 2  # 强制 0,1,0,1,...
        forced.append(item)
    transcripts = forced

    # 生成音频
    episode_id = datetime.now().strftime("%Y%m%d")
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

    # 检查片头片尾模板
    intro_path = os.path.join(repo_dir, INTRO_FILE)
    outro_path = os.path.join(repo_dir, OUTRO_FILE)
    ensure_template(intro_path, repo_dir)
    ensure_template(outro_path, repo_dir)

    # 拼接音频：intro + dialog + outro
    output_mp3 = os.path.join(output_dir, f"osp-podcast-{episode_id}.mp3")

    # 先合并对话
    concat_file = os.path.join(output_dir, f"concat_{episode_id}.txt")
    with open(concat_file, "w") as f:
        for _, _, temp_file, _ in temp_files:
            if os.path.exists(temp_file):
                f.write(f"file '{os.path.abspath(temp_file)}'\n")

    dialog_mp3 = os.path.join(output_dir, f"dialog_{episode_id}.mp3")
    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file, "-codec:a", "libmp3lame", "-b:a", "192k",
        dialog_mp3
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"FFmpeg dialog merge error: {result.stderr}")
        sys.exit(1)

    # 拼接片头 + 对话 + 片尾
    parts = []
    if os.path.exists(intro_path):
        parts.append(intro_path)
    parts.append(dialog_mp3)
    if os.path.exists(outro_path):
        parts.append(outro_path)

    concat_audio(parts, output_mp3)

    # 清理临时文件
    for _, _, temp_file, _ in temp_files:
        if os.path.exists(temp_file):
            os.remove(temp_file)
    os.remove(concat_file)
    if os.path.exists(dialog_mp3):
        os.remove(dialog_mp3)

    print(f"播客生成完成: {output_mp3}")
    print(f"文件大小: {os.path.getsize(output_mp3) / 1024:.1f} KB")

    # 保存元数据
    meta = {
        "id": episode_id,
        "title": title,
        "link": link,
        "date": datetime.now().isoformat(),
        "audio_file": os.path.basename(output_mp3),
        "file_size_kb": os.path.getsize(output_mp3) // 1024,
        "num_segments": len(temp_files)
    }
    with open(os.path.join(output_dir, f"episode_{episode_id}.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
