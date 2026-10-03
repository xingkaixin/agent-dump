---
layout: "../../../layouts/Guide.astro"
locale: "zh"
slug: "save-ai-conversations-to-obsidian"
category: "export"
order: 6
updated: "2026-10-03"
title: "把 AI 对话保存到 Obsidian 知识库"
description: "将 Codex 和 Claude Code 对话保存为 Obsidian 中的 Markdown 笔记。使用独立导出目录，保留关键上下文，并了解归档与恢复的边界。"
---

Agent Dump 可以将受支持的 AI 编码会话导出为普通 Markdown 文件。把输出目录指向 Obsidian 知识库中的独立文件夹，就能在 Obsidian 中打开、链接和搜索这些笔记，不需要额外插件。

这是手动导出流程，不是持续同步。适合保存值得留存的讨论、问题排查过程或项目交接材料。

## 找到需要保留的对话

[安装 Agent Dump](/zh/#install) 后，列出近期会话：

```sh
agent-dump --list --days 30 --query 'provider:codex,claude'
```

从匹配项中复制 URI。如果只记得主题，可以先[搜索对话正文](/zh/guides/search-ai-coding-history/)。CLI 需要运行在保存原始会话的机器上。

## 导出到独立的知识库目录

将会话 ID 和示例知识库路径都替换为真实值。下面是 macOS/Linux 路径示例：

```sh
agent-dump 'codex://YOUR_SESSION_ID' --format markdown --output '/path/to/Your Vault/AI Sessions'
```

包含空格的路径需要引号。Windows 可以使用实际路径，例如 `C:\Notes\My Vault\AI Sessions`。输出目录必须可写，并且应当位于你拥有的独立目录中，不要指向编码工具的会话源目录。

导出文件按来源工具分目录存放。Codex 文件位于知识库内的 `AI Sessions/codex/<session-id>.md`。Claude Code 使用 `claude://...` URI，对应目录为 `AI Sessions/claude/`。CLI 会打印准确的保存路径。

## 单独记录自己的结论

在 Obsidian 中打开导出的文件。把自己的决策、待办和解释写在另一篇项目笔记中，再链接到原始导出。这样可以区分对话记录和个人整理，避免把导出文件直接当作长期编辑的项目计划。

同一会话再次导出会使用相同的目标文件名。需要保留的手工修改应放在另一篇笔记中，或者为新快照指定不同的输出目录。源对话继续更新时，导出文件不会自动同步。

## 只保留必要上下文

完整对话可能很长。如果只需要一次决策及附近讨论，可以使用[消息定位和片段导出](/zh/guides/search-ai-coding-history/)。片段文件会保留源 URI 和消息范围，便于以后核对。

跨多段对话的摘要可以使用[工作报告流程](/zh/guides/weekly-report-from-ai-sessions/)，再将报告保存到知识库。与直接导出的记录不同，报告是模型生成的摘要。

## 了解归档边界

Markdown 导出是可阅读的记录，不是原始 Agent 数据库、附件、执行环境或运行中任务的备份。不同 Provider 支持的格式不同，例如 Cursor 不支持 Markdown 导出。可以通过 `agent-dump --providers` 查看格式能力。

开启知识库同步或分享笔记前，应先检查导出内容。导出过程在本地完成，但保存后的文件会去哪里，取决于知识库自身的同步配置。
