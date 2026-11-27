---
layout: "../../layouts/Guide.astro"
locale: "en"
slug: "export-cherry-studio-conversations"
category: "export"
order: 6
updated: "2026-11-27"
title: "Export Cherry Studio 2.x Chats & Agent Sessions to Markdown"
description: "Export local Cherry Studio 2.x chats (topic-*) and agent sessions (session-*) from cherrystudio.sqlite to Markdown or JSON. Read-only CLI, no API key required."
faq:
  - question: "Where does Cherry Studio 2.x store its local database?"
    answer: "Cherry Studio 2.x stores conversations in Data/cherrystudio.sqlite under ~/Library/Application Support/CherryStudio on macOS, %APPDATA%\\CherryStudio on Windows, or ~/.config/CherryStudio on Linux, or paths configured in ~/.cherrystudio/boot-config.json."
  - question: "Does Agent Dump support Cherry Studio 1.x IndexedDB data?"
    answer: "No. Agent Dump reads Cherry Studio 2.x SQLite databases (including history migrated into 2.x). Direct reads of 1.x IndexedDB/Redux storage and --format raw export are unsupported."
  - question: "How are multi-model or branched replies handled?"
    answer: "For ordinary chats (cherry://topic-<id>), Agent Dump exports only the active root-to-leaf path, excluding parallel model replies and inactive branches. Agent sessions (cherry://session-<id>) are read chronologically with their workspace directory."
---

Agent Dump reads Cherry Studio 2.x's local SQLite database (`cherrystudio.sqlite`) in read-only mode, letting you search, browse, and export both ordinary chats and agent sessions to Markdown or structured JSON.

## Install or run without installing

```sh
# macOS / Linux (Homebrew)
brew install xingkaixin/tap/agent-dump

# macOS / Linux (shell installer)
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh

# Or run immediately with npx (Node.js 22+)
npx @agent-dump/cli list --days 30 --query 'provider:cherry'
```

See [all installation options](/#install) for Windows Scoop, `uv`, and `npm`.

## List Cherry Studio chats and agent sessions

```sh
agent-dump list --days 30 --query 'provider:cherry'
```

Cherry Studio uses two URI forms:

- `cherry://topic-<id>` — ordinary chats (exports the active root-to-leaf conversation path; no working directory).
- `cherry://session-<id>` — agent sessions (read chronologically, with the agent workspace as working directory so `path:.` works for agent sessions).

## Export to Markdown or JSON

Replace `YOUR_ID` with a real `topic-<id>` or `session-<id>` from the list:

```sh
# Export Markdown
agent-dump export 'cherry://topic-YOUR_ID' --format markdown --output ./exports

# Export both Markdown and structured JSON
agent-dump export 'cherry://session-YOUR_ID' --format json,markdown --output ./exports

# Browse and batch-export interactively
agent-dump browse --days 30 --query 'provider:cherry'
```

Files are written to `./exports/cherry/<id>.md` and `.json`. Cherry Studio supports `markdown`, `json`, and `print` (not `raw`). Text, reasoning, tool calls/results, code, and translations are normalized; JSON also preserves file references and per-currency recorded costs.

## Portable installs & troubleshooting

Agent Dump looks up Cherry Studio in this order:

1. `CHERRYSTUDIO_USER_DATA_DIR` or `CHERRY_STUDIO_USER_DATA_DIR` → `Data/cherrystudio.sqlite`
2. Directories listed in `~/.cherrystudio/boot-config.json`
3. Platform defaults: macOS `~/Library/Application Support/CherryStudio`, Windows `%APPDATA%\CherryStudio`, Linux `${XDG_CONFIG_HOME:-~/.config}/CherryStudio`

If you use a portable or dev installation, set `CHERRYSTUDIO_USER_DATA_DIR` and run `agent-dump providers` to confirm the active database. Deleted chats and messages are automatically excluded.

Next, [save exported Markdown to Obsidian](/guides/save-ai-conversations-to-obsidian/) or [search across all local AI tools](/guides/search-ai-coding-history/).
