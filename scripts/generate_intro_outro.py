#!/usr/bin/env python3
"""
generate_intro_outro.py - 用 ACE-Step 生成播客片头片尾音乐
淡入淡出效果，输出到 templates/intro.mp3 和 templates/outro.mp3
"""
import os
import sys
import json
import subprocess
import urllib.request
import urllib.parse

# =============================================================================
# 配置
# =============================================================================
ACE_API_KEY = os.environ.get("ACE_MUSIC_API_KEY", "")
ACE_BASE_URL = "https://api.acemusic.ai"
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
INTRO_FILE = os.path.join(TEMPLATES_DIR, "intro.mp3")
OUTRO_FILE = os.path.join(TEMPLATES_DIR, "outro.mp3")

# 播客片头片尾音乐 prompt（技术播客风格，器乐为主）
# v2: 8秒版，DeepSeek建议+马大师2026-04-04确认
INTRO_PROMPT = "A short, modern tech podcast intro jingle, bright electronic ambient, confident and energetic, perfect for 6-8 second logo sound, no vocals, instrumental only"
OUTRO_PROMPT = "A short, warm tech podcast outro jingle, smooth electronic ambient, gentle fade, professional closing feel, no vocals, instrumental only"


def generate_music(prompt, duration=8, output_path=None):
    """调用 ACE-Step API 生成音乐（curl 方式，避免 urllib 403 问题）"""
    if not ACE_API_KEY:
        print("ERROR: ACE_MUSIC_API_KEY not set")
        return None

    messages_content = f"<prompt>{prompt}</prompt>"
    payload = {
        "messages": [{"role": "user", "content": messages_content}],
        "audio_config": {
            "duration": duration,
            "vocal_language": "en",
            "instrumental": True,
            "format": "mp3"
        },
        "sample_mode": False,
        "stream": False
    }

    import tempfile
    payload_file = os.path.join(tempfile.gettempdir(), "ace_payload.json")
    with open(payload_file, "w") as f:
        json.dump(payload, f)

    print(f"  生成音乐: {prompt[:60]}...")
    try:
        result = subprocess.run([
            "curl", "-s", "-X", "POST",
            f"{ACE_BASE_URL}/v1/chat/completions",
            "-H", f"Authorization: Bearer {ACE_API_KEY}",
            "-H", "Content-Type: application/json",
            "-d", f"@{payload_file}"
        ], capture_output=True, text=True, timeout=120)
        result_text = result.stdout.strip()
        if not result_text:
            print(f"  curl 返回为空: {result.stderr[:200]}")
            return None
        resp_data = json.loads(result_text)
    except Exception as e:
        print(f"  API 请求失败: {e}")
        return None

    try:
        audios = resp_data["choices"][0]["message"].get("audio", [])
        if not audios:
            print(f"  ERROR: 没有返回音频: {resp_data}")
            return None
        audio_url = audios[0]["audio_url"]["url"]
        # data:audio/mpeg;base64,xxxx
        b64 = audio_url.split(",", 1)[1]
        import base64
        mp3_data = base64.b64decode(b64)
        if output_path:
            with open(output_path, "wb") as f:
                f.write(mp3_data)
            print(f"  已保存: {output_path}")
        return mp3_data
    except Exception as e:
        print(f"  解析音频失败: {e}")
        print(f"  原始响应前200字: {str(resp_data)[:200]}")
        return None


def add_fade(path, fade_in=0.5, fade_out=1.5):
    """用 FFmpeg 给 MP3 添加淡入淡出"""
    temp_path = path + ".tmp.mp3"
    # -af volume=0.8 稍微降低整体音量，fade效果更自然
    cmd = [
        "ffmpeg", "-y",
        "-i", path,
        "-af", f"afade=t=in:ss=0:d={fade_in},afade=t=out:st={get_duration(path)-fade_out}:d={fade_out},volume=0.85",
        "-codec:a", "libmp3lame",
        "-q:a", "2",
        temp_path
    ]
    print(f"  添加淡入淡出 (in={fade_in}s, out={fade_out_actual:.1f}s)...")
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print(f"  FFmpeg 警告: {r.stderr.decode()[:200]}")
    os.replace(temp_path, path)


def get_duration(path):
    """获取 MP3 时长（秒）"""
    r = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except:
        return 10.0


def main():
    os.makedirs(TEMPLATES_DIR, exist_ok=True)

    print("🎵 生成播客片头片尾音乐（ACE-Step）")
    print("=" * 50)

    # 生成片头
    intro_data = generate_music(INTRO_PROMPT, duration=8, output_path=INTRO_FILE)
    if intro_data:
        add_fade(INTRO_FILE, fade_in=0.3, fade_out=1.5)
        dur = get_duration(INTRO_FILE)
        print(f"  片头完成，时长: {dur:.1f}s")
    else:
        # 回退到静音文件
        print("  回退：创建静音片头")
        create_silent(INTRO_FILE, duration=3)

    # 生成片尾
    outro_data = generate_music(OUTRO_PROMPT, duration=8, output_path=OUTRO_FILE)
    if outro_data:
        add_fade(OUTRO_FILE, fade_in=0.3, fade_out=2.0)
        dur = get_duration(OUTRO_FILE)
        print(f"  片尾完成，时长: {dur:.1f}s")
    else:
        print("  回退：创建静音片尾")
        create_silent(OUTRO_FILE, duration=3)

    print("\n✅ 片头片尾生成完毕！")
    print(f"   片头: {INTRO_FILE}")
    print(f"   片尾: {OUTRO_FILE}")


def create_silent(path, duration=3):
    """创建静音 MP3 作为回退"""
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(duration), "-q:a", "9",
        "-acodec", "libmp3lame", path
    ], capture_output=True)
    print(f"  已创建静音文件: {path}")


if __name__ == "__main__":
    main()
