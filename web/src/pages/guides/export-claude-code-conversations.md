---
layout: "../../layouts/Guide.astro"
locale: "en"
slug: "export-claude-code-conversations"
category: "export"
order: 2
updated: "2026-11-27"
title: "Export Claude Code Sessions to Markdown & JSON (Token Stats)"
description: "Export local Claude Code sessions from ~/.claude/projects to Markdown or JSON with input_tokens & output_tokens stats, plus --output-format json comparison."
faq:
  - question: "Where does Claude Code store local session transcripts?"
    answer: "Claude Code saves local session records as JSONL files under ~/.claude/projects/<project>/<session>.jsonl, with subagent transcripts under <session>/subagents/. If you use a custom directory, set CLAUDE_CONFIG_DIR before running Agent Dump."
  - question: "How is --format json different from Claude Code's --output-format json?"
    answer: "Claude Code's --output-format json prints a single-run stdout result object with session_id, total_cost_usd, and usage tokens. Agent Dump's --format json reads saved ~/.claude/projects JSONL files offline and exports normalized messages plus total_input_tokens and total_output_tokens. Local JSONL does not store USD cost, so stats.total_cost is 0."
  - question: "How is Agent Dump different from Claude Code's built-in /export or --resume?"
    answer: "Built-in /export only saves the active conversation one session at a time, and --resume reopens a session interactively. Agent Dump reads all historical sessions and subagents in read-only mode, supports full-text search, batch export, and normalized JSON with token stats across 19 tools."
  - question: "Does this export claude.ai web conversations?"
    answer: "No. Agent Dump reads local Claude Code CLI sessions stored on your machine. It does not connect to claude.ai web accounts or parse claude.ai conversations.json account export archives."
---

Agent Dump exports local Claude Code CLI sessions into clean Markdown or structured JSON files without modifying original records. Use Markdown for docs, PR notes, and Obsidian, or JSON for scripts and token audits. Everything runs locally with no API key required.

```sh
# List recent Claude Code sessions, then export one to JSON + Markdown
npx @agent-dump/cli list --days 30 --query 'provider:claude'
npx @agent-dump/cli export 'claude://YOUR_SESSION_ID' --format json,markdown --output ./exports
```

> This guide covers local **Claude Code CLI** sessions (`~/.claude/projects/`), not `claude.ai` web account exports.

## Install or run without installing

Install the native CLI (no Python or Node.js required), or run directly with `npx`:

```sh
# macOS / Linux (Homebrew)
brew install xingkaixin/tap/agent-dump

# macOS / Linux (shell installer)
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh

# Or try immediately without installing (Node.js 22+)
npx @agent-dump/cli list --days 30 --query 'provider:claude'
```

See [all installation options](/#install) for Scoop (Windows), `uv`, `npm`, and `bun`. Run commands on the machine and OS user account where you ran Claude Code.

## Find your Claude Code sessions

List sessions updated in the last 30 days, or scope to the current project directory:

```sh
agent-dump list --days 30 --query 'provider:claude'
agent-dump list --days 30 --query 'provider:claude path:.'
```

The list shows each session's title, working directory, and `claude://<session-id>` URI. Subagent transcripts under `<session>/subagents/` appear as separate sessions too. By default `--days` filters by latest activity time; add `--time-field created` (or `--since` / `--until`) to filter by creation date or an exact range.

## Export a session to Markdown

Replace `YOUR_SESSION_ID` with a real ID from the list:

```sh
agent-dump export 'claude://YOUR_SESSION_ID' --format markdown --output ./exports
```

The command prints the written path under `./exports/claudecode/<session-id>.md`. A Markdown export looks like this:

```markdown
# Session Dump

- URI: `claude://7f3c91ab`

## 1. User

Login retries pile up when the auth upstream stalls past 30s.

## 2. Assistant

Pass the request AbortSignal into the retry loop so canceled logins stop immediately after the timeout.
```

Exporting creates a portable, human-readable transcript. It does not recreate the original Claude Code process or resume its runtime state.

## Export structured JSON or raw JSONL

Request both Markdown and normalized JSON in one command:

```sh
agent-dump export 'claude://YOUR_SESSION_ID' --format json,markdown --output ./exports
```

`--format json` writes a normalized JSON file containing session metadata (`id`, `title`, `directory`, `version`, `time_created`, `time_updated`), aggregated `stats`, and structured `messages` with per-turn `tokens`:

```json
{
  "id": "7f3c91ab",
  "title": "Fix login timeout retry",
  "directory": "/Users/dev/project",
  "stats": {
    "message_count": 18,
    "total_input_tokens": 42180,
    "total_output_tokens": 3940,
    "total_cost": 0
  },
  "messages": [
    {
      "role": "assistant",
      "tokens": {
        "input_tokens": 1240,
        "output_tokens": 310,
        "cache_read_input_tokens": 8900,
        "cache_creation_input_tokens": 0
      },
      "parts": [{ "type": "text", "text": "Pass the request AbortSignal into the retry loop..." }]
    }
  ]
}
```

### Field comparison: `--output-format json` vs local JSONL vs Agent Dump

Claude Code's headless `--output-format json` prints a single-run result summary to stdout, whereas `~/.claude/projects/<project>/<session>.jsonl` stores the full multi-turn transcript on disk. Here is how their fields map to `agent-dump export --format json`:

| Field | Claude Code `--output-format json` | Local `~/.claude/projects/*.jsonl` | `agent-dump export --format json` |
| --- | --- | --- | --- |
| Session ID | `session_id` | `sessionId` | `id` |
| Input tokens | `usage.input_tokens` (+ cache) | `message.usage.input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens` | `stats.total_input_tokens` (includes cache input tokens) & `messages[].tokens` |
| Output tokens | `usage.output_tokens` | `message.usage.output_tokens` | `stats.total_output_tokens` & `messages[].tokens.output_tokens` |
| Cost (USD) | `total_cost_usd` | Not recorded in local JSONL | `stats.total_cost` (`0` for Claude Code) |
| Scope | One headless CLI run | Raw local transcript on disk | Normalized archived session + subagents |

To copy the untouched source file instead, pass `--format raw` (writes `.raw.jsonl`). Note that `--format json` exports an archived session file, which is different from Agent Dump's `--json` stdout flag for scripts. For reading part of a very long session, see [bounded session reading](/guides/handoff-context-to-ai-agent/).

## Batch export or browse in the terminal

To preview conversations and export multiple Claude Code sessions at once:

```sh
agent-dump browse --days 30 --query 'provider:claude'
```

Press `Space` to mark sessions and `e` to export the marked set. You can also run `agent-dump export --query 'provider:claude' --format markdown --output ./exports` to open the selector directly with your chosen format and output directory.

## Where Claude Code stores sessions & troubleshooting

Agent Dump checks `CLAUDE_CONFIG_DIR` first, then `~/.claude`. Within that directory it scans `projects/<project>/<session>.jsonl` and `<session>/subagents/`.

If a session is missing:

- Run `agent-dump providers` to confirm the detected Claude Code source path.
- Widen the window with `--days 90` or use `--since` / `--until`.
- Remove `path:.` if the session was started from a parent or different working directory.
- Sessions with no visible user or assistant messages are skipped automatically.

Next, [search across all AI coding sessions](/guides/search-ai-coding-history/) or [save exported conversations to Obsidian](/guides/save-ai-conversations-to-obsidian/).
