---
layout: "../../../layouts/Guide.astro"
locale: "zh"
slug: "weekly-report-from-ai-sessions"
category: "reports"
order: 5
updated: "2026-10-05"
title: "从 AI 编码会话生成日报或周报"
description: "将保存的 AI 编码对话整理成工作报告。先确认会话范围，再选择内置 AI 汇总或提示词交接，最后检查来源覆盖和未完成项。"
---

Agent Dump 可以把已保存的编码对话整理成工作报告，归纳用户要做什么、关键决策，以及 Agent 明确报告的结果。它适合准备日报或周报，但不会独立验证改动是否真的发布，分享前仍应核对重要结论。

先[安装 CLI](/zh/#install)，确认目标会话保存在当前机器上。

## 先预览报告范围

使用明确日期，便于重复核对。下面日期只是示例，请替换为实际报告周期：

```sh
agent-dump --collect --since 2026-09-28 --until 2026-10-02 --query 'provider:codex,claude path:.' --dry-run
```

从项目工作目录中运行。日期包含首尾两天，按可见文本段的实际本地日期筛选。跨数天的长会话会拆成每日单元，旧会话中发生在本周的内容也会纳入，本周之外的文本不算作本期工作。没有可靠时间的文本直接排除，不借用会话日期。需要跨项目报告时，移除 `path:.`。

在请求汇总前检查候选来源和诊断。缺失或读失败的会话是覆盖缺口，不能当作没有工作发生。

## 使用配置好的 AI 服务汇总

通过 `agent-dump --config` 配置 `[ai]`，具体字段见[配置参考](https://github.com/xingkaixin/agent-dump#collect-configuration-file)。然后执行：

```sh
agent-dump --collect --since 2026-09-28 --until 2026-10-02 --query 'provider:codex,claude path:.' --save ./reports/weekly.md
```

与本地搜索和导出不同，AI collect 会将选中的对话内容发送给配置的模型服务。先确认来源范围，再选择适合当前项目的服务。

Collect 分块处理符合条件的 user/assistant 可见文本，排除 system/developer 消息、工具结果、推理和计划。没有有效可见文本的会话会被忽略。默认 PM 报告按日期和已知工作目录汇总；增加 `--collect-mode insight` 可使用另一种分析模式。内置报告指令目前生成中文报告。

## 交给现有 Agent 处理

如果不想单独配置 AI API Key，可以生成完整的交接提示词：

```sh
agent-dump --collect --emit-prompt --since 2026-09-28 --until 2026-10-02 --query 'provider:codex,claude path:.' --save ./reports/weekly.md
```

这条命令会打印包含候选清单和读取说明的提示词。`--save` 指定最终报告的位置，不会保存提示词，也不会自动运行报告任务。将完整提示词交给能够在原环境执行命令的 Agent，并明确要求它生成报告。

Agent 需要先校验清单，再完整读取符合条件的对话文本，并报告缺失来源。提示词为空且退出码为 0，表示没有候选会话，不应继续生成报告。

## 核对最终结果

打开 `./reports/weekly.md`，检查日期范围、来源归属、遗漏会话和不完整标记。完整覆盖输入不意味着摘要保留了每个细节。重要结论可以通过[搜索和消息上下文](/zh/guides/search-ai-coding-history/)回到原始对话核对。

如果需要长期保存项目材料，可以继续阅读[将对话保存到 Obsidian](/zh/guides/save-ai-conversations-to-obsidian/)。
