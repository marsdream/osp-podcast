#!/usr/bin/env python3
"""
generate_podcast.py - 生成 osp.io 播客音频
从 osp.io RSS 获取文章，用 AI 生成播客对话脚本，Edge-TTS 合成音频
"""
import os
import sys
import json
import re
import time
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


# LLM 候选链：第一个失败（限流/超时/5xx）就自动换下一个。
# 起因：2026-10-26 sensenova 的 deepseek-v4-flash 触发 TPM/RPM 限流
# (429 'inference exceeds tpm/rpm limit')，整个 CI job 挂在第一篇文章上。
# 同一 key 同一 base_url 下 glm-5.2 / sensenova-6.8-flash-lite 均可用。
# LLM 候选链：每个候选是 (model, base_url, api_key, label) 四元组，
# 支持跨供应商切换。起因：2026-11-04 排查发现 SenseNova 单日额度池会耗尽
# （deepseek-v4-flash 返回 insufficient_quota，glm-5.2 / 6.8-flash 返回
# code 8 RPM/TPM 限流），而 OmniRoute 背后的 Agnes 是完全独立的额度池，
# 能兜住 SenseNova 全挂的场景。
#
# 顺序经过实测验证（2026-11-04）：
#   sensenova/glm-5.2              200
#   sensenova/sensenova-6.8-flash-lite 200
#   omni agnes/agnes-2.5-flash     200（真实播客 prompt 解析出 21 段对话）
#   sensenova/deepseek-v4-flash     429 insufficient_quota（额度池真空）
# 因此 deepseek-v4-flash 放在最后，不做首选。
LLM_FALLBACK_MODELS = [
    "glm-5.2",                    # SenseNova 首选，实测 200
    "sensenova-6.8-flash-lite",   # SenseNova 备用，额度池较大
]

# OmniRoute 兜底候选。设置了 OMNI_API_KEY / OMNI_BASE_URL 才启用。
# agnes/agnes-2.5-flash：独立供应商，不受 SenseNova 额度池影响，
# 真实播客 prompt 实测 200 / 23s / JSON 可解析。
OMNI_FALLBACK_MODELS = [
    "agnes/agnes-2.5-flash",
]

# 退避基数（秒）。SenseNova 的 RPM/TPM 滑窗实测需要 40-70 秒才恢复，
# 3 秒的间隔必然让所有候选在同一窗口内全部 429。
FALLBACK_BACKOFF_SECONDS = 25

# max_tokens 上限。3000 会撞上限被截断（usage.completion_tokens==3000），
# 导致 JSON 不完整、解析失败、白烧一次额度。2000 足够写完 3-5 分钟对话。
LLM_MAX_TOKENS = 2000


