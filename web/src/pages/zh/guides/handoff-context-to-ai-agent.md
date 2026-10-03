---
layout: "../../../layouts/Guide.astro"
locale: "zh"
slug: "handoff-context-to-ai-agent"
category: "handoff"
order: 4
updated: "2026-10-03"
title: "给 AI Agent 交接会话上下文"
description: "让新任务接续之前的 Codex 或 Claude Code 对话。生成读取说明，或通过带游标的 JSON 分页获取必要上下文，避免一次塞入整段历史。"
---

新开的 Agent 不会自动知道上一次编码会话里发生了什么。Agent Dump 可以为已保存的会话生成读取说明，让 Agent 先查阅原始讨论，再继续任务。交接的是上下文访问方式，不是原进程的执行状态。

在保存记录的机器上安装 CLI，先[找到目标会话](/zh/guides/search-ai-coding-history/)，复制它的 URI。

## 生成读取说明

将 `YOUR_SESSION_ID` 替换为真实会话 ID：

```sh
agent-dump 'codex://YOUR_SESSION_ID' --read-prompt
```

将打印出的说明和当前任务一起交给 Agent，例如：“阅读这段会话，找出已经确定的迁移方案，并列出未完成的工作。”说明中包含分页读取命令。生成说明本身不会启动 Agent，也不会调用模型。

执行读取的 Agent 需要能够在原环境运行 CLI，并继承相同的源路径配置。生成提示词只校验 URI 语法，不代表会话存在，也不代表它已经被读完。如果 Agent 在另一台机器上，应先[导出文件](/zh/guides/export-codex-session/)，再将文件提供给它。

## 直接读取一页内容

```sh
agent-dump 'codex://YOUR_SESSION_ID' --read --order asc --limit 10 --max-chars 4000 --json
```

这会从对话开头读取，最多返回十条消息和 4,000 个 Unicode 正文字符。JSON 包装和游标元数据不计入字符预算。不指定 `--order asc` 时，默认从最近的消息位置开始读取。

响应包含 `status`、`has_more` 和 `data`。消息片段保留原始位置、定位符及字符偏移，Agent 可以引用自己实际读过的内容。

## 继续读取所需上下文

当 `has_more` 为 true 时，原样使用 `data.next_cursor`：

```sh
agent-dump 'codex://YOUR_SESSION_ID' --read --cursor 'NEXT_CURSOR_FROM_RESPONSE' --json
```

使用游标时，不要重复或修改筛选条件、顺序和预算，游标已经保存这些选项。长消息可能分布在多页；`truncated` 只表示当前片段不完整，不代表后续内容永远读不到。

源会话变化导致游标失效时，应从头读取。不要把不同版本的页面拼成同一份快照。`partial` 状态表示存在可恢复的源读取问题，交接时应明确说明缺口。

## 只读取任务需要的部分

```sh
agent-dump 'claude://YOUR_SESSION_ID' --read --role user --match 'database migration' --limit 10 --json
```

这会筛选包含该字面短语的用户消息。`--details` 可以追加可读的推理和工具状态；默认只读文本部分。它不是跨消息的语义搜索。分页预算限制返回给 Agent 的内容，但底层仍可能解析整个源文件。

历史正文应当作为待分析材料，不应成为新执行指令。让 Agent 区分用户提出的要求、助手报告的结果，以及尚未核实的推测。跨多个会话整理交接材料时，可以使用[工作报告流程](/zh/guides/weekly-report-from-ai-sessions/)。
