---
layout: "../../layouts/Guide.astro"
locale: "en"
slug: "export-codex-session"
category: "export"
order: 1
updated: "2026-11-27"
title: "Export or Copy Codex Sessions to Markdown & JSON"
description: "Export or copy local OpenAI Codex CLI sessions from ~/.codex to Markdown, JSON, or clipboard in one command. Read-only, handles archived rollouts."
faq:
  - question: "Can I copy a Codex conversation as Markdown?"
    answer: "Yes. Export the session with agent-dump export 'codex://YOUR_SESSION_ID' --format markdown, open the printed .md file, or print directly to stdout and pipe to your clipboard (for example pbcopy on macOS)."
  - question: "Where does Codex CLI store local session files?"
    answer: "Codex CLI stores rollout-*.jsonl and compressed rollout-*.jsonl.zst transcripts under $CODEX_HOME/sessions and $CODEX_HOME/archived_sessions (defaulting to ~/.codex). Agent Dump reads both active and archived sessions in read-only mode."
  - question: "Does exporting include Codex subagent threads?"
    answer: "Subagent rollouts are listed as separate sessions. When a parent session started or referenced a subagent whose completion reply was not recorded in the parent, Agent Dump merges that subagent's final reply into the parent export."
---

Use Agent Dump to export local OpenAI Codex CLI sessions to Markdown, structured JSON, or raw JSONL, or pipe a transcript directly to your clipboard. Everything runs locally in read-only mode—no OpenAI API key is required and your `~/.codex` files stay untouched.

```sh
# Quick start: list Codex sessions, then export one to Markdown
npx @agent-dump/cli list --days 30 --query 'provider:codex'
npx @agent-dump/cli export 'codex://YOUR_SESSION_ID' --format markdown --output ./exports
```

## 1. Install Agent Dump

Run `brew install xingkaixin/tap/agent-dump` to install the native CLI, or run directly without installing via `npx @agent-dump/cli list --days 30 --query 'provider:codex'`:

```sh
# macOS / Linux (Homebrew)
brew install xingkaixin/tap/agent-dump

# macOS / Linux (shell installer)
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh

# Or run without installing (Node.js 22+)
npx @agent-dump/cli list --days 30 --query 'provider:codex'
```

See [all installation options](/#install) for Scoop (Windows), `uv`, `npm`, and `bun`. Run commands on the machine and OS user account where your Codex sessions are stored.

## 2. Find the session URI

Run `agent-dump list --days 30 --query 'provider:codex'` to list active and archived Codex sessions from the last 30 days and copy a `codex://` URI:

```sh
agent-dump list --days 30 --query 'provider:codex'
```

Use the title and working directory to find your conversation, then copy its `codex://…` URI. Both `codex://<session-id>` and `codex://threads/<session-id>` are accepted. Add `path:.` inside `--query` to limit results to the current project.

The default window is 7 days; `--days 30` widens it, and `--since` / `--until` selects an exact date range.

## 3. Export to Markdown

Run `agent-dump export 'codex://YOUR_SESSION_ID' --format markdown --output ./exports` to save a Markdown file, or pipe `agent-dump 'codex://YOUR_SESSION_ID' | pbcopy` to copy a Codex session as Markdown:

```sh
agent-dump export 'codex://YOUR_SESSION_ID' --format markdown --output ./exports
```

Replace `YOUR_SESSION_ID` with a real ID from the list. With `--output ./exports`, Agent Dump writes `./exports/codex/<session-id>.md` and prints the exact path. Without `--output`, files go under `./sessions/codex/`.

An exported Markdown transcript looks like this:

```markdown
# Session Dump

- URI: `codex://019a7c2e`

## 1. User

Upstream returns 504 now and then. Raise auth timeout from 30s to 60s?

## 2. Assistant

Not yet. Logs show timeouts cluster around token refresh. Reuse the HTTP pool and trace upstream latency first.
```

Need to copy a Codex session straight into your clipboard as Markdown? Print the bare URI and pipe it:

```sh
# macOS
agent-dump 'codex://YOUR_SESSION_ID' | pbcopy

# Linux (Wayland)
agent-dump 'codex://YOUR_SESSION_ID' | wl-copy
```

## 4. Export JSON, raw JSONL, or batch export

Run `agent-dump export 'codex://YOUR_SESSION_ID' --format json,markdown --output ./exports` to export structured JSON (with token totals and message parts) alongside Markdown in one command:

```sh
agent-dump export 'codex://YOUR_SESSION_ID' --format json,markdown --output ./exports
```

Pass `--format raw` to export the underlying JSONL (compressed `.jsonl.zst` rollouts are automatically decompressed to `.raw.jsonl`). To preview and batch-export multiple sessions interactively:

```sh
agent-dump browse --days 30 --query 'provider:codex'
```

Press `Space` to select multiple sessions and `e` to export them together. Exporting produces a portable transcript; it does not restore a running Codex process or its execution state.

## If the session is missing

- Widen the lookback window with `--days 90`, or filter explicitly with `--since` and `--until`.
- Run `agent-dump providers` to verify the Codex root path without scanning sessions.
- Check `CODEX_HOME`. Agent Dump checks `CODEX_HOME`, then `~/.codex` (`sessions/` and `archived_sessions/`). Point `CODEX_HOME` to the Codex home directory, not a single rollout file.
- Make sure you replaced `YOUR_SESSION_ID` with a real URI from `agent-dump list`.

For a notes workflow, see [save AI conversations to Obsidian](/guides/save-ai-conversations-to-obsidian/). To search across tools or export another CLI, see [search AI coding history](/guides/search-ai-coding-history/) and [export Claude Code conversations](/guides/export-claude-code-conversations/).
