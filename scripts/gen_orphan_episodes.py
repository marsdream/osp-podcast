#!/usr/bin/env python3
"""
gen_orphan_episodes.py - 为孤儿 episode 生成播客音频
使用 Ollama (qwen3:32b) 生成对话脚本 + edge-tts 合成音频
"""
import os
import sys
import json
import re
import subprocess
import unicodedata
import asyncio
from datetime import datetime

# ==============================
# 配置
# ==============================
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EPISODES_DIR = os.path.join(REPO_DIR, "episodes")
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3:32b"

SPEAKER_VOICES = {
    0: "zh-CN-XiaoxiaoNeural",   # 女声 - 梅梅
    1: "zh-CN-YunyangNeural",   # 男声 - 开源君
}

# 5 篇孤儿文章
ARTICLES = [
    {
        "id": "10030",
        "slug": "10030",
        "url": "https://osp.io/archives/10030",
        "title": "Anthropic 向 GitHub 发出版权删除请求",
        "pub_date": "2026-04-12",
    },
    {
        "id": "9986",
        "slug": "9986",
        "url": "https://osp.io/archives/9986",
        "title": "N.O.M.A.D",
        "pub_date": "2026-04-12",
    },
    {
        "id": "9994",
        "slug": "9994",
        "url": "https://osp.io/archives/9994",
        "title": "ClawFeed：我再也不想刷 RSS 了",
        "pub_date": "2026-04-11",
    },
    {
        "id": "9926",
        "slug": "9926",
        "url": "https://osp.io/archives/9926",
        "title": "不用写代码也能做AI应用",
        "pub_date": "2026-04-04",
    },
    {
        "id": "9873",
        "slug": "9873",
        "url": "https://osp.io/archives/9873",
        "title": "在本地跑大模型：Ollama",
        "pub_date": "2026-03-23",
    },
]

# ==============================
# 工具函数
# ==============================

def fetch_article_content(url):
    """从 osp.io HTML 页面提取正文"""
    import requests
    from html.parser import HTMLParser

    class TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.skip = False
            self.skip_tags = {'script', 'style', 'nav', 'header', 'footer', 'aside'}
            self.texts = []
            self.paragraphs = []
            self.in_body = False
            self.current_tag = ''

        def handle_starttag(self, tag, attrs):
            self.current_tag = tag
            if tag in self.skip_tags:
                self.skip = True
            if tag == 'article':
                self.in_body = True

        def handle_endtag(self, tag):
            if tag in self.skip_tags:
                self.skip = False
            if tag == 'article':
                self.in_body = False
            if tag == 'p' and self.paragraphs:
                text = ' '.join(self.paragraphs).strip()
                if text:
                    self.texts.append(text)
                self.paragraphs = []
            self.current_tag = ''

        def handle_data(self, data):
            if not self.skip:
                stripped = data.strip()
                if stripped:
                    if self.current_tag == 'p':
                        self.paragraphs.append(stripped)
                    else:
                        self.texts.append(stripped)

    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    r = requests.get(url, headers=headers, timeout=15)
    parser = TextExtractor()
    parser.feed(r.text)

    # 提取正文，跳过头部/标题/作者/相关文章
    article_text = []
    skip_phrases = ['Related Posts', '关于作者', '发表回复', '取消回复',
                    '您的邮箱地址', '必填项已用', 'No Comments', '开源派\n']
    for line in parser.texts:
        if any(phrase in line for phrase in skip_phrases):
            break
        if len(line) > 20:  # 跳过短文本（标题、日期等）
            article_text.append(line)

    return ' '.join(article_text)


