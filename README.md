# why-skills

面向 Codex 和 Claude Code 的技能市场。两个客户端共用同一份技能源码，可按需安装和更新插件。

| 插件 | 版本 | 用途 |
| --- | --- | --- |
| `image-generator` | `0.1.0` | 使用 Gemini、OpenAI GPT Image 或通义千问生成、编辑和合成图片。 |

## 在 Codex 安装

```bash
codex plugin marketplace add https://github.com/COSWINNER/why-skills.git --ref main
codex plugin add image-generator@why-skills
```

从本地安装时，在本仓库根目录运行 `codex plugin marketplace add .`，再执行相同的插件安装命令。

**更新 GitHub 市场和插件**

```bash
codex plugin marketplace upgrade why-skills
codex plugin add image-generator@why-skills
```

本地市场更新时，先在市场目录运行 `git pull --ff-only`，再重新执行插件安装命令。更新后开启新会话以重新加载技能。

**卸载**

```bash
codex plugin remove image-generator@why-skills
codex plugin marketplace remove why-skills
```

## 在 Claude Code 安装

```bash
claude plugin marketplace add https://github.com/COSWINNER/why-skills.git --scope user
claude plugin install image-generator@why-skills --scope user
```

从本地安装时，在本仓库根目录运行 `claude plugin marketplace add "$(pwd)" --scope user`，再执行相同的插件安装命令。

**更新市场和插件**

```bash
claude plugin marketplace update why-skills
claude plugin update image-generator@why-skills --scope user
```

本地市场更新时，先在市场目录运行 `git pull --ff-only`，再执行上述更新命令。更新后重启 Claude Code 以重新加载技能。

**卸载**

```bash
claude plugin uninstall image-generator@why-skills --scope user
claude plugin marketplace remove why-skills
```

## 配置并调用图片生成

使用 Python 3.11 或更新版本，安装 Pillow、python-dotenv 和所选服务商的 SDK。在启动客户端的环境中设置 `IMAGE_PROVIDER` 和对应的 API Key，也可在已安装技能目录中将 `.env.example` 复制为 `.env` 后填写。SDK 安装命令和配置变量见[图片生成技能说明](plugins/image-generator/skills/image-generator/README_CN.md)。

配置后在 Codex 中选择 `image-generator`，或在 Claude Code 中调用 `/image-generator:image-generator` 并提供提示词。需要编辑或合成时，可同时提供参考图片。

## 维护市场

1. 把技能放在 `plugins/<名称>/skills/<名称>/`，在 `SKILL.md` 的 YAML 中填写 `name` 和 `description`，将依赖的脚本及资源放在同一技能目录内。
2. 在插件目录添加 `.codex-plugin/plugin.json` 和 `.claude-plugin/plugin.json`，保持两端的名称、描述和版本一致。新插件从 `0.1.0` 开始。
3. 将插件登记到 `.agents/plugins/marketplace.json` 和 `.claude-plugin/marketplace.json`。Codex 使用 `{"source":"local","path":"./plugins/<名称>"}` 作为 `source`，Claude Code 使用 `"./plugins/<名称>"`。
4. 更新技能时同步提升两个插件描述文件的版本，更新市场中的插件描述及上方技能表。发布前运行目录校验、对应技能测试和客户端安装检查。

```bash
python3 scripts/validate.py
claude plugin validate --strict .
claude plugin validate --strict plugins/image-generator

# 安装三个服务商 SDK 后运行。测试使用本地模拟接口。
python3 -m unittest discover -s plugins/image-generator/skills/image-generator/tests -v
```
