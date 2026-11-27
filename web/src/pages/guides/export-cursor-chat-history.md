---
layout: "../../layouts/Guide.astro"
locale: "en"
slug: "export-cursor-chat-history"
category: "export"
order: 3
updated: "2026-11-27"
title: "Export Cursor Chat & Composer History from state.vscdb"
description: "Read, search, and export local Cursor composer chat history from globalStorage/state.vscdb to JSON or printable transcript. Read-only CLI, no API key needed."
faq:
  - question: "Where does Cursor store local chat history?"
    answer: "Cursor stores composer conversations in globalStorage/state.vscdb under ~/Library/Application Support/Cursor/User on macOS, %APPDATA%\\Cursor\\User on Windows, or ~/.config/Cursor/User on Linux. Workspace paths come from workspaceStorage/*/workspace.json."
  - question: "Does Agent Dump support Markdown export for Cursor?"
    answer: "Cursor supports --format json and --format print, not --format markdown or --format raw. Because bare URI printing writes a readable Markdown-style transcript to stdout, you can redirect agent-dump 'cursor://YOUR_COMPOSER_ID' > session.md or export JSON for scripts."
  - question: "Will reading state.vscdb corrupt my running Cursor workspace?"
    answer: "No. Agent Dump opens Cursor's SQLite database strictly in read-only mode and never writes into Cursor's user data directory. Export files are written only to the output path you specify."
---

Cursor keeps local composer and chat records inside an internal SQLite database (`state.vscdb`), making them hard to search or archive outside the editor. Agent Dump reads Cursor's database in read-only mode so you can list, search, browse, print, and export sessions as structured JSON without touching your IDE data.

## Install or run without installing

```sh
# macOS / Linux (Homebrew)
brew install xingkaixin/tap/agent-dump

# macOS / Linux (shell installer)
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh

# Or try directly without installing (Node.js 22+)
npx @agent-dump/cli list --days 30 --query 'provider:cursor'
```

See [all installation options](/#install) for Windows Scoop, `uv`, and `npm`.

## Find your Cursor composer sessions

List Cursor sessions from the last 30 days, or filter to the current workspace:

```sh
agent-dump list --days 30 --query 'provider:cursor'
agent-dump list --days 30 --query 'provider:cursor path:.'
```

Each entry prints its title, matched workspace directory, and `cursor://<composer-id>` URI (legacy `cursor://<request-id>` URIs also resolve to the same session).

## Export Cursor chat history to JSON

Replace `YOUR_COMPOSER_ID` with a real ID from the list:

```sh
agent-dump export 'cursor://YOUR_COMPOSER_ID' --format json --output ./exports
```

Agent Dump writes normalized JSON to `./exports/cursor/<composer-id>.json` with session metadata, message parts, and token stats when recorded:

```json
{
  "id": "8821c4e0",
  "title": "Refactor auth middleware",
  "directory": "/Users/dev/app",
  "stats": {
    "message_count": 12,
    "total_input_tokens": 18420,
    "total_output_tokens": 2150
  },
  "messages": [
    {
      "role": "user",
      "parts": [{ "type": "text", "text": "Why does token refresh loop on 401?" }]
    }
  ]
}
```

## Print a readable transcript or browse in the terminal

Cursor supports `json` and `print` formats (requesting `--format markdown` or `--format raw` returns a capability diagnostic). To save a readable transcript directly or copy it to your clipboard, print the bare URI:

```sh
# Save readable transcript to a file
agent-dump 'cursor://YOUR_COMPOSER_ID' > ./exports/cursor-chat.md

# Or browse and search Cursor sessions interactively
agent-dump browse --days 30 --query 'provider:cursor'
```

## Custom Cursor paths & troubleshooting

Agent Dump resolves Cursor data from `CURSOR_DATA_PATH/globalStorage/state.vscdb`, falling back to the platform `User` directory:

- **macOS**: `~/Library/Application Support/Cursor/User`
- **Windows**: `%APPDATA%\Cursor\User`
- **Linux**: `${XDG_CONFIG_HOME:-~/.config}/Cursor/User`

If no sessions appear, run `agent-dump providers` to verify the detected database path, widen `--days 90`, or remove `path:.` (working directories come from `workspaceStorage/*/workspace.json` entries that reference the composer).

Next, [search across Cursor, Codex, and Claude Code](/guides/search-ai-coding-history/) or [hand off context to another AI agent](/guides/handoff-context-to-ai-agent/).
