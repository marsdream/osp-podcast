# osp-podcast

开源派（osp.io）技术播客自动生成仓库

## 概述

每周自动抓取 osp.io 最新文章，生成中文播客 MP3，并发布到各大平台。

## 技术架构

- **播客生成**: [Podcast-Generator](https://github.com/justlovemaki/Podcast-Generator)
- **TTS 引擎**: Edge-TTS（中文）+ Qwen3 0.6B（英文）
- **RSS 源**: https://osp.io/feed
- **发布平台**: Anchor.fm + GitHub Pages

## 目录结构

```
├── episodes/          # 播客音频文件
├── scripts/           # 自动化脚本
│   ├── check_articles.py   # 检查新文章
│   ├── generate_podcast.py  # 生成播客
│   └── update_rss.py        # 更新 RSS
├── feed.xml          # RSS Feed
└── .github/workflows/     # GitHub Actions
```

## License

MIT
