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
import unicodedata
from datetime import datetime
from email.utils import parsedate_to_datetime

try:
    import feedparser
except ImportError:
    print("ERROR: feedparser not installed. Run: pip install feedparser")
    sys.exit(1)

# =============================================================================
# 配置
# =============================================================================
SPEAKER_VOICES = {
    0: "zh-CN-XiaoxiaoNeural",   # 女声
    1: "zh-CN-YunyangNeural",   # 男声
}
INTRO_FILE = "templates/intro.mp3"
OUTRO_FILE = "templates/outro.mp3"
TTS_VOICE_CACHE = {}   # (text, voice) -> local_path


# =============================================================================
# 工具函数
# =============================================================================

def synthesize_audio(text, voice, output_path):
    """用 edge-tts 生成音频，返回是否成功"""
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


def concat_audio(parts, output_path):
    """用 FFmpeg concat 拼接多个音频文件"""
    concat_file = output_path + ".concat.txt"
    with open(concat_file, "w") as f:
        for p in parts:
            if os.path.exists(p):
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
        sys.exit(1)


# =============================================================================
# 文章内容获取
# =============================================================================

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


# =============================================================================
# LLM 生成对话脚本
# =============================================================================

def generate_script(title, content, api_key=None, base_url=None, model=None):
    """用 LLM 生成播客对话 JSON"""
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai not installed. Run: pip install openai")
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url=base_url)

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

请用以下JSON格式输出：
{{"podcast_transcripts": [{{"speaker_id": 0, "dialog": "梅梅内容"}}, {{"speaker_id": 1, "dialog": "开源君内容"}}]}}

文章标题：{title}
文章内容：{content[:3000]}

