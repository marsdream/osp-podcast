#!/usr/bin/env python3
"""手动生成「AI Agent如何改变软件开发」这集"""
import asyncio, subprocess, requests, json, re, os
from datetime import datetime
import edge_tts

API_KEY = open('/Users/marsdream/.openclaw/credentials/openrouter_key').read().strip()

# 抓文章
r = requests.get('https://osp.io/wp-json/wp/v2/posts/9924', timeout=10)
d = r.json()
title = d['title']['rendered'].strip()
content = re.sub(r'<[^>]+>', '', d['content']['rendered']).strip()
link = d['link']
print('文章:', title)

import openai
client = openai.OpenAI(api_key=API_KEY, base_url='https://openrouter.ai/api/v1')
prompt = f'''* **Output Format:** No explanatory text！Make sure the language of the output content is Chinese

<podcast_generation_system>
You are a master podcast scriptwriter, adept at transforming diverse input content into a lively, engaging, and natural-sounding conversation between multiple distinct podcast hosts.

<input>
  <podcast_settings>
    <num_speakers>2</num_speakers>
    <turn_pattern>strict_alternating</turn_pattern>
  </podcast_settings>
  <source_content>
{content[:4000]}
  </source_content>
</input>

<guidelines>
1. **Distinct Host Personas:**
   * Speaker 0 (主播/女声): 引导对话，热情活泼
   * Speaker 1 (专家/男声): 技术深度，用通俗语言解释

2. **Natural Dialogue:** 使用真实口语，不要"首先、其次、最后"。用"咱们、其实、你知道吗、对对对"。

3. **Pure Dialog Only:** dialog 字段里只放对话内容，不要任何角色前缀。

4.两人自然交替，约 3-5 分钟对话量。
</guidelines>

<output_format>
Output a JSON object with a podcasts field. Each item: speaker_id (0 or 1), dialog (Chinese text). 10-20 segments.
</output_format>'''

print('生成对话...')
resp = client.chat.completions.create(model='qwen/qwen-plus',
    messages=[{'role':'user','content':prompt}], temperature=0.7)
raw = re.sub(r'^\s*```json\s*', '', resp.choices[0].message.content.strip())
raw = re.sub(r'\s*```\s*$', '', raw)
data = json.loads(raw)
segments = data.get('podcasts', data.get('podcast_transcripts', []))
for i, seg in enumerate(segments):
    seg['speaker_id'] = i % 2
print(f'对话 {len(segments)} 段')

OUTPUT_DIR = 'episodes'
os.makedirs(OUTPUT_DIR, exist_ok=True)
EPISODE_ID = "397b-20260403"

async def tts_one(i, sid, text):
    voice = 'zh-CN-XiaoxiaoNeural' if sid == 0 else 'zh-CN-YunxiNeural'
    tmp = os.path.join(OUTPUT_DIR, f'temp_{EPISODE_ID}_{i}.mp3')
    await edge_tts.Communicate(text, voice).save(tmp)
    return (sid, tmp, text[:40])

async def main():
    tasks = [tts_one(i, s.get('speaker_id', 0) % 2, s.get('dialog', '').strip())
             for i, s in enumerate(segments) if s.get('dialog', '').strip()]
    return await asyncio.gather(*tasks)

print('合成音频...')
results = asyncio.run(main())
ok = [(r[0], r[1], r[2]) for r in results]
print(f'音频 {len(ok)}/{len(segments)} 段')

# 拼接对话
concat = os.path.join(OUTPUT_DIR, f'concat_{EPISODE_ID}.txt')
with open(concat, 'w') as f:
    for _, tmp, _ in ok:
        if os.path.exists(tmp):
            f.write(f"file '{os.path.abspath(tmp)}'\n")
dialog = os.path.join(OUTPUT_DIR, f'dialog_{EPISODE_ID}.mp3')
r = subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat,
    '-codec:a', 'libmp3lame', '-b:a', '192k', dialog], capture_output=True, text=True)
print('dialog merge:', r.returncode, r.stderr[-300:] if r.stderr else 'ok')

# 片头+对话+片尾
output = os.path.join(OUTPUT_DIR, f'osp-podcast-{EPISODE_ID}.mp3')
intro = 'templates/intro.mp3'
outro = 'templates/outro.mp3'
parts = [p for p in [intro, dialog, outro] if os.path.exists(p)]
concat2 = os.path.join(OUTPUT_DIR, 'concat2.txt')
with open(concat2, 'w') as f:
    for p in parts:
        f.write(f"file '{os.path.abspath(p)}'\n")
r = subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat2,
    '-codec:a', 'libmp3lame', '-b:a', '192k', output], capture_output=True, text=True)
print('final merge:', r.returncode, r.stderr[-300:] if r.stderr else 'ok')

# 清理
for _, tmp, _ in ok:
    if os.path.exists(tmp):
        os.remove(tmp)
for f in [concat, dialog, concat2]:
    if os.path.exists(f):
        os.remove(f)

size = os.path.getsize(output) // 1024
print(f'完成: {output} ({size}KB)')

# 元数据
meta = {"id": EPISODE_ID, "title": title, "link": link,
    "date": datetime.now().isoformat(), "audio_file": os.path.basename(output),
    "file_size_kb": size, "num_segments": len(ok)}
with open(os.path.join(OUTPUT_DIR, f'episode_{EPISODE_ID}.json'), 'w') as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print('元数据已存')
