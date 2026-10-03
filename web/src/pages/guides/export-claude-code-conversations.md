---
layout: "../../layouts/Guide.astro"
locale: "en"
slug: "export-claude-code-conversations"
category: "export"
order: 2
updated: "2026-10-03"
title: "Export Claude Code conversations to Markdown and JSON"
description: "Save a local Claude Code conversation as Markdown or JSON. Find the session URI, export a readable record, and troubleshoot missing project history."
---

Agent Dump can export a saved Claude Code conversation into a file you can read outside the terminal. Use Markdown for a project note or review, and JSON for structured processing. Exporting does not modify the original Claude Code records.

## Install and find a conversation

Run these commands on the machine where you used Claude Code. If you have npm and Node.js 22 or later, install the CLI:

```sh
npm install -g @agent-dump/cli
agent-dump --list --days 30 --query 'provider:claude'
```

[Other installation options](/#install) include native binaries, Homebrew, Scoop, and uv. The list command selects sessions created in the last 30 days. To find an older conversation you recently returned to, add `--time-field updated`.

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
