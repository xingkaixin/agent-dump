---
name: agent-dump
description: 使用 agent-dump 命令行导出、列出、筛选、按 URI 直读 AI coding 会话。Use this skill when users ask to export AI assistant sessions, list sessions, filter by keyword or agent scope, interactively select sessions, or dump a single session by URI with json/md/print.
---

# Agent Dump

使用本技能时，始终通过 `agent-dump` CLI 完成会话查询与导出，不改动业务源码。

## 执行工作流

1. 识别任务模式
- 用户给了 `opencode://...`、`codex://...`、`kimi://...`、`claude://...` 这类 URI：使用 URI 模式。
- 用户要“先看列表/筛选”：使用 `--list` 模式。
- 用户要“交互式勾选后导出”：使用 `--interactive` 模式。
- 用户只给 `-days` 或 `-query` 且未指定 `--interactive`：按列表模式处理（CLI 会自动启用 `--list`）。

2. 组装命令
- 优先复用 [references/cli-recipes.md](references/cli-recipes.md) 的模板命令。
- 保留用户显式给出的 `--output`、`--format`、`--lang`、`-days`、`-query` 参数。

3. 执行并检查退出状态
- 退出码 `0` 视为成功。
- 非 `0` 视为失败，提炼关键报错并给出下一步修复建议。

4. 输出结果摘要
- 说明执行模式（interactive/list/uri）。
- 说明会话结果（命中数量、是否导出成功）。
- 说明输出位置（若发生文件导出）。
- 说明失败原因（若失败）。

## 强约束

- 在 `--interactive` 模式下，不要使用 `--format print`。
- 在 `--list` 模式下，`--format` 和 `--output` 会被忽略，需在结果里提醒。
- URI 模式默认输出为 `print`；非 URI 模式默认输出为 `json`。
- 仅使用当前 CLI 已支持的 URI 协议：`opencode`、`codex`、`kimi`、`claude`（其中 `claude` 对应 Claude Code）。

## 参数与错误参考

读取 [references/cli-recipes.md](references/cli-recipes.md) 获取完整命令模板、行为矩阵、查询语法和错误处理策略。
