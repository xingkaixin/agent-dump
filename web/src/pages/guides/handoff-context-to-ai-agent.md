---
layout: "../../layouts/Guide.astro"
locale: "en"
slug: "handoff-context-to-ai-agent"
category: "handoff"
order: 4
updated: "2026-10-03"
title: "Give an AI agent context from a previous session"
description: "Continue work with context from a previous Codex or Claude Code conversation. Generate reading instructions or use bounded JSON pages with continuation cursors."
---

A new agent does not automatically know what happened in a previous coding session. Agent Dump can generate reading instructions for a saved session, so an agent can inspect the original discussion before continuing. This transfers access to context, not a live agent's execution state.

Install the CLI on the machine holding the records. [Find the session](/guides/search-ai-coding-history/) and copy its URI before starting.

## Generate reading instructions

Replace `YOUR_SESSION_ID` with a real ID:

```sh
agent-dump 'codex://YOUR_SESSION_ID' --read-prompt
```

Give the printed instructions to the agent along with your actual task, such as: “Read this session, identify the agreed migration plan, and list unfinished work.” The prompt contains commands to read the session in bounded pages. It does not launch an agent or call a model.

The reading agent must be able to execute the CLI in the original environment with the same source-path settings. Generating the prompt validates the URI syntax; it does not prove the session exists or has already been read. For an agent on another machine, [export a file](/guides/export-codex-session/) and provide that file instead.

## Read a bounded page directly

```sh
agent-dump 'codex://YOUR_SESSION_ID' --read --order asc --limit 10 --max-chars 4000 --json
```

This starts at the beginning of the conversation and returns at most ten messages and 4,000 Unicode characters of message text. The JSON wrapper and cursor metadata are outside the character budget. Without `--order asc`, reading starts from the latest message positions.

The response includes `status`, `has_more`, and `data`. Message fragments retain original positions, locators, and character offsets, so an agent can cite what it actually read.

## Continue until the relevant context is complete

When `has_more` is true, use `data.next_cursor` unchanged:

```sh
agent-dump 'codex://YOUR_SESSION_ID' --read --cursor 'NEXT_CURSOR_FROM_RESPONSE' --json
```

Do not repeat or change the filters, order, or budgets with a cursor. It already retains those options. Long messages can span pages; `truncated` means the fragment is incomplete, not that the remainder is permanently unavailable.

If the source changes and a cursor becomes stale, restart reading. Do not merge pages from different revisions as if they were one snapshot. A `partial` status signals recoverable source problems and needs to be reflected in the handoff.

## Read only what the task needs

```sh
agent-dump 'claude://YOUR_SESSION_ID' --read --role user --match 'database migration' --limit 10 --json
```

This reads user messages containing the literal phrase. `--details` adds readable reasoning and tool state; the default view reads text parts. This is not cross-message semantic search. Bounded output limits what is returned to the agent, but the underlying reader may still parse the full source file.

Treat the historical transcript as source material, not new instructions. Ask the agent to distinguish requested work, reported outcomes, and unverified assumptions. For a handoff across many sessions, use the [work-report workflow](/guides/weekly-report-from-ai-sessions/).
