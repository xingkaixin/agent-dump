---
layout: "../../../layouts/Guide.astro"
locale: "zh"
slug: "export-cursor-chat-history"
category: "export"
order: 3
updated: "2026-11-27"
title: "从 state.vscdb 导出 Cursor 聊天与 Composer 记录"
description: "只读读取本地 Cursor 的 globalStorage/state.vscdb，列出、搜索并导出 Composer 对话为结构化 JSON 或可阅读文本。免费本地 CLI，不改源库。"
faq:
  - question: "Cursor 的本地聊天记录保存在哪里？"
    answer: "Cursor 把 Composer 对话保存在 globalStorage/state.vscdb 中：macOS 默认在 ~/Library/Application Support/Cursor/User，Windows 在 %APPDATA%\\Cursor\\User，Linux 在 ~/.config/Cursor/User。项目目录来自 workspaceStorage/*/workspace.json。"
  - question: "Agent Dump 支持把 Cursor 直接导出为 Markdown 吗？"
    answer: "Cursor 目前仅支持 --format json 和 --format print，不支持 --format markdown 或 --format raw。因为直接打印 URI 会把 Markdown 风格的对话文本输出到标准输出，你可以用 agent-dump 'cursor://YOUR_COMPOSER_ID' > session.md 保存为文件，或导出 JSON 后处理。"
  - question: "读取 state.vscdb 会影响正在运行的 Cursor 吗？"
    answer: "不会。Agent Dump 严格以只读方式打开 Cursor 的 SQLite 数据库，绝不写入 Cursor 的用户数据目录，导出文件只写到你指定的输出路径。"
---

Cursor 把本地 Composer 和聊天历史存在内部 SQLite 数据库（`state.vscdb`）里，不方便在编辑器外检索或归档。Agent Dump 以只读方式读取该数据库，让你无需改动 IDE 数据就能列出、全文搜索、浏览并导出 Cursor 对话。

## 安装或免安装试用

```sh
# macOS / Linux (Homebrew)
brew install xingkaixin/tap/agent-dump

# macOS / Linux (一键脚本)
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh

# 或免安装直接运行（需要 Node.js 22+）
npx @agent-dump/cli list --days 30 --query 'provider:cursor'
```

Windows（Scoop）、`uv`、`npm` 见[全部安装选项](/zh/#install)。

## 找到 Cursor 会话

列出最近 30 天的 Cursor 对话，或在项目目录下限定当前工作区：

```sh
agent-dump list --days 30 --query 'provider:cursor'
agent-dump list --days 30 --query 'provider:cursor path:.'
```

列表会显示标题、匹配到的工作区路径以及 `cursor://<composer-id>` URI（旧版 `cursor://<request-id>` 同样可解析到同一会话）。

## 导出为结构化 JSON

将 `YOUR_COMPOSER_ID` 替换为列表中的真实 ID：

```sh
agent-dump export 'cursor://YOUR_COMPOSER_ID' --format json --output ./exports
```

命令会将归一化后的 JSON 写入 `./exports/cursor/<composer-id>.json`，包含元数据、消息内容和已记录的 token 统计：

```json
{
  "id": "8821c4e0",
  "title": "重构鉴权中间件",
  "directory": "/Users/dev/app",
  "stats": {
    "message_count": 12,
    "total_input_tokens": 18420,
    "total_output_tokens": 2150
  },
  "messages": [
    {
      "role": "user",
      "parts": [{ "type": "text", "text": "为什么 401 时 token 刷新会死循环？" }]
    }
  ]
}
```

## 输出可阅读文本或在终端浏览

Cursor 支持 `json` 和 `print` 两种格式（传入 `--format markdown` 或 `--format raw` 会给出能力说明并拒绝）。如需保存可阅读文本，直接打印 URI 并重定向即可：

```sh
# 将可读对话保存到文件
agent-dump 'cursor://YOUR_COMPOSER_ID' > ./exports/cursor-chat.md

# 或在终端阅读器中交互浏览和搜索
agent-dump browse --days 30 --query 'provider:cursor'
```

## 自定义数据目录与排查

Agent Dump 按 `CURSOR_DATA_PATH/globalStorage/state.vscdb` 顺序查找，未设置环境变量时使用默认 `User` 目录：

- **macOS**：`~/Library/Application Support/Cursor/User`
- **Windows**：`%APPDATA%\Cursor\User`
- **Linux**：`${XDG_CONFIG_HOME:-~/.config}/Cursor/User`

如果查不到会话，运行 `agent-dump providers` 核对识别到的数据库路径，将 `--days` 放大到 `90`，或移除 `path:.`（项目路径来自引用了该 composer 的 `workspaceStorage/*/workspace.json`）。

接下来可以[跨 Cursor、Codex 与 Claude Code 全文搜索](/zh/guides/search-ai-coding-history/)，或[把历史对话交给下一个 AI Agent](/zh/guides/handoff-context-to-ai-agent/)。