JSON输出："""

    try:
        resp = client.chat.completions.create(
            model=model or "qwen/qwen-plus",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2000,
        )
        raw = resp.choices[0].message.content
        # 去掉 markdown 代码块
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        data = json.loads(raw)
        transcripts = data.get("podcast_transcripts", [])
        return transcripts, raw
    except Exception as e:
        print(f"LLM error: {e}")
        return [], ""


# =============================================================================
# 单篇文章处理（供 auto 模式循环调用）
# =============================================================================

def process_article(title, content, link, args, pub_date=None):
    """处理单篇文章：生成脚本 → TTS → 拼接 → 保存元数据"""
    repo_dir = args.repo_dir
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    # 生成对话脚本
    print(f"  生成播客脚本...")
    transcripts, raw_script = generate_script(
        title, content,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model
    )
    if not transcripts:
        print(f"  ERROR: 脚本生成失败")
        return False

    # 强制交替
    forced = []
    for i, item in enumerate(transcripts):
        item = dict(item)
        item['speaker_id'] = i % 2
        forced.append(item)
    transcripts = forced

    # episode_id 用文章原始发布时间 + slug，避免同日期多篇互相覆盖
    slug = unicodedata.normalize('NFKC', title)[:30]
    slug = re.sub(r'[^\w\u4e00-\u9fff]', '_', slug)
    slug = re.sub(r'_+', '_', slug).strip('_')
    if pub_date:
        try:
            dt = parsedate_to_datetime(pub_date)
            date_str = dt.strftime('%Y%m%d')
        except Exception:
            date_str = datetime.now().strftime('%Y%m%d')
    else:
        date_str = datetime.now().strftime('%Y%m%d')
    episode_id = f"{date_str}_{slug}"

    # 生成 TTS 片段
    temp_files = []
    for i, item in enumerate(transcripts):
        text = item.get("dialog", "").strip()
        if not text:
            continue
        speaker_id = item.get("speaker_id", 0)
        voice = SPEAKER_VOICES.get(speaker_id, SPEAKER_VOICES[0])
        temp_file = os.path.join(output_dir, f"temp_{episode_id}_{i}.mp3")
        temp_files.append((speaker_id, voice, temp_file, text))

    print(f"  生成 {len(temp_files)} 段音频...")
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
                print(f"    [{'✓' if success else '✗'}] {role}: {snippet}...")
            except Exception as e:
                print(f"    [✗] {e}")

    # 片头片尾文件（通过 actions/checkout@v4 lfs:true 已拉到本地）
    intro_path = os.path.join(repo_dir, INTRO_FILE)
    outro_path = os.path.join(repo_dir, OUTRO_FILE)

    # 生成最终文件
    output_mp3 = os.path.join(output_dir, f"osp-podcast-{episode_id}.mp3")

    # 先合并对话
    concat_file = os.path.join(output_dir, f"concat_{episode_id}.txt")
    with open(concat_file, "w") as f:
        for _, _, temp_file, _ in temp_files:
            if os.path.exists(temp_file):
                f.write(f"file '{os.path.abspath(temp_file)}'\n")
    dialog_mp3 = os.path.join(output_dir, f"dialog_{episode_id}.mp3")
    r = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file, "-codec:a", "libmp3lame", "-b:a", "192k", dialog_mp3
    ], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  FFmpeg merge error: {r.stderr}")
        return False

    # 拼接片头+对话+片尾
    parts = [p for p in [intro_path, dialog_mp3, outro_path] if os.path.exists(p)]
    concat_audio(parts, output_mp3)

    # === 关键检查：音频文件必须真实存在且有内容 ===
    if not os.path.exists(output_mp3) or os.path.getsize(output_mp3) < 1000:
        print(f"  错误：音频文件生成失败或文件过小，删除残留并退出")
        if os.path.exists(output_mp3):
            os.remove(output_mp3)
        # 清理临时文件
        for _, _, temp_file, _ in temp_files:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        if os.path.exists(concat_file):
            os.remove(concat_file)
        if os.path.exists(dialog_mp3):
            os.remove(dialog_mp3)
        return False

    # 清理临时文件
    for _, _, temp_file, _ in temp_files:
        if os.path.exists(temp_file):
            os.remove(temp_file)
    os.remove(concat_file)
    if os.path.exists(dialog_mp3):
        os.remove(dialog_mp3)

    size_kb = os.path.getsize(output_mp3) / 1024
    print(f"  播客生成完成: {output_mp3} ({size_kb:.0f} KB)")

    # 统一转为 ISO 8601 格式（兼容 RSS pubDate 和字符串排序）
    if pub_date:
        try:
            dt = parsedate_to_datetime(pub_date)
            date_iso = dt.strftime('%Y-%m-%dT%H:%M:%S%z')
        except Exception:
            date_iso = pub_date
    else:
        date_iso = datetime.now().isoformat()

    # === 必须等音频文件确认生成成功后才写 metadata ===
    meta = {
        "id": episode_id,
        "title": title,
        "link": link,
        "date": date_iso,
        "audio_file": os.path.basename(output_mp3),
        "file_size_kb": int(size_kb),
        "num_segments": len(temp_files)
    }
    meta_path = os.path.join(output_dir, f"episode_{episode_id}.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"  元数据已保存: episode_{episode_id}.json")

    return True


# =============================================================================
# 主入口
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="生成 osp.io 播客")
    parser.add_argument("--auto", action="store_true", help="自动从 RSS 获取最新文章（处理所有待生成的新文章）")
    parser.add_argument("--link", help="文章链接（单独生成）")
    parser.add_argument("--title", help="文章标题")
    parser.add_argument("--content", help="文章内容（直接传入，省去抓取）")
    parser.add_argument("--api-key", help="API Key（默认从 OPENAI_API_KEY 环境变量读取）")
    parser.add_argument("--base-url", default="https://api.deepseek.com", help="API Base URL")
    parser.add_argument("--model", default="deepseek-chat", help="模型名称")
    parser.add_argument("--output-dir", default="episodes", help="输出目录")
    args = parser.parse_args()

    # 确定 repo 根目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.dirname(script_dir)
    args.repo_dir = repo_dir

    # API Key
    if not args.api_key:
        args.api_key = os.environ.get("OPENAI_API_KEY")
        if not args.api_key:
            print("ERROR: 需要设置 OPENAI_API_KEY 环境变量或 --api-key 参数")
            sys.exit(1)

    if args.auto:
        # ============================================================
        # AUTO 模式：循环处理所有待生成的新文章
        # ============================================================
        print("从 osp.io RSS 获取最新文章...")
        # 获取 feed.xml 里已有的 episode 信息（标题 → 是否有音频 enclosure）
        # 只跳过已有音频的条目；没有 enclosure 的条目会重新生成音频
        try:
            existing_feed = feedparser.parse("https://podcast.herebuy.us/feed.xml")
            existing_info = {}  # title -> has_audio
            for e in existing_feed.entries:
                title = e.title.strip()
                has_audio = False
                if hasattr(e, 'enclosures') and e.enclosures:
                    for enc in e.enclosures:
                        if enc.get('type', '').startswith('audio/'):
                            has_audio = True
                            break
                existing_info[title] = has_audio
            audio_count = sum(1 for v in existing_info.values() if v)
            print(f"Feed 已有 {len(existing_info)} 个 episode（{audio_count} 个有音频），将跳过有音频的条目")
        except Exception as e:
            existing_info = {}
            print(f"(无法读取 feed.xml，跳过去重: {e})")

        osp_feed = feedparser.parse("https://osp.io/feed")
        if not osp_feed.entries:
            print("osp.io RSS 为空，退出。")
            sys.exit(0)

        # 收集所有新文章（没有音频 enclosure 的才处理）
        # 按 osp.io 原始发布时间逆序（最新的在前），确保生成顺序和发布顺序一致
        new_articles = []
        for entry in osp_feed.entries[:20]:
            t = entry.title.strip()
            if existing_info.get(t, False):
                # 已有音频，跳过
                continue
            if hasattr(entry, "content") and entry.content:
                c = entry.content[0].value
            elif hasattr(entry, "summary"):
                c = entry.summary
            else:
                c = entry.get("description", "")
            # 用 osp.io 原始发布时间，用于 feed 排序
            pub_date = getattr(entry, "published", None) or getattr(entry, "updated", None) or None
            new_articles.append((t, c, entry.get("link", ""), pub_date))
        # osp.io RSS 已经是最新文章在前，new_articles 顺序就是发布顺序
        print(f"  [{len(new_articles)}] 篇，按 osp.io 发布顺序（最新→最老）")

        if not new_articles:
            print("没有新文章需要生成，退出。")
            sys.exit(0)

        print(f"发现 {len(new_articles)} 篇新文章，开始逐个生成...\n")
        success_count = 0
        fail_count = 0
        existing_titles = set()  # 跟踪已处理文章，防止同一篇被重复生成
        for i, (title, content, link, pub_date) in enumerate(new_articles, 1):
            print(f"=== [{i}/{len(new_articles)}] {title} (osp: {pub_date or '?'}) ===")
            ok = process_article(title, content, link, args, pub_date=pub_date)
            if ok:
                success_count += 1
                # 生成成功后，把这篇文章加入 existing_titles，防止同一篇被重复生成
                existing_titles.add(title)
            else:
                fail_count += 1
            print()

        print(f"=== 完成：成功 {success_count} 篇，失败 {fail_count} 篇 ===")
        if fail_count > 0:
            print("ERROR: 有文章生成失败，CI 将报告错误")
            sys.exit(1)

    elif args.link or args.title:
        # ============================================================
        # 单篇模式（--link 或 --title+--content）
        # ============================================================
        title, content, link = "", "", ""
        if args.link:
            title, content, link = fetch_article_content(args.link)
        if not content and args.content:
            content = args.content
        if not title and args.title:
            title = args.title
        if not content:
            print("ERROR: 需要 --content 参数提供文章内容")
            sys.exit(1)
        if not title:
            print("ERROR: 需要 --title 或 --link 提供文章标题")
            sys.exit(1)
        print(f"文章: {title}")
        ok = process_article(title, content, link, args)
        sys.exit(0 if ok else 1)

    else:
        print("ERROR: 需要 --auto（自动处理所有新文章）或 --link（单独生成一篇）")
        sys.exit(1)


if __name__ == "__main__":
    main()
