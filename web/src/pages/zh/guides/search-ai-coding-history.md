---
layout: "../../../layouts/Guide.astro"
locale: "zh"
slug: "search-ai-coding-history"
category: "search"
order: 3
updated: "2026-10-06"
title: "搜索 AI 编码历史，找回过去的决策"
description: "跨 Codex、Claude Code 等本地工具搜索过去的修复方案和技术决策。按项目筛选，定位匹配消息，再阅读前后上下文。"
---

记得以前解决过一个问题，却不记得用的是哪个编码工具时，可以用 Agent Dump 搜索本地对话历史。先按关键词找回会话，再定位具体消息，最后保留带来源的上下文片段。

先[安装 Agent Dump](/zh/#install)，在保存了源会话的机器上运行命令。搜索在本地完成，不需要 AI API Key。

## 按记得的词搜索

```sh
agent-dump --search 'auth timeout' --days 90
```

每个不同的搜索词都需要在该会话中出现，但可以位于不同消息或字段。它是字面全文搜索，不是语义搜索。搜索范围包括归一化后的标题、消息、推理和工具状态，不把 `AND` 等 FTS 操作符当作查询语法。

默认日期窗口是七天。查更早的工作时增大 `--days`。如果要找最近仍在使用的旧会话，按更新时间筛选：

```sh
agent-dump --search 'auth timeout' --time-field updated --days 7
```

## 限定项目或工具

进入目标项目的工作目录后运行：

```sh
agent-dump --search 'database migration' --days 90 --query 'provider:codex,claude path:.'
```

`--query` 用于追加筛选条件。它的关键词部分与 `--search` 匹配方式相同，空白分隔的每个词都必须出现。`--search` 还会按相关度排序并显示证据，因此搜索词放在 `--search`，范围放在 `--query`。

## 定位原始依据

增加 `--locate --json`，获取带消息位置的结构化结果：

```sh
agent-dump --search 'database migration' --days 90 --locate --json
```

从返回结果中取出 URI 和消息定位符，替换下面两个占位符：

```sh
agent-dump 'codex://YOUR_SESSION_ID' --message 'REVISION:POSITION' --before 2 --after 3
```

命令会打印目标消息，以及前两条、后三条消息。仅标题匹配时，可能没有消息位置。定位符与源版本绑定；会话继续更新后，需要重新搜索，不能继续使用过期定位符。

## 在终端中阅读

需要交互式浏览时：

```sh
agent-dump --browse --days 90 --query 'provider:codex,claude path:.'
```

选中会话后按 Enter 阅读。`/` 在当前对话中搜索，`n` 和 `N` 在匹配项之间移动，`t` 展开工具细节，`q` 退出。此模式需要交互式终端，脚本应使用[分页 JSON 读取](/zh/guides/handoff-context-to-ai-agent/)。

## 保留一小段上下文

```sh
agent-dump 'codex://YOUR_SESSION_ID' --message 'REVISION:POSITION' --before 2 --after 3 --format json,markdown --output ./excerpts
```

导出的片段会保留会话 URI、定位符和消息范围。检查命令报告的输出路径及诊断信息；源会话保持不变。格式仍受工具能力限制，例如 Cursor 支持 JSON 和打印，不支持 Markdown。

没有结果时，可以减少关键词、扩大日期范围、移除项目筛选，并执行 `agent-dump --providers` 检查源是否可用。
