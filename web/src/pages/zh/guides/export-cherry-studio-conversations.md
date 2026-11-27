---
layout: "../../../layouts/Guide.astro"
locale: "zh"
slug: "export-cherry-studio-conversations"
category: "export"
order: 6
updated: "2026-11-27"
title: "将 Cherry Studio 2.x 聊天与 Agent 会话导出为 Markdown"
description: "从本地 cherrystudio.sqlite 只读导出 Cherry Studio 2.x 普通聊天（topic-*）与 Agent 会话（session-*）为 Markdown 或 JSON，支持多安装目录。"
faq:
  - question: "Cherry Studio 2.x 的本地数据库保存在哪里？"
    answer: "默认位于 Data/cherrystudio.sqlite：macOS 在 ~/Library/Application Support/CherryStudio，Windows 在 %APPDATA%\\CherryStudio，Linux 在 ~/.config/CherryStudio，同时也会读取 ~/.cherrystudio/boot-config.json 配置的目录。"
  - question: "支持直接读取 Cherry Studio 1.x 的 IndexedDB 数据吗？"
    answer: "不支持。Agent Dump 读取 Cherry Studio 2.x 的 SQLite 数据库（包含已迁移到 2.x 的历史记录）；不支持直接读取 1.x 的 IndexedDB/Redux 数据，也不支持 --format raw。"
  - question: "多模型并行回复或分支对话怎么处理？"
    answer: "普通聊天（cherry://topic-<id>）仅导出当前激活的根到叶路径，排除其他分支和并行回复；Agent 会话（cherry://session-<id>）按时间顺序读取并保留其工作区目录。"
---

Agent Dump 以只读方式读取 Cherry Studio 2.x 的本地 SQLite 数据库（`cherrystudio.sqlite`），支持统一搜索、终端浏览，并将普通聊天和 Agent 会话导出为 Markdown 或结构化 JSON。

## 安装或免安装试用

```sh
# macOS / Linux (Homebrew)
brew install xingkaixin/tap/agent-dump

# macOS / Linux (一键脚本)
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh

# 或免安装直接运行（需要 Node.js 22+）
npx @agent-dump/cli list --days 30 --query 'provider:cherry'
```

Windows（Scoop）、`uv`、`npm` 见[全部安装选项](/zh/#install)。

## 列出 Cherry Studio 聊天与 Agent 会话

```sh
agent-dump list --days 30 --query 'provider:cherry'
```

Cherry Studio 使用两种 URI 形式：

- `cherry://topic-<id>` — 普通聊天（导出当前激活路径，无工作目录）。
- `cherry://session-<id>` — Agent 会话（按时间顺序读取，保留工作区目录，因此支持 `path:.` 筛选）。

## 导出为 Markdown 或 JSON

将 `YOUR_ID` 替换为列表中的真实 `topic-<id>` 或 `session-<id>`：

```sh
# 导出为 Markdown
agent-dump export 'cherry://topic-YOUR_ID' --format markdown --output ./exports

# 同时导出 Markdown 和结构化 JSON
agent-dump export 'cherry://session-YOUR_ID' --format json,markdown --output ./exports

# 在终端阅读器中浏览并批量导出
agent-dump browse --days 30 --query 'provider:cherry'
```

文件会写入 `./exports/cherry/<id>.md` 和 `.json`。Cherry Studio 支持 `markdown`、`json` 和 `print`（不支持 `raw`）。正文、推理、工具调用/结果、代码块和翻译内容均会被归一化，JSON 还会保留文件引用与各币种原始费用记录。

## 便携版目录与排查

Agent Dump 按以下顺序定位 Cherry Studio 数据库：

1. 环境变量 `CHERRYSTUDIO_USER_DATA_DIR` 或 `CHERRY_STUDIO_USER_DATA_DIR` 下的 `Data/cherrystudio.sqlite`
2. `~/.cherrystudio/boot-config.json` 中配置的用户数据目录
3. 系统默认目录：macOS `~/Library/Application Support/CherryStudio`、Windows `%APPDATA%\CherryStudio`、Linux `${XDG_CONFIG_HOME:-~/.config}/CherryStudio`

使用便携版、开发版或同时存在多个安装目录时，可设置 `CHERRYSTUDIO_USER_DATA_DIR` 后运行 `agent-dump providers` 核对实际命中的数据库。已删除的会话与消息会被自动排除。

接下来可以[把导出的 Markdown 保存到 Obsidian](/zh/guides/save-ai-conversations-to-obsidian/)，或[跨工具搜索全部 AI 编码历史](/zh/guides/search-ai-coding-history/)。
