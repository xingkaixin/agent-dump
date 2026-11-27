---
layout: "../../layouts/Guide.astro"
locale: "en"
slug: "export-opencode-sessions"
category: "export"
order: 5
updated: "2026-11-27"
title: "Export OpenCode Sessions to Markdown & JSON (1.x & 2.x)"
description: "Export local OpenCode 1.x and 2.x SQLite sessions from opencode.db to Markdown or JSON. Supports custom OPENCODE_DB channels, read-only, no API key required."
faq:
  - question: "Does Agent Dump work with OpenCode 2.x?"
    answer: "Yes. Agent Dump reads both OpenCode 2.x session_v2/session_message tables and legacy SQLite tables. When both coexist for the same session ID, V2 wins; once OpenCode completes migration.v1-v2, only V2 is read so deleted sessions stay hidden."
  - question: "Where is OpenCode's database located and how do I select a channel DB?"
    answer: "By default Agent Dump reads opencode.db under $XDG_DATA_HOME/opencode or ~/.local/share/opencode (and legacy Windows AppData paths). Set OPENCODE_DB to a custom path or filename relative to that directory to target a specific channel database."
  - question: "What does --format raw output for OpenCode?"
    answer: "For SQLite-backed OpenCode sessions, --format raw writes a normalized .raw.json snapshot rather than an OpenCode re-import file. Use --format markdown for readable notes or --format json for structured scripts."
---

Agent Dump reads local OpenCode SQLite databases—covering both legacy schemas and OpenCode 2.x `session_v2`—in read-only mode. List, search, browse, and export conversations to Markdown or JSON without risking database locks or modifying `opencode.db`.

## Install or run without installing

```sh
# macOS / Linux (Homebrew)
brew install xingkaixin/tap/agent-dump

# macOS / Linux (shell installer)
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh

# Or run immediately with npx (Node.js 22+)
npx @agent-dump/cli list --days 30 --query 'provider:opencode'
```

See [all installation options](/#install) for Windows Scoop, `uv`, and `npm`.

## List OpenCode sessions

List sessions updated in the last 30 days, or narrow to the current repository:

```sh
agent-dump list --days 30 --query 'provider:opencode'
agent-dump list --days 30 --query 'provider:opencode path:.'
```

Both active and archived OpenCode sessions are listed with `opencode://<session-id>` URIs; sessions without visible messages are skipped.

## Export to Markdown or JSON

Replace `YOUR_SESSION_ID` with a real ID from the list:

```sh
# Export Markdown
agent-dump export 'opencode://YOUR_SESSION_ID' --format markdown --output ./exports

# Export Markdown and structured JSON together
agent-dump export 'opencode://YOUR_SESSION_ID' --format json,markdown --output ./exports

# Browse and batch-export in the terminal
agent-dump browse --days 30 --query 'provider:opencode'
```

Exported files are written under `./exports/opencode/<session-id>.md` and `.json`. Input token totals include cache reads and writes, and output totals include reasoning tokens.

```markdown
# Session Dump

- URI: `opencode://5c4b3a12`

## 1. User

Can we check if local auth timeout is shorter than the gateway idle window?

## 2. Assistant

Yes: client auth timeout is 30s while gateway refresh sits at 45s. Aligning both removes the spurious retries.
```

## Selecting a custom or channel database

If you run a custom build or channel database, pass `OPENCODE_DB`:

```sh
OPENCODE_DB=opencode-beta.db agent-dump list --days 30 --query 'provider:opencode'
```

Relative paths resolve under `$XDG_DATA_HOME/opencode` (or `~/.local/share/opencode`). An explicit missing `OPENCODE_DB` path reports an error instead of silently falling back to another database. Run `agent-dump providers` anytime to verify which database path is selected.

Next, [search across OpenCode, Codex, and Claude Code](/guides/search-ai-coding-history/) or [save conversations to Obsidian](/guides/save-ai-conversations-to-obsidian/).
