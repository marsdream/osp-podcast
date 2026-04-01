#!/usr/bin/env python3
"""
generate_podcast.py - 生成播客音频
从 osp.io RSS 获取文章，生成播客对话脚本，用 Edge-TTS 合成音频

依赖:
  pip install feedparser requests edge-tts openai

用法:
  python generate_podcast.py [--title "标题"] [--link "链接"]

环境变量:
  OPENAI_API_KEY   - OpenAI / OpenRouter API Key（必填）
  LLM_BASE_URL     - API base URL，默认 https://openrouter.ai/api/v1
  LLM_MODEL        - 模型，默认 deepseek/deepseek-chat-v3-0324:free
"""
import os
import sys
import json
import subprocess
import argparse
from datetime import datetime

# 尝试导入，缺失时给出友好提示
try:
    import feedparser
except ImportError:
    print("ERROR: feedparser not installed. Run: pip install feedparser")
    sys.exit(1)

PODCAST_SCRIPT_TEMPLATE = """你是一个播客编剧。请根据以下文章内容，撰写一段中文播客对话脚本。

要求：
- 角色：主播（女声）、技术专家（男声）交替对话
- 时长：约3-5分钟
- 风格：轻松自然，像两个人聊天，不要播音腔
- 开头：欢迎收听开源派技术播客
- 结尾：感谢收听，下期再见
- 不要出现"首先、其次、最后"这类僵硬结构
- 不要自称主播，可以用"咱们、我觉得、其实"

文章内容：
{content}

播客脚本：
"""

EDGE_TTS_VOICES = {
    "host": "zh-CN-XiaoxiaoNeural",   # 女声-晓晓
    "expert": "zh-CN-YunyangNeural",   # 男声-云扬
}


def fetch_article_content(url):
    """通过 feedparser 获取文章内容"""
    feed = feedparser.parse(url)
    if feed.entries:
        entry = feed.entries[0]
        # 尝试获取完整内容
        content = ""
        if hasattr(entry, "content") and entry.content:
            content = entry.content[0].value
        elif hasattr(entry, "summary"):
            content = entry.summary
        else:
            content = entry.get("description", "")
        return entry.title, content
    return None, None


def generate_script(title, content, api_key=None, base_url=None, model=None):
    """调用 OpenAI 兼容 API（OpenRouter/Gemini/本地Ollama）生成播客脚本"""
    try:
        import openai
    except ImportError:
        print("ERROR: openai not installed. Run: pip install openai")
        return None

    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        print("ERROR: OPENAI_API_KEY not set")
        return None

    url = base_url or os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    model_name = model or os.environ.get("LLM_MODEL", "deepseek/deepseek-chat-v3-0324:free")

    print(f"Using LLM: {model_name} via {url}")

    client = openai.OpenAI(api_key=key, base_url=url)

    prompt = PODCAST_SCRIPT_TEMPLATE.format(content=content[:3000])

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "你是一个专业的中文播客编剧。"},
            {"role": "user", "content": prompt}
        ],
        max_tokens=2000,
        temperature=0.7
    )
    return response.choices[0].message.content


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


def parse_script_to_segments(script):
    """把脚本解析成[（角色, 文本)]列表"""
    segments = []
    import re
    # 简单分割：按行处理，识别角色
    lines = script.split("\n")
    current_role = None
    current_text = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 识别角色
        if "主播" in line or "女声" in line or ":" in line:
            if current_role and current_text:
                segments.append((current_role, "".join(current_text)))
                current_text = []
            if ":" in line:
                parts = line.split(":", 1)
                role_part = parts[0].strip()
                text_part = parts[1].strip()
                role = "host" if any(r in role_part for r in ["主播", "女声", "晓晓"]) else "expert"
                current_role = role
                current_text = [text_part]
            else:
                current_role = "host"
                current_text = [line]
        elif current_role:
            current_text.append(line)
        else:
            # 开头段落
            current_role = "host"
            current_text.append(line)

    if current_role and current_text:
        segments.append((current_role, "".join(current_text)))

    return segments


def main():
    parser = argparse.ArgumentParser(description="生成 osp.io 播客")
    parser.add_argument("--title", help="文章标题")
    parser.add_argument("--link", help="文章链接")
    parser.add_argument("--auto", action="store_true", help="自动从 RSS 获取最新文章")
    parser.add_argument("--api-key", help="API Key（默认从 OPENAI_API_KEY 环境变量读取）")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1", help="API Base URL")
    parser.add_argument("--model", default="deepseek/deepseek-chat-v3-0324:free", help="模型名称")
    parser.add_argument("--output-dir", default="episodes", help="输出目录")
    args = parser.parse_args()

    # 获取文章
    title = args.title
    content = ""

    if args.auto:
        # 自动从 RSS 获取最新文章
        print("从 osp.io RSS 获取最新文章...")
        title, content = fetch_article_content("https://osp.io/feed")
        if not title:
            print("ERROR: 无法获取文章内容")
            sys.exit(1)
        print(f"文章: {title}")
    elif args.link:
        title, content = fetch_article_content(args.link)
        if not title:
            print("ERROR: 无法获取文章内容")
            sys.exit(1)
        print(f"文章: {title}")

    if not content:
        print("ERROR: 缺少文章内容")
        sys.exit(1)

    # 生成脚本
    print("生成播客脚本...")
    script = generate_script(
        title, content,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model
    )
    if not script:
        print("ERROR: 脚本生成失败")
        sys.exit(1)

    print("脚本生成完成:")
    print(script[:200] + "...")

    # 解析并生成音频
    segments = parse_script_to_segments(script)
    print(f"生成 {len(segments)} 段音频...")

    episode_id = datetime.now().strftime("%Y%m%d")
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    temp_files = []
    for i, (role, text) in enumerate(segments):
        voice = EDGE_TTS_VOICES.get(role, EDGE_TTS_VOICES["host"])
        temp_file = os.path.join(output_dir, f"temp_{episode_id}_{i}.mp3")
        temp_files.append((role, voice, temp_file, text))

    # 并行生成（edge-tts 可以多进程）
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(synthesize_audio, text, voice, temp_file): (role, text[:50])
            for role, voice, temp_file, text in temp_files
        }
        for future in concurrent.futures.as_completed(futures):
            role, snippet = futures[future]
            try:
                success = future.result()
                print(f"  [{'✓' if success else '✗'}] {role}: {snippet}...")
            except Exception as e:
                print(f"  [✗] {role}: {e}")

    # 合并音频
    concat_file = os.path.join(output_dir, f"concat_{episode_id}.txt")
    with open(concat_file, "w") as f:
        for _, _, temp_file, _ in temp_files:
            if os.path.exists(temp_file):
                f.write(f"file '{os.path.abspath(temp_file)}'\n")

    output_mp3 = os.path.join(output_dir, f"osp-podcast-{episode_id}.mp3")
    result = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file, "-codec:a", "libmp3lame", "-b:a", "128k", output_mp3
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"FFmpeg merge error: {result.stderr}")
        sys.exit(1)

    # 清理临时文件
    for _, _, temp_file, _ in temp_files:
        if os.path.exists(temp_file):
            os.remove(temp_file)
    os.remove(concat_file)

    print(f"播客生成完成: {output_mp3}")
    print(f"文件大小: {os.path.getsize(output_mp3) / 1024:.1f} KB")

    # 保存元数据
    meta = {
        "id": episode_id,
        "title": title or args.title,
        "date": datetime.now().isoformat(),
        "audio_file": os.path.basename(output_mp3),
        "script": script[:500]
    }
    with open(os.path.join(output_dir, f"episode_{episode_id}.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
