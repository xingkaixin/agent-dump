---
layout: "../../../layouts/Guide.astro"
locale: "zh"
slug: "export-claude-code-conversations"
category: "export"
order: 2
updated: "2026-11-27"
title: "将 Claude Code 对话导出为 Markdown 和 JSON"
description: "从本地 ~/.claude/projects 导出 Claude Code 会话与子代理记录为 Markdown、含 Token 统计的 JSON 或原始 JSONL。免费只读 CLI，支持批量导出。"
faq:
  - question: "Claude Code 的本地对话记录保存在哪里？"
    answer: "Claude Code 默认把会话保存为 ~/.claude/projects/<project>/<session>.jsonl，子代理记录在 <session>/subagents/ 下。如果你自定义了配置目录，运行前设置 CLAUDE_CONFIG_DIR 即可。"
  - question: "agent-dump 的 --format json 和 Claude Code 的 --output-format json 有什么区别？"
    answer: "Claude Code 的 --output-format json 是单次无头运行时输出到标准输出的结果对象（包含 session_id、total_cost_usd、usage tokens）；agent-dump 的 --format json 离线读取 ~/.claude/projects 下的本地 JSONL，导出归一化消息与 total_input_tokens / total_output_tokens 汇总。本地 JSONL 不记录美元费用，因此 stats.total_cost 为 0。"
  - question: "和 Claude Code 内置的 /export 或 --resume 有什么区别？"
    answer: "内置 /export 只能逐个导出当前打开的会话，--resume 则是重新进入交互。Agent Dump 以只读方式读取所有历史会话和子代理，支持全文搜索、批量导出和带 Token 统计的归一化 JSON，并且支持跨 19 款工具统一操作。"
  - question: "可以导出 claude.ai 网页版对话吗？"
    answer: "不可以。Agent Dump 只读取本机保存的 Claude Code CLI 会话，不连接 claude.ai 网页账号，也不解析网页端导出的 conversations.json 压缩包。"
---

Agent Dump 可以把本机保存的 Claude Code CLI 会话导出为干净的 Markdown 或结构化 JSON 文件，不修改任何原始记录。Markdown 适合归档笔记和代码评审，JSON 适合脚本处理与 Token 统计。整个过程在本地执行，不需要 API Key。

```sh
# 列出近期 Claude Code 会话，并导出为 JSON + Markdown
npx @agent-dump/cli list --days 30 --query 'provider:claude'
npx @agent-dump/cli export 'claude://YOUR_SESSION_ID' --format json,markdown --output ./exports
```

> 本指南针对本地 **Claude Code CLI** 会话（`~/.claude/projects/`），不涉及 `claude.ai` 网页版数据导出。

## 安装或免安装试用

推荐直接安装原生二进制（无需 Python 或 Node.js），也可以用 `npx` 直接试用：

```sh
# macOS / Linux (Homebrew)
brew install xingkaixin/tap/agent-dump

# macOS / Linux (一键脚本)
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh

# 或免安装直接试跑（需要 Node.js 22+）
npx @agent-dump/cli list --days 30 --query 'provider:claude'
```

