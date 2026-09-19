---
layout: ../../layouts/Guide.astro
locale: en
title: Export a Codex session to Markdown
description: Find a local Codex session, copy its URI, and export it to Markdown or JSON with Agent Dump. Includes installation, output paths, and missing-session checks.
---

Use Agent Dump to find a saved local Codex conversation and export it as a Markdown file. Install the CLI, list your sessions, then pass a real session URI to the export command. The source session stays unchanged; the exported file can be opened in your editor or notes app.

## 1. Install Agent Dump

If you already have npm and Node.js 22 or later:

```sh
npm install -g @agent-dump/cli
agent-dump --version
```

If you use uv, run `uv tool install agent-dump` instead. See [all installation options](/#install).

Run the following commands on the machine and under the user account where your Codex sessions are stored. Agent Dump reads local records; it does not fetch conversations from your OpenAI account.

## 2. Find the session URI

List Codex sessions from the last 30 days:

```sh
agent-dump --list -days 30 -query "provider:codex"
```

Use the title and working directory to identify the conversation. Copy the full `codex://…` URI from its list entry. Both `codex://<session-id>` and `codex://threads/<session-id>` are supported.

The default list window is seven days; `-days 30` widens it. Listing sessions does not export files.

## 3. Export to Markdown

Replace `YOUR_SESSION_ID` below with the actual ID, or replace the entire quoted URI with the one you copied:

```sh
agent-dump "codex://YOUR_SESSION_ID" --format markdown --output ./exports
```

`YOUR_SESSION_ID` is a placeholder, not an existing session. The command prints the exported file path. With this output directory, a Codex Markdown export is written to `./exports/codex/<session-id>.md`, relative to the directory where you ran the command.

## 4. Open the exported file

Open the printed `.md` path in your editor or Markdown notes app to read the conversation. Without `--output`, Markdown exports go to `./sessions/codex/<session-id>.md`.

For structured processing, export JSON instead, or request both formats in one command:

```sh
agent-dump "codex://YOUR_SESSION_ID" --format json,markdown --output ./exports
```

These list and export commands operate locally and do not require an AI API key. Exporting creates a readable record; it does not restore a running agent, its environment, or its execution state.

## If the session is missing

- Widen the date window, for example `-days 90`, if the session is older.
- Run `agent-dump --providers` to check whether the Codex source root is available without scanning sessions.
- Check the user account and `CODEX_HOME` environment variable. Codex discovery checks `CODEX_HOME`, then `~/.codex`, then the development fallback `data/codex`. A custom `CODEX_HOME` should point to the Codex home, not an individual session file.
- Copy the complete URI from a fresh listing. Do not run the example placeholder unchanged.
- If the source records exist only on another machine, run the export there. Agent Dump cannot recover deleted or unavailable source records.

For more formats and filtering options, see the [CLI parameter reference](https://github.com/xingkaixin/agent-dump#full-parameter-reference). To export conversations from other supported tools, start with the [Agent Dump overview](/#capabilities).
