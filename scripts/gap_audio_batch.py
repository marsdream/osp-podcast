#!/usr/bin/env python3
"""
gap_audio_batch.py - 批量为 osp.io 缺失文章生成播客音频
使用 Qwen3 TTS (localhost:5001) + OpenRouter (Qwen-plus)
"""
import os, sys, json, re, time, subprocess, shutil, urllib.request, urllib.parse
from datetime import datetime

# ─── 配置 ────────────────────────────────────────────────────
OSP_PODCAST_DIR = "/Users/marsdream/Dev/osp-podcast"
EPISODES_DIR = os.path.join(OSP_PODCAST_DIR, "episodes")
TEMPLATE_DIR = os.path.join(OSP_PODCAST_DIR, "templates")
INTRO_MUSIC = os.path.join(TEMPLATE_DIR, "intro.mp3")
OUTRO_MUSIC = os.path.join(TEMPLATE_DIR, "outro.mp3")
OUTPUT_DIR = "/tmp/podcast-gap"
VENV = os.path.expanduser("~/Dev/tools/qwen3-tts-apple-silicon-main/.venv")

OPENROUTER_KEY = open("/Users/marsdream/.openclaw/credentials/openrouter_key").read().strip()
Qwen3_SERVER = "http://localhost:5001"

MAX_CHARS = 2800  # 每次发送给 TTS 的最大字数

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def check_server():
    try:
        req = urllib.request.Request(f"{Qwen3_SERVER}/health", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except:
        return False

def get_article_content(post_id):
    """通过 WordPress REST API 获取文章内容"""
    api_url = f"https://osp.io/wp-json/wp/v2/posts/{post_id}?_fields=id,title,content,date,link"
    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        content = data.get("content", {}).get("rendered", "")
        text = re.sub(r'<[^>]+>', '', content)
        text = re.sub(r'\s+', ' ', text).strip()
        return {
            "title": data["title"]["rendered"],
            "content": text,
            "date": data["date"],
            "link": data["link"],
            "id": post_id
        }
    except Exception as e:
        log(f"  ⚠️ 获取文章 {post_id} 失败: {e}")
        return None

def generate_dialog(article_content):
    """用 Qwen-plus 生成对话脚本"""
    osp_section = """【背景说明 — 梅梅在开场白和自然对话中自然带入，不要在正文里直接念角色名字】

- 开源派介绍（第一次提及时自然带入）：开源派 osp.io 是我的个人技术博客，从2006年开始写，坚持了近20年，专注开源技术分享
- 订阅引导（结尾处自然说）：订阅开源派，官网 osp.io，追更不迷路
- 互动引导（自然插入）：有问题想问我，欢迎在评论区留言，我会尽量回复
- 马大师介绍（梅梅提及博主时直接用，无角色名前缀）：技术老兵，哥德堡大学硕士，曾在联想、猎聘等公司做ERP产品经理，户外运动爱好者，热爱滑雪、潜水、攀岩
"""

    prompt = f"""你是一个播客编剧，帮我把以下文章改编成两人对话播客脚本。

要求：
- 格式：JSON数组，每行一个 speaker_id + dialog
- speaker_id=0 是梅梅，开源派的作者，语气轻松活泼，爱用语气词（哇、哇哦、嗯呢、那今天、你们知道吗），多提问，多感叹，自称"梅梅"
- speaker_id=1 是马大师，开源派博主，语气沉稳专业但接地气，能用生活化比喻讲技术，自称"马大师"
- 两人对话要像真实聊天：有反问、有接话、有补充，不要每句都太完整太正式
- 纯对话，dialog 里绝对不要有角色名前缀（如"梅梅："、"马大师："），只需要对话内容本身，角色由 speaker_id 区分
- 播客名称是《开源有点甜》，是开源派 osp.io 官方播客
- 总时长约3-5分钟，10-16轮对话
- 开场：梅梅欢迎听众，介绍本期主题（用osp_section里的介绍）
- 结尾：梅梅说订阅引导（用osp_section里的订阅话术）
- 马大师介绍：梅梅提到马大师时，直接用背景描述（如"技术老兵，哥德堡大学硕士…"），不要加"马大师是"的台词前缀

{osp_section}

文章内容：
{article_content}

输出格式（只输出JSON，不要其他内容）：
{{"podcast_transcripts": [{{"speaker_id": 0, "dialog": "对话内容"}}]}}"""

    try:
        import openai
    except ImportError:
        log("⚠️ openai 未安装，尝试安装...")
        subprocess.run([sys.executable, "-m", "pip", "install", "openai", "-q"])
        import openai

    client = openai.OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")
    resp = client.chat.completions.create(
        model="qwen/qwen-plus",
        messages=[
            {"role": "system", "content": "你是一个播客编剧。"},
            {"role": "user", "content": prompt}
        ],
        max_tokens=2000,
        temperature=0.7
    )
    raw = resp.choices[0].message.content
    raw = re.sub(r'^```json\s*', '', raw.strip())
    raw = re.sub(r'^```\s*', '', raw).strip()

    try:
        data = json.loads(raw)
        transcripts = data.get("podcast_transcripts", [])

        # 去重
        deduped = []
        for item in transcripts:
            text = (item.get("dialog") or "").strip()
            if not text:
                continue
            text = re.sub(r'^(梅梅|马大师|开源君|开源派)[：:]\s*', '', text)
            prev_text = deduped[-1]["dialog"].strip().rstrip('。！？.,!?') if deduped else ""
            curr_clean = text.rstrip('。！？.,!?')
            if curr_clean != prev_text:
                deduped.append({"speaker_id": item["speaker_id"], "dialog": text})

        log(f"  对话生成完成，共 {len(deduped)} 轮")
        return deduped
    except Exception as e:
        log(f"  ⚠️ 对话解析失败: {e}, raw[:200]={raw[:200]}")
        return None

def generate_tts(text, voice_code, output_path):
    """调用 Qwen3 TTS 生成音频"""
    url = f"{Qwen3_SERVER}/api/tts?text={urllib.parse.quote(text)}&voiceCode={voice_code}&model=1"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            data = r.read()
            with open(output_path, "wb") as f:
                f.write(data)
        return len(data) > 1000  # success if non-trivial size
    except Exception as e:
        log(f"  ⚠️ TTS 失败: {e}")
        return False

def concat_audio(seg_dir, concat_list_path, output_path):
    """拼接音频片段"""
    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_list_path,
        "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1",
        output_path
    ], capture_output=True, text=True)
    return result.returncode == 0