def _is_retryable(exc):
    """判断异常是否值得换模型重试（限流/超时/服务端错误）。

    有 status_code 时以状态码为准：只有 429 和 5xx 才值得重试。
    403（套餐无权）/ 404（模型不存在）重试多少次都没用，必须换模型。
    原实现把 APIStatusError 按类名一律当可重试，会在 403 上空转。
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    name = type(exc).__name__
    return name in ("RateLimitError", "APITimeoutError", "APIConnectionError",
                    "InternalServerError")


def _is_quota_exhausted(exc):
    """区分「额度池耗尽」和「瞬时限流」。

    2026-11-04 实测：insufficient_quota 表示该模型当日额度池已空，
    退避再试也没用，必须换模型；而 code 8 (tpm/rpm limit) 是滑动窗口，
    等一会儿就能恢复。两者混为一谈会导致在死模型上空转。
    """
    msg = str(exc).lower()
    return "insufficient_quota" in msg or "quota" in msg


def _build_candidates(primary, url, key, fallback_models, omni_models=None):
    """构造 (model, base_url, api_key, label) 候选列表。

    同一供应商的模型共用 base_url/key；OmniRoute 候选使用独立 endpoint 和 key。
    """
    candidates = []
    seen = set()

    def add(model, base, api_key, label):
        if not model:
            return
        marker = (model, base)
        if marker in seen:
            return
        seen.add(marker)
        candidates.append((model, base, api_key, label))

    # 1) 主模型
    add(primary, url, key, "primary")

    # 2) 同供应商 fallback
    for m in (fallback_models if fallback_models is not None else LLM_FALLBACK_MODELS):
        add(m, url, key, "fallback")

    # 3) OmniRoute 兜底（跨供应商，额度池独立）
    omni_key = os.environ.get("OMNI_API_KEY")
    omni_url = os.environ.get("OMNI_BASE_URL", "https://omni.herebuy.us/v1")
    if omni_key:
        for m in (omni_models if omni_models is not None else OMNI_FALLBACK_MODELS):
            add(m, omni_url, omni_key, "omniroute")

    return candidates


def generate_script(title, content, api_key=None, base_url=None, model=None,
                    fallback_models=None):
    """调用 OpenAI 兼容 API 生成播客脚本（JSON 格式）

    带跨供应商模型级 fallback：主模型限流/超时/5xx 时自动切下一个候选，
    候选可以来自不同 base_url 和不同 key。
    """
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
    primary = model or os.environ.get("LLM_MODEL", "qwen/qwen-plus")

    candidates = _build_candidates(primary, url, key, fallback_models)
    if len(candidates) == 1 and not os.environ.get("OMNI_API_KEY"):
        print("WARNING: 候选链只有主模型一个，没有可用的 fallback")

    # Podcast-Generator 风格的 XML prompt
    prompt = PODCAST_PROMPT_TEMPLATE.replace("{{content}}", content[:4000])

    response = None
    last_exc = None
    clients = {}
    for idx, (model_name, cand_url, cand_key, kind) in enumerate(candidates):
        client = clients.get(cand_url)
        if client is None:
            client = openai.OpenAI(api_key=cand_key, base_url=cand_url, timeout=180.0)
            clients[cand_url] = client
        try:
            print(f"Using LLM: {model_name} via {cand_url}"
                  + (f" ({kind} #{idx})" if idx else ""))
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "你是一个专业的中文播客编剧。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=LLM_MAX_TOKENS,
                temperature=0.7
            )
            break
        except Exception as e:
            last_exc = e
            if idx == len(candidates) - 1:
                print(f"LLM 调用失败 ({model_name}): {type(e).__name__}: {e}")
                print("所有候选均已失败")
                raise
            if not _is_retryable(e):
                # 401/403/404：端点或模型本身不可用。
                # 跨端点链里这不代表整体失败 —— SenseNova 的 key 挂了，
                # OmniRoute 的 key 照样能用。所以立即换下一个候选，不做长退避。
                print(f"LLM 调用失败 ({model_name}): {type(e).__name__}: {e}")
                print("  不可重试的错误，立即换下一个候选")
                continue
            if _is_quota_exhausted(e):
                # 额度池耗尽：等再久也没用，立即换供应商。
                print(f"  {type(e).__name__}: {e} — 额度池耗尽，立即换供应商")
                continue
            print(f"  {type(e).__name__}: {e} — 等待 {FALLBACK_BACKOFF_SECONDS}s 换下一个候选")
            time.sleep(FALLBACK_BACKOFF_SECONDS)

    if response is None:
        raise last_exc

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

RESULT_FILE = "episode_result.json"


def write_result(success, link, title=None, episode_id=None, error=None):
    """写本轮处理结果，供 update_queue.py 决定是否出队。

    只有 success=True 且带 episode_id 时才允许出队；
    失败（429/超时/脚本生成失败）时文章留在队列里等下轮重试。
    """
    payload = {
        "success": bool(success),
        "link": link,
        "title": title,
        "episode_id": episode_id,
        "error": error,
        "finished_at": datetime.now().isoformat(),
    }
    # 附带已发布清单，供 update_queue.py 清理队列里的僵尸条目
    published = []
    try:
        for fn in os.listdir("episodes"):
            if fn.endswith(".json") and fn.startswith("episode_"):
                try:
                    with open(os.path.join("episodes", fn)) as f:
                        meta = json.load(f)
                    if meta.get("link"):
                        published.append(meta["link"])
                except (json.JSONDecodeError, OSError):
                    continue
    except OSError:
        pass
    payload["published_links"] = published
    with open(RESULT_FILE, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Result written: success={success} episode_id={episode_id}")


def main():
    parser = argparse.ArgumentParser(description="生成 osp.io 播客")
    parser.add_argument("--title", help="文章标题")
    parser.add_argument("--link", help="文章链接")
    parser.add_argument("--auto", action="store_true", help="自动从 RSS 获取最新文章")
    parser.add_argument("--api-key", help="API Key（默认从 OPENAI_API_KEY 环境变量读取）")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1", help="API Base URL")
    parser.add_argument("--model", default="glm-5.2", help="模型名称")
    parser.add_argument("--output-dir", default="episodes", help="输出目录")
    args = parser.parse_args()
    STATE_FILE = "last_article.json"

    # 读取文章链接：优先级 --link > NEW_ARTICLE_LINK > last_article.json 队列
    target_link = None
    if args.link:
        target_link = args.link
    elif os.environ.get("NEW_ARTICLE_LINK"):
        target_link = os.environ["NEW_ARTICLE_LINK"]
    else:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                queue = json.load(f)
            if isinstance(queue, list) and queue:
                # 只读取队首，不再在此处 pop。
                # 原逻辑在这里 pop 一次、update_queue.py 又 pop 一次，
                # 同一篇文章被出队两次 = 每处理一篇就丢一篇（72 → 71 → 70）。
                # 出队统一交给 update_queue.py：只在 episode_result.json
                # 确认本集成功后才移除。
                target_link = queue[0]["link"]
                print(f"Queue: processing first of {len(queue)}, {len(queue) - 1} remaining")
            elif isinstance(queue, dict):
                target_link = queue["link"]

    if not target_link:
        print("ERROR: no article link (need --link or NEW_ARTICLE_LINK or queue in last_article.json)")
        sys.exit(1)

    title, article_content, link, article_date = fetch_article_content("https://osp.io/feed", target_link=target_link)
    if not title:
        print("ERROR: 无法获取文章内容")
        write_result(success=False, link=target_link, error="无法获取文章内容")
        sys.exit(0)
    print(f"文章: {title}")


    # 生成脚本
    print("生成播客脚本...")
    try:
        transcripts, raw_script = generate_script(
            title, article_content,
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model
        )
    except Exception as e:
        # LLM 全链路失败（限流/超时/5xx）不应让整个 CI job 失败。
        # 关键：文章必须留在队列里等下轮重试，不能被丢弃。
        print(f"ERROR: 脚本生成异常，跳过此文章: {type(e).__name__}: {e}")
        write_result(success=False, link=target_link, title=title,
                     error=f"{type(e).__name__}: {e}")
        sys.exit(0)
    if not transcripts:
        print("ERROR: 脚本生成失败，跳过此文章")
        # 单篇失败：文章留在队列里，写失败标记，下轮 CI 重试
        write_result(success=False, link=target_link, title=title,
                     error="脚本生成失败（无有效 transcript）")
        sys.exit(0)  # 不算 CI 失败，只是跳过

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
    final_mp3 = os.path.join(output_dir, f"episode_{episode_id}.mp3")
    print("Adding intro/outro music...")
    add_intro_outro(content_mp3, final_mp3)

    # 清理中间文件
    if os.path.exists(content_mp3):
        os.remove(content_mp3)

    print(f"播客生成完成: {final_mp3}")
    final_size = os.path.getsize(final_mp3)
    print(f"文件大小: {final_size / 1024:.1f} KB")
    print(f"Queue management delegated to update_queue.py step")

    # 音频有效性检查：TTS 全部失败时 ffmpeg 仍可能产出极小/空文件。
    # 这种情况不能算成功，否则出队后这集就永久丢失了。
    if final_size < 50000:
        print(f"ERROR: 生成的音频过小 ({final_size} bytes)，判定为失败，文章保留在队列中")
        write_result(success=False, link=link, title=title,
                     error=f"生成的音频过小 ({final_size} bytes)")
        sys.exit(0)
    with open(final_mp3, "rb") as fh:
        head = fh.read(4)
    if head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        pass
    else:
        print(f"ERROR: 生成的文件不是有效 MP3 (head={head!r})，文章保留在队列中")
        write_result(success=False, link=link, title=title,
                     error=f"生成的文件不是有效 MP3 (head={head!r})")
        sys.exit(0)

    # 保存元数据
    meta = {
        "id": episode_id,
        "title": title,
        "link": link,
        "date": article_date.isoformat() if article_date else datetime.now().isoformat(),
        "audio_file": os.path.basename(final_mp3),
        "file_size_kb": os.path.getsize(final_mp3) // 1024,
        "num_segments": len(temp_files),
        "has_intro_outro": has_intro_outro(),
        "script": raw_script[:1000] if raw_script else ""
    }
    with open(os.path.join(output_dir, f"episode_{episode_id}.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 成功标记：只有这里写 success=True，update_queue.py 才会出队
    write_result(success=True, link=link, title=title, episode_id=episode_id)


if __name__ == "__main__":
    main()