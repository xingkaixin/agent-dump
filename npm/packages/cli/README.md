# @agent-dump/cli

Native `agent-dump` binaries for `bunx` and `npx`.

The package downloads the matching native binary for the current platform during installation
and verifies it against the published checksum manifest before exposing `agent-dump`.

```bash
bunx @agent-dump/cli --help
npx @agent-dump/cli --help
```

Supported targets:

- `darwin-x64`
- `darwin-arm64`
- `linux-x64`
- `win32-x64`

## Installation

```bash
# Via bunx (no installation)
bunx @agent-dump/cli --help

# Via npx (no installation)
npx @agent-dump/cli --help

# Global install
npm install -g @agent-dump/cli
agent-dump --help
```

## Usage

### Interactive export

```bash
agent-dump --interactive
agent-dump --interactive -days 3
```

### List sessions

```bash
agent-dump --list
agent-dump --list -days 7
agent-dump --list -query error
```

### URI direct dump

```bash
agent-dump opencode://<session-id>
agent-dump codex://<session-id>
agent-dump kimi://<session-id>
agent-dump claude://<session-id>
```

### Statistics

```bash
agent-dump --stats
agent-dump --stats -days 30
```

### Search

```bash
agent-dump --search "auth timeout"
agent-dump --search "auth" --list -days 30
agent-dump --reindex
```

### Collect (AI summary by date range)

```bash
agent-dump --collect
agent-dump --collect -since 2026-04-01 -until 2026-04-15
agent-dump --collect --save ./reports
```

### Config

```bash
agent-dump --config view
agent-dump --config edit
```

## Supported URI schemes

- `opencode://<session_id>` - OpenCode sessions
- `codex://<session_id>` - Codex sessions
- `kimi://<session_id>` - Kimi sessions
- `claude://<session_id>` - Claude Code sessions
- `cursor://<requestid>` - Cursor sessions

## Key features

- **Multi-agent support**: Scan and export sessions from OpenCode, Claude Code, Codex, Kimi, and Cursor
- **Interactive selection**: Friendly CLI selector with time-based grouping
- **URI direct access**: View or export any session by its URI without searching
- **Statistics**: `--stats` shows session counts and message counts grouped by agent and time
- **AI collect**: `--collect` summarizes sessions over a date range using your configured LLM
- **Full-text search**: `--search` uses local SQLite FTS5 with dual tokenizer (`unicode61` + `trigram`) for Western and CJK text
- **Structured queries**: `provider:`, `role:`, `path:`, `limit:` filters in `-query`
- **Scoped queries**: `agents://<path>?q=keyword&providers=codex,claude` for repo-scoped searches
- **Multi-format export**: `--format json,markdown,raw,print` with `md` alias for markdown
- **Config-driven**: `~/.config/agent-dump/config.toml` for AI provider, shortcuts, and agent deny-lists

## Documentation

Full documentation and Python source: [xingkaixin/agent-dump](https://github.com/xingkaixin/agent-dump).
