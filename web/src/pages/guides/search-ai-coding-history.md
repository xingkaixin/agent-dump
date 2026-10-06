---
layout: "../../layouts/Guide.astro"
locale: "en"
slug: "search-ai-coding-history"
category: "search"
order: 3
updated: "2026-10-06"
title: "Search AI coding history and find past decisions"
description: "Find a past fix or decision across Codex, Claude Code, and other local AI tools. Filter by project, locate matching messages, and read the surrounding context."
---

When you remember solving a problem but cannot remember which coding assistant you used, search your local conversation history with Agent Dump. You can narrow results to a project, inspect the matching messages, and keep a cited excerpt for the next task.

Install Agent Dump using [your preferred package manager](/#install). These examples run on the machine holding the source sessions. Searching works locally and does not require an AI API key.

## Search for the words you remember

```sh
agent-dump --search 'auth timeout' --days 90
```

Every distinct term must match the session, but terms can appear in different messages or corpus fields. This is literal full-text search, not semantic search. The corpus includes normalized titles, messages, reasoning, and tool state. FTS operators such as `AND` are not interpreted as query syntax.

The default date window is seven days. Increase `--days` for older work. To find recently active conversations regardless of when they began:

```sh
agent-dump --search 'auth timeout' --time-field updated --days 7
```

## Narrow to a project or tool

Run from your project's working directory:

```sh
agent-dump --search 'database migration' --days 90 --query 'provider:codex,claude path:.'
```

The `--query` option adds filters. Its keyword component matches like `--search`: every whitespace-separated term must occur. `--search` also ranks results and shows evidence, so keep the search terms in `--search` and the scope in `--query`.

## Locate the evidence

Add `--locate --json` to get message locations with machine-readable results:

```sh
agent-dump --search 'database migration' --days 90 --locate --json
```

Use a URI and message locator returned by this command. Replace both placeholders in the following example:

```sh
agent-dump 'codex://YOUR_SESSION_ID' --message 'REVISION:POSITION' --before 2 --after 3
```

This prints the matching message and nearby context. A session matched only by its title can have no message locations. A locator is tied to a source revision; if the conversation changes, rerun the search for fresh locations rather than reusing a stale one.

## Read in the terminal

For an interactive reader, use:

```sh
agent-dump --browse --days 90 --query 'provider:codex,claude path:.'
```

Select a session and press Enter. Use `/` to search within the current conversation, `n` and `N` to move between matches, and `t` to show tool details. Press `q` to close the reader. This requires a terminal; scripts should use [paged JSON reading](/guides/handoff-context-to-ai-agent/).

## Keep a small excerpt

```sh
agent-dump 'codex://YOUR_SESSION_ID' --message 'REVISION:POSITION' --before 2 --after 3 --format json,markdown --output ./excerpts
```

The exported excerpt keeps its session URI, locator, and message range. Check the reported output path and any diagnostics. The source transcript remains unchanged. Provider format restrictions still apply; Cursor supports JSON and print, but not Markdown.

If there are no results, shorten the terms, widen the date window, remove the project filter, and run `agent-dump --providers` to inspect source availability.
