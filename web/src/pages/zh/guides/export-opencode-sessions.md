---
layout: "../../../layouts/Guide.astro"
locale: "zh"
slug: "export-opencode-sessions"
category: "export"
order: 5
updated: "2026-11-27"
title: "将 OpenCode 会话导出为 Markdown 和 JSON（兼容 1.x / 2.x）"
description: "只读读取本地 OpenCode 1.x 与 2.x 的 opencode.db，导出对话为 Markdown 或 JSON。支持自定义 OPENCODE_DB 数据库，无需 API Key。"
faq:
  - question: "Agent Dump 支持 OpenCode 2.x 吗？"
    answer: "支持。Agent Dump 同时兼容 OpenCode 2.x 的 session_v2/session_message 表和旧版 SQLite 表。同一会话 ID 共存时以 V2 为准；当 OpenCode 完成 migration.v1-v2 迁移后仅读取 V2，避免已删除会话重新出现。"
  - question: "OpenCode 数据库默认在哪里？如何指定 channel 数据库？"
    answer: "默认读取 $XDG_DATA_HOME/opencode/opencode.db 或 ~/.local/share/opencode/opencode.db（Windows 兼容旧版 AppData 路径）。设置环境变量 OPENCODE_DB 可指定自定义路径或该目录下的其他 channel 数据库。"
  - question: "OpenCode 的 --format raw 会输出什么？"
    answer: "对于 SQLite 存储的 OpenCode 会话，--format raw 输出归一化后的 .raw.json 快照，而不是 OpenCode 导入文件。日常阅读建议用 --format markdown，脚本分析用 --format json。"
---

Agent Dump 以只读方式读取本地 OpenCode SQLite 数据库（同时支持旧版结构与 OpenCode 2.x `session_v2`），可将对话导出为 Markdown 或结构化 JSON，不修改 `opencode.db`。

## 安装或免安装试用

```sh
# macOS / Linux (Homebrew)
brew install xingkaixin/tap/agent-dump

# macOS / Linux (一键脚本)
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh

# 或免安装直接运行（需要 Node.js 22+）
npx @agent-dump/cli list --days 30 --query 'provider:opencode'
```

Windows（Scoop）、`uv`、`npm` 见[全部安装选项](/zh/#install)。

## 列出 OpenCode 会话

查看最近 30 天更新过的会话，或在项目目录下限定当前仓库：

```sh
agent-dump list --days 30 --query 'provider:opencode'
agent-dump list --days 30 --query 'provider:opencode path:.'
```

活跃和归档会话都会以 `opencode://<session-id>` 列出，没有可见消息的空会话会自动跳过。

## 导出为 Markdown 或 JSON

将 `YOUR_SESSION_ID` 替换为列表中的真实 ID：

```sh
# 导出为 Markdown
agent-dump export 'opencode://YOUR_SESSION_ID' --format markdown --output ./exports

# 同时导出 Markdown 和结构化 JSON
agent-dump export 'opencode://YOUR_SESSION_ID' --format json,markdown --output ./exports

# 在终端阅读器中浏览并批量导出
agent-dump browse --days 30 --query 'provider:opencode'
```

文件会保存到 `./exports/opencode/<session-id>.md` 和 `.json`。输入 Token 汇总包含缓存读写，输出 Token 包含推理部分。

```markdown
# Session Dump

- URI: `opencode://5c4b3a12`

## 1. User

帮我确认本地 auth timeout 是否比网关空闲窗口更短？

## 2. Assistant

是的，客户端 auth timeout 为 30s，网关刷新窗口是 45s，对齐阈值后即可消除误重试。
```

## 指定自定义或 channel 数据库

如果你使用自定义构建或测试通道数据库，通过 `OPENCODE_DB` 指定：

```sh
OPENCODE_DB=opencode-beta.db agent-dump list --days 30 --query 'provider:opencode'
```

相对路径会基于 `$XDG_DATA_HOME/opencode`（或 `~/.local/share/opencode`）解析。显式指定的路径不存在时会直接报错，不会静默回退到其他数据库。运行 `agent-dump providers` 可随时确认实际命中的数据库路径。

接下来可以[跨 OpenCode、Codex 与 Claude Code 搜索历史](/zh/guides/search-ai-coding-history/)，或[把对话保存到 Obsidian](/zh/guides/save-ai-conversations-to-obsidian/)。