Windows（Scoop）、`uv`、`npm`、`bun` 等方式见[全部安装选项](/zh/#install)。请在运行过 Claude Code 的同一台机器和系统账号下执行命令。

## 找到 Claude Code 会话

列出最近 30 天更新过的会话，或在项目目录里只看当前项目：

```sh
agent-dump list --days 30 --query 'provider:claude'
agent-dump list --days 30 --query 'provider:claude path:.'
```

列表会打印会话标题、工作目录和 `claude://<session-id>` URI；`<session>/subagents/` 中的子代理也会作为独立会话列出。默认按最近更新时间筛选，如需按创建时间或精确日期范围筛选，使用 `--time-field created` 或 `--since` / `--until`。

## 导出为 Markdown

将 `YOUR_SESSION_ID` 替换为列表中的真实会话 ID：

```sh
agent-dump export 'claude://YOUR_SESSION_ID' --format markdown --output ./exports
```

命令会打印保存路径，默认写入 `./exports/claudecode/<session-id>.md`。导出的 Markdown 结构如下：

```markdown
# Session Dump

- URI: `claude://7f3c91ab`

## 1. User

鉴权上游超过 30s 无响应时，登录重试会一直堆积。

## 2. Assistant

把请求的 AbortSignal 透传进重试循环，触发超时后立即终止已取消的登录尝试。
```

导出得到的是可携带的纯文本记录，不会恢复原来的 Claude Code 进程或执行状态。

## 导出结构化 JSON 或原始 JSONL

一次命令可同时导出 Markdown 和归一化 JSON：

```sh
agent-dump export 'claude://YOUR_SESSION_ID' --format json,markdown --output ./exports
```

`--format json` 会写出归一化 JSON，包含会话元数据（`id`、`title`、`directory`、`version`、`time_created`、`time_updated`）、汇总统计 `stats` 以及带单轮 `tokens` 的 `messages` 数组：

```json
{
  "id": "7f3c91ab",
  "title": "修复登录超时重试",
  "directory": "/Users/dev/project",
  "stats": {
    "message_count": 18,
    "total_input_tokens": 42180,
    "total_output_tokens": 3940,
    "total_cost": 0
  },
  "messages": [
    {
      "role": "assistant",
      "tokens": {
        "input_tokens": 1240,
        "output_tokens": 310,
        "cache_read_input_tokens": 8900,
        "cache_creation_input_tokens": 0
      },
      "parts": [{ "type": "text", "text": "把请求的 AbortSignal 透传进重试循环..." }]
    }
  ]
}
```

### 字段对照：`--output-format json`、本地 JSONL 与 Agent Dump

Claude Code 运行时的 `--output-format json` 只输出单次无头调用的汇总结果；本地 `~/.claude/projects/<project>/<session>.jsonl` 保存完整多轮记录。下表对应三者常见字段：

| 字段 | Claude Code `--output-format json` | 本地 `~/.claude/projects/*.jsonl` | `agent-dump export --format json` |
| --- | --- | --- | --- |
| 会话 ID | `session_id` | `sessionId` | `id` |
| 输入 Token | `usage.input_tokens`（含缓存字段） | `message.usage.input_tokens`、`cache_read_input_tokens`、`cache_creation_input_tokens` | `stats.total_input_tokens`（含缓存输入）与 `messages[].tokens` |
| 输出 Token | `usage.output_tokens` | `message.usage.output_tokens` | `stats.total_output_tokens` 与 `messages[].tokens.output_tokens` |
| 费用（USD） | `total_cost_usd` | 本地 JSONL 未记录 | `stats.total_cost`（Claude Code 固定为 `0`） |
| 范围 | 单次无头命令输出 | 磁盘原始多轮日志 | 归一化归档会话与子代理 |

如需保留未加工的源文件，使用 `--format raw` 导出 `.raw.jsonl`。注意 `--format json` 是写出导出文件，与 `--json`（将查询和分页读取结果输出到标准输出）不同。若脚本只需读取长会话的一部分，请看[分页读取与 Agent 交接](/zh/guides/handoff-context-to-ai-agent/)。

## 在终端中浏览与批量导出

想预览内容并一次导出多个 Claude Code 会话：

```sh
agent-dump browse --days 30 --query 'provider:claude'
```

在阅读器中按 `Space` 标记多个会话，按 `e` 批量导出。也可以直接运行 `agent-dump export --query 'provider:claude' --format markdown --output ./exports` 指定格式与输出目录后进行勾选。

## 源路径与排查方法

Agent Dump 优先读取 `CLAUDE_CONFIG_DIR`，否则读取 `~/.claude`，扫描 `projects/<project>/<session>.jsonl` 和 `<session>/subagents/`。

找不到历史记录时：

- 执行 `agent-dump providers`，确认检测到的 Claude Code 源路径是否可用。
- 用 `--days 90` 或 `--since` / `--until` 扩大时间范围。
- 去掉 `path:.`，确认是不是因为启动目录不同被过滤掉了。
- 没有可见用户/助手消息的空会话会被自动跳过。

接下来可以[跨工具搜索 AI 编码历史](/zh/guides/search-ai-coding-history/)，或[把对话保存到 Obsidian](/zh/guides/save-ai-conversations-to-obsidian/)。

## 延伸阅读

- [你跟 AI 的每一次编码对话，都在悄悄消失](https://xingkaixin.me/posts/codesesh-ai-coding-sessions-disappearing/) — 讨论 AI 编码会话留存与跨工具查看的问题，以及从 agent-dump 出发的实践。
- [进程挂了 resume 回来，agent 却僵住了：log 才是 agent 本体](https://xingkaixin.me/posts/log-lock-in/) — 解释为什么 Claude Code 的对话记录不等于可恢复的执行状态。
