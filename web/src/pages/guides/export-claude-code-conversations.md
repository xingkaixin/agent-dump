---
layout: "../../layouts/Guide.astro"
locale: "en"
slug: "export-claude-code-conversations"
category: "export"
order: 2
updated: "2026-11-22"
title: "Export Claude Code Sessions to Markdown and JSON"
description: "Export local Claude Code sessions and conversations to Markdown or structured JSON with token stats and messages. Includes batch export and troubleshooting."
---

Agent Dump exports local Claude Code CLI sessions into Markdown or structured JSON files you can read, search, or parse outside the terminal. Use Markdown for project notes and reviews, and JSON for scripts or analytics. Exporting reads local session history without modifying original Claude Code records (this guide covers local Claude Code CLI sessions, not claude.ai web account exports).

## Install and find a conversation

Run these commands on the machine where you used Claude Code. If you have npm and Node.js 22 or later, install the CLI:

```sh
npm install -g @agent-dump/cli
agent-dump --list --days 30 --query 'provider:claude'
```

[Other installation options](/#install) include native binaries, Homebrew, Scoop, and uv. The list command selects sessions updated in the last 30 days, including older conversations you recently returned to. To filter by creation time instead, add `--time-field created`.

Look for the conversation title and working directory. Copy the full `claude://...` URI. To focus on your current project, run this from its directory:

```sh
agent-dump --list --days 30 --query 'provider:claude path:.'
```

## Export a readable record

Replace `YOUR_SESSION_ID` with a real ID from the list:

```sh
agent-dump 'claude://YOUR_SESSION_ID' --format markdown --output ./exports
```

The command prints the saved file path. Markdown files go under `./exports/claude/`, relative to your current directory. Open the printed path in your editor. This gives you a portable conversation record; it does not recreate the original agent process or resume its execution.

## Keep structured data too

Request both formats in the same command when you need a readable note and machine-readable data:

```sh
agent-dump 'claude://YOUR_SESSION_ID' --format json,markdown --output ./exports
```

`--format json` writes a normalized JSON file containing session metadata (`id`, `title`, `directory`, `version`, `time_created`, `time_updated`), aggregated `stats` (`total_input_tokens`, `total_output_tokens`, `total_cost`, `message_count`), and a `messages` array (`role`, `model`, `time_created`, `tokens`, `cost`, and structured `parts`). To export the untouched source transcript instead, use `--format raw` to copy the original `.raw.jsonl` file.

`--format json` writes an export file. It is different from `--json`, which produces structured standard output for supported query and reading modes. For scripts that need only part of a long conversation, use [bounded session reading](/guides/handoff-context-to-ai-agent/) instead of loading a full export.

## Export several conversations

For manual batch selection, open the interactive exporter:

```sh
agent-dump --interactive --query 'provider:claude' --format markdown --output ./exports
```

Choose the sessions in the terminal. This workflow requires an interactive terminal; use a URI for an unattended single-session export.

## When history is missing

Run `agent-dump --providers` to inspect source availability, and widen `--days` if the conversation is older. Confirm that you are using the same OS account and machine as Claude Code. A project filter matches the recorded working directory; remove `path:.` to check whether it excluded the session.

Agent Dump reads local saved history. It cannot fetch missing conversations from a remote account or recover deleted source files. Before sharing an export, review its contents for project information you do not intend to publish.

Next, [search across coding conversations](/guides/search-ai-coding-history/) or [save the export in Obsidian](/guides/save-ai-conversations-to-obsidian/).
