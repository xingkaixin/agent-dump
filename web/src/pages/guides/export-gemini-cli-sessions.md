---
layout: "../../layouts/Guide.astro"
locale: "en"
slug: "export-gemini-cli-sessions"
category: "export"
order: 4
updated: "2026-11-27"
title: "Export Gemini CLI Sessions to Markdown & JSON"
description: "Export local Google Gemini CLI chats and subagent transcripts from ~/.gemini/tmp to Markdown, JSON, or raw JSONL. Supports JSONL replay, read-only, no API key."
faq:
  - question: "Where does Gemini CLI store local chat sessions?"
    answer: "Gemini CLI stores chats under ~/.gemini/tmp/<project>/chats/*.jsonl (and legacy *.json), with subagent chats inside chats/<parent-session-id>/. Set GEMINI_CLI_HOME to the parent directory containing .gemini if you use a custom home."
  - question: "Does Agent Dump handle Gemini CLI rewind and JSONL patches?"
    answer: "Yes. Agent Dump replays JSONL records in order—including $set, $patch, and $rewindTo updates—so exported Markdown and JSON match the actual conversation state. When a legacy .json chat was resumed as .jsonl, only the .jsonl version is read."
  - question: "Are thought summaries and token counts preserved?"
    answer: "Yes. Thought summaries are normalized into reasoning parts, tool calls are paired with their functionResponse results, input tokens include cached and tool-use prompt tokens, and output totals include thinking tokens."
---

Agent Dump reads local Google Gemini CLI sessions directly from `~/.gemini/tmp` and exports them to Markdown, structured JSON, or raw source files. Everything stays local and read-only—no Google API key is needed.

## Install or run without installing

```sh
# macOS / Linux (Homebrew)
brew install xingkaixin/tap/agent-dump

# macOS / Linux (shell installer)
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh

# Or run immediately with npx (Node.js 22+)
npx @agent-dump/cli list --days 30 --query 'provider:gemini-cli'
```

See [all installation options](/#install) for Scoop (Windows), `uv`, and `npm`.

## List Gemini CLI sessions

List recent Gemini CLI sessions, or scope to your current project directory:

```sh
agent-dump list --days 30 --query 'provider:gemini-cli'
agent-dump list --days 30 --query 'provider:gemini-cli path:.'
```

Working directories are resolved from `tmp/<project>/.project_root`. Subagent chats under `chats/<parent-session-id>/` appear as separate `gemini-cli://<session-id>` entries.

## Export to Markdown, JSON, or raw

Replace `YOUR_SESSION_ID` with an ID from the list:

```sh
# Export clean Markdown
agent-dump export 'gemini-cli://YOUR_SESSION_ID' --format markdown --output ./exports

# Export both Markdown and structured JSON
agent-dump export 'gemini-cli://YOUR_SESSION_ID' --format json,markdown --output ./exports

# Or browse and batch-export interactively
agent-dump browse --days 30 --query 'provider:gemini-cli'
```

Files are written under `./exports/gemini-cli/<session-id>.md` and `.json`. Pass `--format raw` if you need the original underlying chat file copied untouched.

```markdown
# Session Dump

- URI: `gemini-cli://3f9a2c41`

## 1. User

Why did the SQLite migration fail when re-running locally?

## 2. Assistant

The migration script creates the index without IF NOT EXISTS. Wrap it in a conditional check so repeated runs stay idempotent.
```

## Custom paths & troubleshooting

- Agent Dump checks `GEMINI_CLI_HOME/.gemini/tmp`, then `~/.gemini/tmp`. Note that `GEMINI_CLI_HOME` must point to the directory **containing** `.gemini`, not `.gemini/tmp` itself.
- Run `agent-dump providers` to confirm the resolved Gemini CLI directory.
- Files without a `sessionId` or chats with zero messages are skipped automatically.

Next, [search across Gemini CLI, Claude Code, and Codex](/guides/search-ai-coding-history/) or [save transcripts to Obsidian](/guides/save-ai-conversations-to-obsidian/).
