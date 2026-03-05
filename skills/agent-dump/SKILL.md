---
name: agent-dump
description: 使用 agent-dump 命令行导出、列出、筛选、按 URI 直读 AI coding 会话，并支持 collect/config/summary 能力。Use this skill when users ask to export AI assistant sessions, list sessions, filter by keyword or agent scope, interactively select sessions, dump a single session by URI, generate URI summary, run collect reports, or manage config.
---

# Agent Dump

使用本技能时，始终通过 `agent-dump` CLI 完成会话查询与导出，不改动业务源码。

## 安装与运行入口

按“尽量不改环境”的顺序选择入口：

1. 已存在本地命令时直接使用
- 适用于用户明确说已全局安装，或当前环境已确认存在 `agent-dump`。
- 示例：`agent-dump --help`

2. 免安装直跑
- 适用于只想临时运行一次，或用户明确说不想装 Python。
- 优先使用 `bunx @agent-dump/cli` 或 `npx @agent-dump/cli`。
- 示例：`bunx @agent-dump/cli --help`
- 示例：`npx @agent-dump/cli --help`

3. 持久安装
- 适用于用户明确要长期直接运行 `agent-dump`。
- 只在 skill 中说明支持全局安装；具体安装命令优先参考仓库 README，或在用户明确要求安装时再给出。

## 环境不确定时的处理规则

- 如果用户已经指定运行方式，直接遵循，不要替换成别的入口。
- 如果环境不明确，先做低成本检查，按以下顺序判断可用入口：`agent-dump`、`bunx`、`npx`、`uv` / `uvx`。
- 只要确认某个入口可用，就按该入口组装后续命令。
- 如果无法安全判断是否允许联网拉包、是否应做全局安装、或用户偏好 Python 体系还是 Node/Bun 体系，先向用户确认，不要自行假设。
- 默认偏好：已存在 `agent-dump` 时优先复用；只是临时执行一次时优先 `bunx @agent-dump/cli` 或 `npx @agent-dump/cli`；用户明确要长期直接运行 `agent-dump` 时再走安装路径。

## 执行工作流

1. 识别任务模式
- 用户给了 `opencode://...`、`codex://...`、`kimi://...`、`claude://...` 这类 URI：使用 URI 模式。
- 用户给了 `--collect`：使用 collect 模式（按时间范围收集并调用 AI 总结）。
- 用户给了 `--config view` 或 `--config edit`：使用 config 模式。
- 用户要“先看列表/筛选”：使用 `--list` 模式。
- 用户要“交互式勾选后导出”：使用 `--interactive` 模式。
- 用户只给 `-days` 或 `-query` 且未指定 `--interactive`：按列表模式处理（CLI 会自动启用 `--list`）。
- Codex URI 允许 `codex://threads/<session_id>` 变体，等价于 `codex://<session_id>`。

2. 组装命令
- 先确认命令前缀，使用以下等价入口之一：`agent-dump`、`bunx @agent-dump/cli`、`npx @agent-dump/cli`、必要时 `uv run agent-dump`。
- 优先复用 [references/cli-recipes.md](references/cli-recipes.md) 的模板命令。
- `references/cli-recipes.md` 负责详细命令模板、行为矩阵和错误处理；本 skill 只负责入口选择与环境判断规则。
- 保留用户显式给出的 `--output`、`--format`、`--lang`、`-days`、`-query`、`--summary`、`--collect`、`-since/-until`、`--config` 参数。

3. 执行并检查退出状态
- 退出码 `0` 视为成功。
- 非 `0` 视为失败，提炼关键报错并给出下一步修复建议。

4. 输出结果摘要
- 说明执行模式（interactive/list/uri/collect/config）。
- 说明会话结果（命中数量、是否导出成功）。
- 说明输出位置（若发生文件导出）。
- 说明失败原因（若失败）。

## 强约束

- 在 `--interactive` 模式下，不要使用 `--format print`。
- 在 `--list` 模式下，`--format` 和 `--output` 会被忽略，需在结果里提醒。
- `--format` 支持 `json,markdown,raw,print` 逗号组合，`md` 是 `markdown` 别名。
- URI 模式默认输出为 `print`，可组合 `print,json`；非 URI 模式默认输出为 `json`。
- `--summary` 仅支持 URI 模式，且 `--format` 必须包含 `json`；不满足条件时仅警告并继续主流程。
- `--collect` 不能与 URI、`--interactive`、`--list` 同时使用。
- 仅使用当前 CLI 已支持的 URI 协议：`opencode`、`codex`、`kimi`、`claude`（其中 `claude` 对应 Claude Code）。

## 参数与错误参考

读取 [references/cli-recipes.md](references/cli-recipes.md) 获取完整命令模板、行为矩阵、查询语法和错误处理策略。
