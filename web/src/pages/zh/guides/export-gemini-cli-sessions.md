---
layout: "../../../layouts/Guide.astro"
locale: "zh"
slug: "export-gemini-cli-sessions"
category: "export"
order: 4
updated: "2026-11-27"
title: "将 Gemini CLI 会话导出为 Markdown 和 JSON"
description: "从本地 ~/.gemini/tmp 导出 Google Gemini CLI 对话与子代理记录为 Markdown、JSON 或原始文件。支持 JSONL 回放与思考摘要，本地只读。"
faq:
  - question: "Gemini CLI 的本地对话记录保存在哪里？"
    answer: "Gemini CLI 将对话保存在 ~/.gemini/tmp/<project>/chats/*.jsonl（以及旧版 *.json），子代理对话在 chats/<parent-session-id>/ 下。如果自定义了目录，请将 GEMINI_CLI_HOME 指向包含 .gemini 的上级目录。"
  - question: "Agent Dump 支持处理 Gemini CLI 的回退（rewind）和 JSONL 增量更新吗？"
    answer: "支持。Agent Dump 会按顺序回放 JSONL 记录（包括 $set、$patch 和 $rewindTo），让导出内容与实际对话一致。若旧版 .json 会话已续写为 .jsonl，则只读取 .jsonl。"
  - question: "思考摘要和 Token 统计会保留吗？"
    answer: "会。思考摘要会归一化为推理内容，工具调用会关联对应的 functionResponse 结果；输入 Token 包含缓存与工具提示词，输出 Token 包含思考过程。"
---

Agent Dump 可以直接从本机 `~/.gemini/tmp` 只读读取 Google Gemini CLI 会话，并导出为 Markdown、结构化 JSON 或原始文件。全部在本地完成，不需要配置 Google API Key。

## 安装或免安装试用

```sh
# macOS / Linux (Homebrew)
brew install xingkaixin/tap/agent-dump

# macOS / Linux (一键脚本)
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh

# 或免安装直接试跑（需要 Node.js 22+）
npx @agent-dump/cli list --days 30 --query 'provider:gemini-cli'
```

Windows（Scoop）、`uv`、`npm` 见[全部安装选项](/zh/#install)。

## 列出 Gemini CLI 会话

查看最近 30 天的 Gemini CLI 对话，或在项目目录下只看当前项目：

```sh
agent-dump list --days 30 --query 'provider:gemini-cli'
agent-dump list --days 30 --query 'provider:gemini-cli path:.'
```

工作目录来自 `tmp/<project>/.project_root`。`chats/<parent-session-id>/` 中的子代理对话会作为独立的 `gemini-cli://<session-id>` 会话列出。

## 导出为 Markdown、JSON 或原始文件

将 `YOUR_SESSION_ID` 替换为列表中的真实 ID：

```sh
# 导出为 Markdown
agent-dump export 'gemini-cli://YOUR_SESSION_ID' --format markdown --output ./exports

# 同时导出 Markdown 和结构化 JSON
agent-dump export 'gemini-cli://YOUR_SESSION_ID' --format json,markdown --output ./exports

# 或在终端阅读器中浏览并批量导出
agent-dump browse --days 30 --query 'provider:gemini-cli'
```

文件会写入 `./exports/gemini-cli/<session-id>.md` 和 `.json`。传 `--format raw` 可复制未加工的原始记录。

```markdown
# Session Dump

- URI: `gemini-cli://3f9a2c41`

## 1. User

本地重跑 SQLite 迁移时为什么报错？

## 2. Assistant

迁移脚本创建索引时缺少 IF NOT EXISTS，加上条件判断后重复执行就会保持幂等。
```

## 自定义路径与排查

- Agent Dump 依次检查 `GEMINI_CLI_HOME/.gemini/tmp` 和 `~/.gemini/tmp`。注意 `GEMINI_CLI_HOME` 应指向**包含** `.gemini` 的目录，而不是 `.gemini/tmp` 本身。
- 运行 `agent-dump providers` 核对检测到的 Gemini CLI 路径。
- 缺少 `sessionId` 或没有任何消息的空会话会被自动跳过。

接下来可以[跨 Gemini CLI、Claude Code 与 Codex 搜索历史](/zh/guides/search-ai-coding-history/)，或[将对话保存到 Obsidian](/zh/guides/save-ai-conversations-to-obsidian/)。