def generate_script_via_ollama(title, content):
    """用 Ollama (qwen3:32b) 生成播客对话 JSON"""
    import requests

    prompt = f"""你是一个播客编辑，根据以下文章内容，生成一段两人对话播客脚本。

角色设定：
- speaker_id=0 是梅梅，开源派作者，语气轻松活泼，爱用语气词（哇、嗯呢、你们知道吗），多提问，多感叹，自称"梅梅"
- speaker_id=1 是开源君，开源派博主，语气沉稳专业但接地气，能用生活化比喻讲技术，自称"开源君"

要求：
- 两人交替发言，共8-15段对话
- 女声（梅梅）先开始，每段不超过80字，语气活泼自然
- 内容要有观点碰撞，不是简单总结
- 不要加任何描述性文字（如"[笑声]"、"（音乐）"）
- 最后一段由梅梅引导关注/订阅

请用以下JSON格式输出（只输出JSON，不要其他内容）：
{{"podcast_transcripts": [{{"speaker_id": 0, "dialog": "梅梅内容"}}, {{"speaker_id": 1, "dialog": "开源君内容"}}]}}

文章标题：{title}
文章内容：{content[:3000]}

JSON输出："""

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 2000}
            },
            timeout=120
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("message", {}).get("content", "")

        # 去掉 markdown 代码块
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        raw = raw.strip()

        # 尝试从原始输出中提取 JSON
        json_match = re.search(r'\{.*"podcast_transcripts".*\}', raw, re.DOTALL)
        if json_match:
            raw = json_match.group()

        parsed = json.loads(raw)
        transcripts = parsed.get("podcast_transcripts", [])
        return transcripts, raw
    except Exception as e:
        print(f"  [Ollama error] {e}")
        return [], ""


def synthesize_audio(text, voice, output_path):
    """用 edge-tts 生成音频"""
    try:
        import edge_tts
        sub = edge_tts.Communicate(text, voice)
        asyncio_run(sub.save(output_path))
        return True
    except Exception as e:
        print(f"  [edge_tts error] {e}")
        return False


def asyncio_run(coro):
    """在同步函数里运行 asyncio coroutine"""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        fut = concurrent.futures.Future()
        loop.create_task(_await_coro(fut, coro))
        return fut.result()
    return asyncio.run(coro)


async def _await_coro(fut, coro):
    try:
        result = await coro
        fut.set_result(result)
    except Exception as e:
        fut.set_exception(e)


def make_slug(title, max_len=30):
    """生成文件名 slug"""
    slug = unicodedata.normalize('NFKC', title)[:max_len]
    slug = re.sub(r'[^\w\u4e00-\u9fff]', '_', slug)
    slug = re.sub(r'_+', '_', slug).strip('_')
    return slug


def concat_audio(parts, output_path):
    """用 FFmpeg concat 拼接多个音频文件"""
    concat_file = output_path + ".concat.txt"
    with open(concat_file, "w") as f:
        for p in parts:
            if os.path.exists(p) and os.path.getsize(p) > 1000:
                f.write(f"file '{os.path.abspath(p)}'\n")

    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-codec:a", "libmp3lame", "-b:a", "192k",
        output_path
    ], capture_output=True, text=True)
    os.remove(concat_file)
    if result.returncode != 0:
        print(f"FFmpeg concat error: {result.stderr}")
        return False
    return True


