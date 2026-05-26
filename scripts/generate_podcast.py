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
   * Speaker 0 (女声): 引导对话，热情活泼，像朋友聊天，风格轻松
   * Speaker 1 (男声): 技术深度，用通俗语言解释，有深度但不装

2. **Natural Dialogue:** 使用真实口语，像两个人在咖啡馆聊天。不要"首先、其次、最后"。用"咱们、其实、你知道吗、对对对"。

3. **No Self-Reference by Name:** 对话中禁止 Speaker 自己提及自己的名字。梅梅不能说出"梅梅"二字，开源君不能说出"开源君"二字。名字只能由对方提起（打招呼、问观点等场景）。例如："开源君，你怎么看"是正确的（梅梅提起对方名字）；"梅梅，你觉得呢"也是正确的（开源君提起对方名字）。但梅梅自己的 dialog 里不能出现"梅梅"，开源君自己的 dialog 里不能出现"开源君"。

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

# 模板路径（GitHub Actions 会把仓库 checkout 下来）
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
INTRO_FILE = os.path.join(TEMPLATE_DIR, "intro.mp3")
OUTRO_FILE = os.path.join(TEMPLATE_DIR, "outro.mp3")


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
    abs_input = os.path.abspath(input_mp3)
    abs_intro = os.path.abspath(intro)
    abs_outro = os.path.abspath(outro)

    # 第一段：intro + content
    concat1_file = output_mp3 + ".concat1.txt"
    with open(concat1_file, "w") as f:
        f.write(f"file '{abs_intro}'\n")
        f.write(f"file '{abs_input}'\n")

    mid_mp3 = output_mp3 + ".mid.mp3"
    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat1_file,
        "-codec:a", "libmp3lame", "-b:a", "128k",
        mid_mp3
    ], capture_output=True, text=True)
    os.remove(concat1_file)

    if result.returncode != 0:
        print(f"Intro+content merge failed: {result.stderr[:200]}")
        shutil.copy2(input_mp3, output_mp3)
        return

    # 第二段：(intro+content) + outro
    concat2_file = output_mp3 + ".concat2.txt"
    with open(concat2_file, "w") as f:
        f.write(f"file '{os.path.abspath(mid_mp3)}'\n")
        f.write(f"file '{abs_outro}'\n")

    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat2_file,
        "-filter_complex", "[1]afade=t=out:st=0:d=1[out];[0][out]concat=n=2:v=0:a=1[out]",
        "-map", "[out]",
        "-codec:a", "libmp3lame", "-b:a", "128k",
        output_mp3
    ], capture_output=True, text=True)
    os.remove(concat2_file)
    os.remove(mid_mp3)

    if result.returncode == 0:
        print(f"Added intro/outro music to final output")
    else:
        print(f"Outtro merge with fade failed, using simple concat: {result.stderr[:200]}")
        # 简单拼接，不做淡出
        concat_final = output_mp3 + ".concat_final.txt"
        with open(concat_final, "w") as f:
            f.write(f"file '{os.path.abspath(mid_mp3)}'\n")
            f.write(f"file '{abs_outro}'\n")
        result = subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_final,
            "-codec:a", "libmp3lame", "-b:a", "128k",
            output_mp3
        ], capture_output=True, text=True)
        os.remove(concat_final)
        if result.returncode == 0:
            print(f"Added outro (simple concat)")
        else:
            print(f"Outtro merge failed: {result.stderr[:200]}")
    if result.returncode == 0:
        print(f"Added intro/outro music to final output")
    else:
        print(f"Intro/outro merge failed: {result.stderr[:200]}")


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

    if args.auto:
        print("从 osp.io RSS 获取最新文章...")
        title, content, link = fetch_article_content("https://osp.io/feed")
        if not title:
            print("ERROR: 无法获取文章内容")
            sys.exit(1)
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

    # 保存元数据
    meta = {
        "id": episode_id,
        "title": title,
        "link": link,
        "date": datetime.now().isoformat(),
        "audio_file": os.path.basename(final_mp3),
        "file_size_kb": os.path.getsize(final_mp3) // 1024,
        "num_segments": len(temp_files),
        "has_intro_outro": has_intro_outro()
    }
    with open(os.path.join(output_dir, f"episode_{episode_id}.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
