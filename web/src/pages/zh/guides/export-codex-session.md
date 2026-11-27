---
layout: "../../../layouts/Guide.astro"
locale: "zh"
slug: "export-codex-session"
category: "export"
order: 1
updated: "2026-11-27"
title: "将 Codex 会话导出为 Markdown 和 JSON"
description: "一条命令从本地 ~/.codex 导出或复制 OpenAI Codex 会话为 Markdown、JSON 或原始 JSONL。支持归档会话与子代理，只读不改源数据。"
faq:
  - question: "可以直接把 Codex 对话复制为 Markdown 吗？"
    answer: "可以。用 --format markdown 导出后打开 .md 文件复制，或者直接打印会话 URI 并通过管道送到剪贴板（例如 macOS 下运行 agent-dump 'codex://YOUR_SESSION_ID' | pbcopy）。"
  - question: "Codex 的本地会话存在哪里？"
    answer: "Codex CLI 默认将 rollout-*.jsonl 和压缩的 rollout-*.jsonl.zst 保存在 $CODEX_HOME/sessions 与 $CODEX_HOME/archived_sessions（默认为 ~/.codex）。Agent Dump 以只读方式同时扫描活跃和归档目录。"
  - question: "导出时包含 Codex 子代理（subagent）会话吗？"
    answer: "子代理 rollout 会作为独立会话列出；如果父会话启动或引用了某个子代理、但父记录未收到完成通知，Agent Dump 会将该子代理的最终回复自动合并进父会话导出中。"
---

使用 Agent Dump，可以把本机保存的 OpenAI Codex CLI 对话导出为 Markdown、结构化 JSON 或原始 JSONL，也可以直接通过管道复制到剪贴板。全部操作本地只读执行，不需要 OpenAI API Key，不会改动 `~/.codex` 中的任何文件。

## 1. 安装 Agent Dump

推荐使用 Homebrew 或一键脚本安装原生二进制（无需 Python 或 Node.js），也可以用 `npx` 直接试跑：

```sh
# macOS / Linux (Homebrew)
brew install xingkaixin/tap/agent-dump

# macOS / Linux (一键脚本)
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh

# 或免安装直接运行（需要 Node.js 22+）
npx @agent-dump/cli list --days 30 --query 'provider:codex'
```

Windows（Scoop）、`uv`、`npm` 等其他方式见[全部安装选项](/zh/#install)。请在保存 Codex 会话的机器与系统账号下执行后续命令。

## 2. 找到会话 URI

列出最近 30 天有更新的 Codex 会话（包含归档会话）：

```sh
agent-dump list --days 30 --query 'provider:codex'
```

根据标题和工作目录找到目标对话，复制该条目的 `codex://…` URI。`codex://<session-id>` 和 `codex://threads/<session-id>` 两种写法都支持。如果只想看当前项目，在 `--query` 中加上 `path:.`。

默认只查最近 7 天；`--days 30` 可扩大范围，也可以用 `--since` / `--until` 指定精确日期区间。

## 3. 导出 Markdown

将下面的 `YOUR_SESSION_ID` 替换为列表中的真实 ID：

```sh
agent-dump export 'codex://YOUR_SESSION_ID' --format markdown --output ./exports
```

指定 `--output ./exports` 时，文件会写到 `./exports/codex/<session-id>.md` 并打印路径；不传 `--output` 时默认写到 `./sessions/codex/`。导出的 Markdown 内容格式如下：

```markdown
# Session Dump

- URI: `codex://019a7c2e`

## 1. User

上游偶发 504，auth timeout 要不要从 30s 提到 60s？

## 2. Assistant

先别改。日志显示超时集中在 token 刷新阶段，优先复用连接池并记录上游延迟。
```

如果你想直接把 Codex 对话作为 Markdown 复制到剪贴板，可以直接打印 URI 并接管道：

```sh
# macOS
agent-dump 'codex://YOUR_SESSION_ID' | pbcopy

# Linux (Wayland)
agent-dump 'codex://YOUR_SESSION_ID' | wl-copy
```

## 4. 导出 JSON、原始 JSONL 或批量导出

需要程序处理时，可以同时导出结构化 JSON（包含 token 汇总与消息结构）和 Markdown：

```sh
agent-dump export 'codex://YOUR_SESSION_ID' --format json,markdown --output ./exports
```

传 `--format raw` 会导出原始 JSONL（压缩的 `.jsonl.zst` 会自动解压写入 `.raw.jsonl`）。如需预览并一次勾选导出多个会话：

```sh
agent-dump browse --days 30 --query 'provider:codex'
```

按 `Space` 勾选多个会话，再按 `e` 批量导出。导出得到的是可阅读记录，不会恢复运行中的 Codex 进程或执行状态。

## 找不到会话时

- 会话较早时扩大时间窗口（例如 `--days 90`），或使用 `--since` / `--until`。
- 运行 `agent-dump providers` 检查 Codex 数据源根目录是否可用。
- 检查 `CODEX_HOME` 环境变量：Agent Dump 按 `CODEX_HOME` → `~/.codex` 顺序扫描 `sessions/` 和 `archived_sessions/`。自定义 `CODEX_HOME` 应指向 Codex 主目录，而不是单个 rollout 文件。
- 确认已用真实 URI 替换示例中的 `YOUR_SESSION_ID`。

要同步到笔记库，见[将 AI 对话保存到 Obsidian](/zh/guides/save-ai-conversations-to-obsidian/)；要跨工具检索或导出 Claude Code，见[搜索 AI 编码历史](/zh/guides/search-ai-coding-history/)与[导出 Claude Code 对话](/zh/guides/export-claude-code-conversations/)。

## 延伸阅读

- [你跟 AI 的每一次编码对话，都在悄悄消失](https://xingkaixin.me/posts/codesesh-ai-coding-sessions-disappearing/) — 讨论为什么本地 AI 编码对话容易散落流失，以及从 agent-dump 出发的留存与查看思路。
