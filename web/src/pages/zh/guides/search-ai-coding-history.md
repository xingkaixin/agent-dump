---
layout: "../../../layouts/Guide.astro"
locale: "zh"
slug: "search-ai-coding-history"
category: "search"
order: 7
updated: "2026-11-27"
title: "跨工具搜索 Claude Code、Codex 与 AI 编码历史"
description: "用本地 SQLite FTS5 全文搜索 Claude Code、Codex、Cursor、Gemini CLI 等 19 款工具的对话历史。按项目筛选、定位消息并导出带引用的上下文片段。"
faq:
  - question: "搜索 AI 编码历史需要配置 API Key 或上传数据吗？"
    answer: "不需要。Agent Dump 在自有缓存目录建立本地 SQLite FTS5 全文索引，所有检索都在本地离线完成，既不需要 API Key，也不会改动任何源会话文件。"
  - question: "全文搜索能搜到会话里的哪些内容？"
    answer: "搜索覆盖归一化后的标题、用户与助手消息正文、推理过程以及工具状态与工具报错，方便找回曾经失败过的命令或报错信息。"
  - question: "可以只搜索某一个项目或指定日期范围内的对话吗？"
    answer: "可以。在项目根目录运行时加上 --query 'path:.' 即可限定当前工作目录，用 provider:claude,codex 限定工具，用 --days 或 --since / --until 限定日期区间。"
---

记得以前和 AI 一起修过某个 bug 或做过某次架构取舍，但忘了当时用的是 Claude Code、Codex、Cursor 还是 Gemini CLI 时，可以用 Agent Dump 一次性跨 19 款工具全文检索本地记录。

通过 `brew install xingkaixin/tap/agent-dump` 或[其他方式](/zh/#install)安装即可使用，全文搜索完全在本地执行，无需 API Key。

## 跨工具全文搜索

在最近 90 天的本地会话中搜索关键词：

```sh
agent-dump search 'auth timeout' --days 90
```

空白分隔的每个词都需要在会话中出现，可以分布在不同消息或字段（标题、正文、推理、工具报错）中。默认回溯最近 7 天（按最近更新时间）；可以用 `--since` / `--until` 指定精确本地日期，或用 `--time-field created` 按创建时间筛选：

```sh
agent-dump search 'auth timeout' --since 2026-11-01 --until 2026-11-27
```

## 限定项目或工具范围

在目标项目目录下运行，把结果收敛到当前项目和指定工具：

```sh
agent-dump search 'database migration' --days 90 --query 'provider:claude,codex path:.'
```

把检索词放在 `search` 中可以按相关度排序并输出命中摘要，范围筛选条件（`provider:`、`path:`、`role:`、`limit:`）放在 `--query` 中。

## 定位具体消息与上下文

加上 `--locate --json` 获取结构化结果与每条命中的消息定位符：

```sh
agent-dump search 'database migration' --days 90 --locate --json
```

把返回的会话 URI 和 `REVISION:POSITION` 定位符传给命令，直接查看命中前后几轮对话：

```sh
agent-dump 'codex://YOUR_SESSION_ID' --message 'REVISION:POSITION' --before 2 --after 3
```

定位符绑定到源会话版本；如果原会话后续有新消息，重新运行 `search --locate` 获取最新定位符。

## 在终端阅读器中交互检索

打开已按项目筛好的终端会话阅读器：

```sh
agent-dump browse --days 90 --query 'provider:claude,codex path:.'
```

按 `Enter` 打开会话，`/` 在当前对话内查找，`n` / `N` 跳转下一处或上一处命中，`t` 展开工具调用和错误详情，`q` 退出。脚本或外部 Agent 读取请看[分页 JSON 读取与上下文交接](/zh/guides/handoff-context-to-ai-agent/)。

## 导出带来源引用的上下文片段

只导出关键几轮对话，保留会话 URI、定位符和消息范围：

```sh
agent-dump 'codex://YOUR_SESSION_ID' --message 'REVISION:POSITION' --before 2 --after 3 --format markdown,json --output ./excerpts
```

导出的 Markdown 片段示例：

```markdown
# Session Context

- URI: `codex://019a7c2e`
- Locator: `rev1:3`
- Messages: 1–6 of 24
- Status: ok

## 3. user

上游偶发 504，auth timeout 要不要从 30s 提到 60s？
```

导出格式仍受各工具能力限制（例如 Cursor 支持 `json` 和 `print`，不支持 `markdown`）。没有命中时，可以减少关键词、放大 `--days`、去掉 `path:.`，并执行 `agent-dump providers` 检查数据源路径。

## 延伸阅读

- [每次跟 agent 聊完，你把最值钱的东西丢了](https://xingkaixin.me/posts/session-as-asset/) — 讨论如何把留在编码会话里的踩坑经验与工程判断沉淀成可搜索的决策记录。
- [Agent 让每个人都有了翻译器，但团队不再说同一种语言](https://xingkaixin.me/posts/agent-team-babel/) — 讨论为什么需要找回困在 session 里的设计取舍并沉淀下来。
