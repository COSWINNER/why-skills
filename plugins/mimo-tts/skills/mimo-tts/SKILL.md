---
name: mimo-tts
description: 使用小米 MiMo 把文本合成为 WAV 或 MP3。用于朗读、播报、角色配音、唱歌、用文字设计音色、用参考录音复刻音色，以及通过自然语言或音频标签控制演绎风格。
---

# MiMo 语音合成

根据用户要的音色来源选择模式。脚本按子命令读取该模式的模型配置。

| 模式 | 何时使用 | 音色和指导 |
| --- | --- | --- |
| `preset` | 常规朗读、预置音色、唱歌 | `--voice` 可选，默认 `mimo_default`。唱歌时在歌词最开头加 `(唱歌)`。 |
| `design` | 根据文字描述创造音色 | `--instruction` 必填，写清音色特征和演绎要求。 |
| `clone` | 使用参考录音复刻音色 | `--reference-audio` 必填，传入获得授权的本地 WAV 或 MP3，Base64 编码后限 10 MB。 |

1. 确定要读的正文。保留用户给定的措辞，只按需求添加风格或音频标签。用户只给了角色描述但未提供台词时，按请求拟稿或请用户提供原稿。
2. 有语气、语速、情绪、方言、重音或拟声要求时，查阅[风格控制指南](references/style-control.md)。把演绎指导放在 `--instruction`，把篇首风格和句中音频标签放在 `--text` 或 `--text-file` 的正文里。`design` 将音色描述和指导合写在 `--instruction`。
3. 从用户工作目录运行脚本，按本文件所在目录解析 `scripts/synthesize_speech.py`。相对参考路径和输出路径以工作目录为准。成功时把脚本输出的音频路径交给用户。失败时报告脚本的错误；遇到缺少配置或样本时请用户补充对应信息。

```bash
python "/path/to/installed/mimo-tts/scripts/synthesize_speech.py" preset \
  --voice 茉莉 --instruction '轻快但清晰，重读「提前」' \
  --text '（轻快）好消息，今天的活动提前开始。' --output 'activity.mp3'

python "/path/to/installed/mimo-tts/scripts/synthesize_speech.py" design \
  --instruction '中年男性声线，低沉温厚，普通话，吐字清晰。像夜间电台主持人一样慢速、留出短停顿。' \
  --text-file ./script.txt

python "/path/to/installed/mimo-tts/scripts/synthesize_speech.py" clone \
  --reference-audio './reference voice.wav' --instruction '语速平稳，末尾轻轻收声' \
  --text '今晚，我们从一封旧信说起。' --format wav
```

运行需要 Python 3.11+ 和 `python-dotenv`。将 [`.env.example`](.env.example) 复制为本文件同级的 `.env`，填写 `MIMO_API_KEY`，按需设置 `MIMO_BASE_URL` 和三个模型。也可通过进程环境配置，技能目录下的 `.env` 优先。仅在用户指定模型时使用单次覆盖 `--model`。

有 `--output` 时按扩展名选择 WAV 或 MP3，`--format` 同时出现时须与扩展名一致。省略 `--output` 时在工作目录的 `generation-audio/` 生成唯一文件，默认 WAV。已有文件需改用新的输出路径。