def process_article(article):
    """处理单篇文章：生成脚本 → TTS → 拼接 → 保存"""
    slug = article["slug"]
    title = article["title"]
    url = article["url"]
    pub_date = article["pub_date"]

    print(f"\n{'='*60}")
    print(f"处理: {title} ({url})")

    # 1. 抓取文章内容
    print(f"  抓取文章内容...")
    content = fetch_article_content(url)
    if not content or len(content) < 100:
        print(f"  错误：文章内容过短或抓取失败")
        return None
    print(f"  内容长度: {len(content)} 字")

    # 2. 生成对话脚本
    print(f"  生成播客脚本 (Ollama {OLLAMA_MODEL})...")
    transcripts, raw = generate_script_via_ollama(title, content)
    if not transcripts:
        print(f"  错误：脚本生成失败")
        return None
    print(f"  生成 {len(transcripts)} 段对话")

    # 3. 生成 TTS 音频
    temp_files = []
    for i, item in enumerate(transcripts):
        text = item.get("dialog", "").strip()
        if not text:
            continue
        speaker_id = item.get("speaker_id", i % 2)
        voice = SPEAKER_VOICES.get(speaker_id, SPEAKER_VOICES[0])
        temp_file = os.path.join(EPISODES_DIR, f"temp_{slug}_{i}.mp3")
        temp_files.append((speaker_id, voice, temp_file, text))

    print(f"  生成 {len(temp_files)} 段音频...")
    for i, (speaker_id, voice, temp_file, text) in enumerate(temp_files):
        ok = synthesize_audio(text, voice, temp_file)
        role = "女声" if speaker_id == 0 else "男声"
        print(f"    [{'✓' if ok else '✗'}] {role}: {text[:30]}...")

    # 4. 合并对话
    concat_file = os.path.join(EPISODES_DIR, f"concat_{slug}.txt")
    with open(concat_file, "w") as f:
        for _, _, temp_file, _ in temp_files:
            if os.path.exists(temp_file) and os.path.getsize(temp_file) > 1000:
                f.write(f"file '{os.path.abspath(temp_file)}'\n")

    dialog_mp3 = os.path.join(EPISODES_DIR, f"dialog_{slug}.mp3")
    r = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file, "-codec:a", "libmp3lame", "-b:a", "192k", dialog_mp3
    ], capture_output=True, text=True)
    os.remove(concat_file)

    if r.returncode != 0:
        print(f"  FFmpeg merge error: {r.stderr}")
        return None

    # 5. 生成最终文件名
    date_str = pub_date.replace("-", "")  # e.g. 20260412
    title_slug = make_slug(title, 25)
    output_mp3 = os.path.join(EPISODES_DIR, f"osp-podcast-{date_str}_{title_slug}.mp3")

    # 6. 直接用 dialog_mp3 作为输出（无需片头片尾）
    import shutil
    shutil.copy2(dialog_mp3, output_mp3)

    # 7. 验证文件
    if not os.path.exists(output_mp3) or os.path.getsize(output_mp3) < 1000:
        print(f"  错误：音频文件生成失败")
        if os.path.exists(output_mp3):
            os.remove(output_mp3)
        return None

    size_kb = os.path.getsize(output_mp3) / 1024
    print(f"  生成完成: {os.path.basename(output_mp3)} ({size_kb:.0f} KB)")

    # 8. 清理临时文件
    for _, _, temp_file, _ in temp_files:
        if os.path.exists(temp_file):
            os.remove(temp_file)
    if os.path.exists(dialog_mp3):
        os.remove(dialog_mp3)

    return {
        "title": title,
        "url": url,
        "pub_date": pub_date,
        "mp3_file": os.path.basename(output_mp3),
        "file_size": os.path.getsize(output_mp3),
        "file_size_kb": int(size_kb),
    }


def main():
    os.makedirs(EPISODES_DIR, exist_ok=True)

    results = []
    for i, article in enumerate(ARTICLES, 1):
        print(f"\n[{i}/{len(ARTICLES)}] 处理: {article['title']}")
        result = process_article(article)
        if result:
            results.append(result)

    print(f"\n{'='*60}")
    print(f"完成！成功生成 {len(results)}/{len(ARTICLES)} 篇")
    for r in results:
        print(f"  - {r['title']}")
        print(f"    文件: {r['mp3_file']} ({r['file_size_kb']} KB)")
        print(f"    URL:  https://podcast.herebuy.us/episodes/{r['mp3_file']}")
        print(f"    大小: {r['file_size']} bytes")

    # 保存结果供后续使用
    result_file = os.path.join(EPISODES_DIR, "orphan_episodes_result.json")
    with open(result_file, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {result_file}")


if __name__ == "__main__":
    main()