def add_intro_outro(content_wav, final_mp3):
    """添加片头片尾"""
    abs_content = os.path.abspath(content_wav)
    concat_file = final_mp3 + ".concat.txt"

    if os.path.exists(INTRO_MUSIC) and os.path.exists(OUTRO_MUSIC):
        with open(concat_file, "w") as f:
            f.write(f"file '{os.path.abspath(INTRO_MUSIC)}'\n")
            f.write(f"file '{abs_content}'\n")
            f.write(f"file '{os.path.abspath(OUTRO_MUSIC)}'\n")

        result = subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_file,
            "-acodec", "libmp3lame", "-b:a", "192k",
            final_mp3
        ], capture_output=True, text=True)
        os.remove(concat_file)
        return result.returncode == 0
    else:
        # 无片头片尾，直接转换
        result = subprocess.run([
            "ffmpeg", "-y", "-i", content_wav,
            "-acodec", "libmp3lame", "-b:a", "192k",
            final_mp3
        ], capture_output=True, text=True)
        return result.returncode == 0

def process_article(article_info):
    """处理单篇文章，返回 (success, audio_file_path, error_msg)"""
    post_id = article_info["id"]
    link = article_info["link"]
    log(f"📄 处理文章 ID={post_id}")

    # 1. 获取文章内容
    article = get_article_content(post_id)
    if not article:
        return False, None, "failed_to_fetch_article"

    title = article["title"]
    content = article["content"]
    article_date = article["date"]
    log(f"  标题: {title[:50]}")
    if len(content) < 50:
        return False, None, "article_too_short"

    # 2. 生成对话
    log(f"  生成对话脚本...")
    transcripts = generate_dialog(content[:MAX_CHARS])
    if not transcripts:
        return False, None, "dialog_generation_failed"

    # 3. 生成音频片段
    log(f"  生成 {len(transcripts)} 段音频...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(f"{OUTPUT_DIR}/segs/{post_id}", exist_ok=True)

    seg_dir = f"{OUTPUT_DIR}/segs/{post_id}"
    concat_list_path = f"{seg_dir}/concat.txt"

    with open(concat_list_path, "w") as cf:
        for i, item in enumerate(transcripts):
            sid = item["speaker_id"]
            text = item["dialog"].strip()
            if not text:
                continue

            voice = "Serena" if sid == 0 else "Dylan"
            prefix = "f" if sid == 0 else "m"
            out_file = f"{seg_dir}/{prefix}_{i:03d}.wav"
            tmp_file = f"{seg_dir}/tmp_{prefix}_{i:03d}.wav"

            ok = generate_tts(text, voice, tmp_file)
            if ok and os.path.exists(tmp_file):
                # 转换格式
                r = subprocess.run([
                    "ffmpeg", "-y", "-i", tmp_file,
                    "-ar", "44100", "-ac", "1", "-acodec", "pcm_s16le",
                    out_file
                ], capture_output=True)
                if r.returncode == 0 and os.path.exists(out_file):
                    cf.write(f"file '{os.path.abspath(out_file)}'\n")

    # 4. 拼接
    merged_path = f"{OUTPUT_DIR}/segs/{post_id}/merged.wav"
    ok = concat_audio(seg_dir, concat_list_path, merged_path)
    if not ok:
        return False, None, "concat_failed"

    # 5. 添加片头片尾，导出 MP3
    episode_id = str(post_id)
    audio_filename = f"osp-podcast-{episode_id}.mp3"
    final_mp3 = os.path.join(EPISODES_DIR, audio_filename)

    ok = add_intro_outro(merged_path, final_mp3)
    if not ok:
        return False, None, "intro_outro_failed"

    # 6. 保存 episode JSON
    ep_meta = {
        "id": episode_id,
        "title": title,
        "link": link,
        "date": article_date,
        "audio_file": audio_filename,
        "file_size_kb": os.path.getsize(final_mp3) // 1024,
        "num_segments": len(transcripts),
        "has_intro_outro": os.path.exists(INTRO_MUSIC) and os.path.exists(OUTRO_MUSIC)
    }
    meta_path = os.path.join(EPISODES_DIR, f"episode_{episode_id}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(ep_meta, f, ensure_ascii=False, indent=2)

    log(f"  ✅ 完成: {audio_filename} ({ep_meta['file_size_kb']} KB)")
    return True, final_mp3, None

def main():
    # 从命令行参数获取 gap 文章列表 JSON
    if len(sys.argv) > 1:
        gap_articles = json.loads(sys.argv[1])
    else:
        log("用法: python3 gap_audio_batch.py '[{\"id\":10263,...},...]'")
        sys.exit(1)

    log(f"开始处理 {len(gap_articles)} 篇缺失文章...")

    if not check_server():
        log("❌ Qwen3 TTS 服务器未运行 (localhost:5001)")
        sys.exit(1)

    results = {"success": [], "failed": []}
    for i, article in enumerate(gap_articles):
        log(f"\n[{i+1}/{len(gap_articles)}] 处理文章...")
        ok, path, err = process_article(article)
        if ok:
            results["success"].append({"id": article["id"], "path": path})
        else:
            results["failed"].append({"id": article["id"], "err": err})

        # 每次间隔 2 秒，避免 Qwen3 server 过载
        if i < len(gap_articles) - 1:
            time.sleep(2)

    log(f"\n{'='*50}")
    log(f"完成: {len(results['success'])} 成功, {len(results['failed'])} 失败")
    if results["failed"]:
        for f in results["failed"]:
            log(f"  ❌ article_id={f['id']} err={f['err']}")

    # 保存结果
    with open(f"{OUTPUT_DIR}/results.json", "w", encoding="utf-8") as rf:
        json.dump(results, rf, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()