---
layout: "../../../layouts/Guide.astro"
locale: "zh"
slug: "export-claude-code-conversations"
category: "export"
order: 2
updated: "2026-11-22"
title: "将 Claude Code 对话导出为 Markdown 和 JSON"
description: "找到本地 Claude Code 会话，将对话导出为 Markdown 或 JSON。了解输出路径、多格式导出，以及找不到项目历史时的排查方法。"
---

Agent Dump 可以将本地保存的 Claude Code 对话导出成文件。Markdown 适合项目笔记和代码评审，JSON 适合后续脚本处理。导出过程不会修改 Claude Code 的原始会话记录。

## 安装并找到对话

在使用 Claude Code 的那台机器上执行。如果已安装 npm 和 Node.js 22 或以上版本：

```sh
npm install -g @agent-dump/cli
agent-dump --list --days 30 --query 'provider:claude'
```

也可以选择[原生二进制、Homebrew、Scoop 或 uv 安装](/zh/#install)。列表会筛选最近 30 天有更新的会话，包括创建得较早但最近还在使用的对话。需要按创建时间筛选时，增加 `--time-field created`。

根据标题和工作目录找到目标对话，复制完整的 `claude://...` URI。只查当前项目时，在项目目录中运行：

```sh
agent-dump --list --days 30 --query 'provider:claude path:.'
```

## 导出可阅读的记录

将 `YOUR_SESSION_ID` 替换为列表中的真实会话 ID：

```sh
agent-dump 'claude://YOUR_SESSION_ID' --format markdown --output ./exports
```

命令会打印保存路径。Markdown 文件位于当前工作目录下的 `./exports/claude/` 中。打开打印出的文件即可阅读。这个文件是对话记录，不会恢复原来的 Agent 进程或执行状态。

## 同时保留结构化数据

既需要阅读，又需要脚本处理时，可以一次生成两种格式：

```sh
agent-dump 'claude://YOUR_SESSION_ID' --format json,markdown --output ./exports
```

`--format json` 会写出导出文件。它与 `--json` 不同，后者用于受支持的查询和读取模式，将结构化结果写到标准输出。脚本只需要长对话的一部分时，可以使用[分页读取](/zh/guides/handoff-context-to-ai-agent/)。

## 导出多段对话

如果需要在终端中手动选择多个会话：

```sh
agent-dump --interactive --query 'provider:claude' --format markdown --output ./exports
```

按照终端提示选择会话。这个流程需要交互式终端；自动化导出单个会话时，直接传入 URI。

## 找不到历史记录时

执行 `agent-dump --providers` 检查源路径是否可用，并适当增大 `--days`。确认当前操作系统账号和机器与运行 Claude Code 时一致。`path:.` 匹配记录中的工作目录，可以移除它检查是否过滤掉了目标会话。

Agent Dump 读取本地保存的历史，不能从远程账号拉取缺失内容，也不能恢复被删除的源文件。分享导出文件前，先确认其中没有不适合公开的项目信息。

接下来可以[跨工具搜索历史对话](/zh/guides/search-ai-coding-history/)，或[将导出结果保存到 Obsidian](/zh/guides/save-ai-conversations-to-obsidian/)。

## 延伸阅读

- [你跟 AI 的每一次编码对话，都在悄悄消失](https://xingkaixin.me/posts/codesesh-ai-coding-sessions-disappearing/) — 讨论 AI 编码会话留存与跨工具查看的问题，以及从 agent-dump 出发的实践。
- [进程挂了 resume 回来，agent 却僵住了：log 才是 agent 本体](https://xingkaixin.me/posts/log-lock-in/) — 解释为什么 Claude Code 的对话记录不等于可恢复的执行状态。
