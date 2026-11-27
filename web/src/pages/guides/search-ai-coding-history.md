---
layout: "../../layouts/Guide.astro"
locale: "en"
slug: "search-ai-coding-history"
category: "search"
order: 7
updated: "2026-11-27"
title: "Search Claude Code, Codex & AI Coding History Locally"
description: "Full-text search local Claude Code, Codex, Cursor, and Gemini CLI sessions with SQLite FTS5. Trace past AI code fixes, filter by project, and export cited excerpts."
faq:
  - question: "Does searching AI coding history require an API key or send data to the cloud?"
    answer: "No. Agent Dump builds a local SQLite FTS5 index under its own cache directory and runs full-text search completely offline. No API key is needed and original session files are never modified."
  - question: "What parts of a session does Agent Dump search?"
    answer: "Full-text search covers normalized session titles, user and assistant messages, reasoning blocks, and tool state including tool errors. That makes it easy to trace failed commands or specific error messages across tools."
  - question: "Can I search only sessions from a specific project or date range?"
    answer: "Yes. Pass path:. inside --query from your project root to match its working directory, filter tools with provider:claude,codex, and narrow dates with --days, --since, or --until."
---

When you remember fixing a bug or making a design decision with an AI assistant—but cannot remember whether it happened in Claude Code, Codex, Cursor, or Gemini CLI—search all of your local transcripts at once with Agent Dump.

Install via `brew install xingkaixin/tap/agent-dump` or [other install methods](/#install). Search runs locally using a SQLite FTS5 index with no API key required.

## Search across all local AI sessions

Run a literal full-text search over the last 90 days:

```sh
agent-dump search 'auth timeout' --days 90
```

Every distinct word must occur in the session, across titles, visible dialogue, reasoning, or tool errors. By default the window covers the last 7 days by latest update time. Use `--since` and `--until` for an exact local date range, or `--time-field created` to filter by creation date:

```sh
agent-dump search 'auth timeout' --since 2026-11-01 --until 2026-11-27
```

## Filter by project or AI coding tool

Run from your repository root to limit hits to the current working directory and specific tools:

```sh
agent-dump search 'database migration' --days 90 --query 'provider:claude,codex path:.'
```

Put your search keywords in `search` (so results are ranked with evidence snippets) and put scope filters (`provider:`, `path:`, `role:`, `limit:`) in `--query`.

## Locate matching messages and trace decisions

Add `--locate --json` to get machine-readable message locators for every hit:

```sh
agent-dump search 'database migration' --days 90 --locate --json
```

Pass the returned URI and `REVISION:POSITION` locator back into Agent Dump to inspect surrounding turns:

```sh
agent-dump 'codex://YOUR_SESSION_ID' --message 'REVISION:POSITION' --before 2 --after 3
```

Because a locator is bound to a source revision, re-run `search --locate` if the session has new messages.

## Browse and search interactively in the terminal

Open the terminal reader pre-filtered to your project:

```sh
agent-dump browse --days 90 --query 'provider:claude,codex path:.'
```

Press `Enter` to open a conversation, `/` to search inside it, `n` / `N` to jump between hits, `t` to expand tool calls and errors, and `q` to quit. For scripts and AI agents, use [bounded JSON reading](/guides/handoff-context-to-ai-agent/).

## Export a cited context excerpt

Save only the relevant turns—with session URI and message range preserved—to Markdown or JSON:

```sh
agent-dump 'codex://YOUR_SESSION_ID' --message 'REVISION:POSITION' --before 2 --after 3 --format markdown,json --output ./excerpts
```

An exported Markdown excerpt looks like this:

```markdown
# Session Context

- URI: `codex://019a7c2e`
- Locator: `rev1:3`
- Messages: 1–6 of 24
- Status: ok

## 3. user

Upstream returns 504 now and then. Raise auth timeout from 30s to 60s?
```

Provider format rules still apply (for example, Cursor supports `json` and `print`, not `markdown`). If a query returns nothing, shorten the keywords, widen `--days`, remove `path:.`, and run `agent-dump providers` to verify discovered sources.
