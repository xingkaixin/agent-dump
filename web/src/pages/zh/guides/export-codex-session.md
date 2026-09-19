---
layout: ../../../layouts/Guide.astro
locale: zh
title: 将 Codex 会话导出为 Markdown
description: 使用 Agent Dump 找到本地 Codex 会话，复制真实 URI，并导出 Markdown 或 JSON。包含安装步骤、输出路径和找不到会话时的排查方法。
---

使用 Agent Dump，可以把保存在本地的 Codex 对话导出为 Markdown 文件。先安装 CLI、列出会话，再将真实会话 URI 传给导出命令。源会话保持不变，导出的文件可以在编辑器或笔记应用中阅读。

## 1. 安装 Agent Dump

如果已经安装 npm 和 Node.js 22 或更新版本：

```sh
npm install -g @agent-dump/cli
agent-dump --version
```

如果使用 uv，也可以运行 `uv tool install agent-dump`。其他方式见[安装选项](/zh/#install)。

请在存有 Codex 会话的机器上，使用保存这些会话的用户账户运行后续命令。Agent Dump 读取本地记录，不会从 OpenAI 账户下载对话。

## 2. 找到会话 URI

列出最近 30 天的 Codex 会话：

```sh
agent-dump --list -days 30 -query "provider:codex"
```

根据标题和工作目录找到目标对话，复制该条目中的完整 `codex://…` URI。`codex://<session-id>` 和 `codex://threads/<session-id>` 两种格式都支持。

列表默认只查询最近七天，`-days 30` 将范围扩大到 30 天。列出会话不会导出文件。

## 3. 导出 Markdown

将下面的 `YOUR_SESSION_ID` 替换为真实会话 ID，或将引号内的整个 URI 替换为刚才复制的 URI：

```sh
agent-dump "codex://YOUR_SESSION_ID" --format markdown --output ./exports
```

`YOUR_SESSION_ID` 是占位符，不是已有会话。命令会打印导出文件的路径。使用这里的输出目录时，Codex 的 Markdown 文件会写到 `./exports/codex/<session-id>.md`，相对路径从运行命令的当前目录计算。

## 4. 查看导出结果

在编辑器或 Markdown 笔记应用中打开命令打印的 `.md` 文件，即可阅读对话。不传 `--output` 时，Markdown 默认写到 `./sessions/codex/<session-id>.md`。

如果需要程序处理，可以改用 JSON，也可以一次导出两种格式：

```sh
agent-dump "codex://YOUR_SESSION_ID" --format json,markdown --output ./exports
```

这些列表和导出命令在本地执行，不需要 AI API key。导出得到的是可阅读的记录，不会恢复正在运行的 Agent、运行环境或执行状态。

## 找不到会话时

- 如果会话较早，将日期范围扩大，例如改为 `-days 90`。
- 运行 `agent-dump --providers`，检查 Codex 数据源目录是否可用。这个命令不会扫描会话。
- 检查用户账户和 `CODEX_HOME` 环境变量。Codex 按 `CODEX_HOME`、`~/.codex`、开发回退目录 `data/codex` 的顺序查找。自定义 `CODEX_HOME` 应指向 Codex 主目录，而不是某个会话文件。
- 从最新列表复制完整 URI，不要原样执行示例占位符。
- 如果源记录只在另一台机器上，请在那台机器导出。Agent Dump 无法恢复已删除或不可访问的源记录。

更多格式和筛选方式见 [CLI 参数说明](https://github.com/xingkaixin/agent-dump/blob/main/README_zh.md)。其他工具的会话导出能力见 [Agent Dump 功能介绍](/zh/#capabilities)。
