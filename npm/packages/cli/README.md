# @agent-dump/cli

Native Rust `agent-dump` binaries for `bunx` and `npx`.

The package downloads the matching native binary for the current platform during installation
and verifies it against the published checksum manifest before exposing `agent-dump`.

Registry access is delegated to npm so scoped registries, `.npmrc` authentication, proxies,
custom certificate authorities, and npm's retry policy remain in effect. The npm subprocess has
a five-minute deadline and bounded output; the downloaded archive is size-checked before loading,
decompressed under an output limit, and verified against the published checksum manifest.

```bash
bunx @agent-dump/cli --help
npx @agent-dump/cli --help
```

Every entry point above, including `bunx`, requires Node.js 22 or newer because it executes the
same Node.js package wrapper. Node 18 and 20 are end-of-life upstream and are not tested.

Supported targets:

<!-- native-targets:start -->
- `darwin-x64`
- `darwin-arm64`
- `linux-x64`
- `win32-x64`
<!-- native-targets:end -->

Linux x64 requires glibc 2.17 or newer; Alpine/musl is not supported by this prebuilt target.
macOS wheel baselines are 10.12 (x64) and 11.0 (arm64). No Python runtime is needed.

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
agent-dump zcode://<session-id>
agent-dump codex://<session-id>
agent-dump codex://threads/<session-id>
agent-dump kimi://<session-id>
agent-dump claude://<session-id>
agent-dump cursor://<request-id>
agent-dump pi://<session-id>
agent-dump deepchat://<session-id>
agent-dump cherry://topic-<id>
agent-dump cherry://session-<id>
agent-dump minimax://<session-id>
agent-dump codex://<session-id> --head
```

### Statistics

```bash
agent-dump --stats
agent-dump --stats -days 30
```

### Provider capabilities

```bash
agent-dump --providers
agent-dump --capabilities
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
agent-dump --collect -days 7
agent-dump --collect -days 7 -query "provider:codex path:. limit:20" --dry-run
agent-dump --collect -since 2026-04-01 -until 2026-04-15
agent-dump --collect --collect-mode insight
agent-dump --collect --dry-run --save ./reports
agent-dump --collect --emit-prompt --save ./reports/weekly.md
agent-dump --collect --save ./reports
```

Collect execution, dry-run, and prompt handoff all support `-query` filters. Do not combine
`-query` with an `agents://...` query URI. Reports and handoff metadata retain discovery and
session read failures so incomplete input remains visible.

### Config

```bash
agent-dump --config view
agent-dump --config edit
```

## Supported URI schemes

- `opencode://<session_id>` - OpenCode sessions
- `zcode://<session_id>` - ZCode sessions
- `codex://<session_id>` - Codex sessions
- `codex://threads/<session_id>` - Codex sessions
- `kimi://<session_id>` - Kimi sessions
- `claude://<session_id>` - Claude Code sessions
- `cursor://<requestid>` - Cursor sessions
- `pi://<session_id>` - Pi sessions
- `deepchat://<session_id>` - DeepChat sessions
- `cherry://topic-<id>` / `cherry://session-<id>` - Cherry Studio chats / agent sessions
- `minimax://<session_id>` - MiniMax Code CLI sessions

DeepChat supports saved sessions in its current unencrypted `app_db/agent.db`, including migrated
history, ACP sessions, and subagent sessions. Set `DEEPCHAT_USER_DATA_DIR` for a custom user data
directory. SQLCipher databases and direct reads of legacy `chat.db` are unsupported.

Cherry Studio supports chats and agent sessions in its 2.x `Data/cherrystudio.sqlite`. Ordinary
chats include only the active branch; deleted records are excluded. Set
`CHERRY_STUDIO_USER_DATA_DIR` for a custom user data directory. Direct reads of 1.x IndexedDB/Redux
data are unsupported.

MiniMax Code supports the current CLI's migrated display messages in
`v2/sqlite/runtime-state.sqlite`, including visible conversations, child tasks, and archived
sessions. Hidden and internal sessions are excluded. The data root is selected from
`MINIMAX_DATA_DIR`, then `MAVIS_DATA_DIR`, then `~/.minimax`; a missing explicit path never falls
back. Set `MINIMAX_DATA_DIR` for custom profiles or other installations. Direct legacy storage
reads and desktop data are unsupported; pending migrations and corrupt sessions produce
diagnostics.

These providers support list, query, search, stats, collect, and print / JSON / Markdown exports.
They read source databases without modifying them, retain attachment references without opening
attachment files, and do not support raw export.

OpenCode supports both legacy SQLite sessions and OpenCode 2.x sessions through the existing
`opencode://` workflows, including list, query, search, stats, collect, and export. When both
schemas coexist, 2.x takes precedence for matching session IDs while legacy-only sessions remain
readable. Set `OPENCODE_DB` to an absolute database path or a filename relative to
`$XDG_DATA_HOME/opencode` (or `~/.local/share/opencode`) to select a custom or channel database;
a missing explicit path never falls back. Reads are read-only, and raw export remains normalized
`.raw.json`, not an OpenCode import file.

```bash
agent-dump --list -query "provider:opencode"
agent-dump 'opencode://<session-id>' --format json,markdown --output ./sessions
agent-dump --collect --emit-prompt -query "provider:opencode"
```

## Key features

- **Multi-agent support**: Scan and export sessions from OpenCode, ZCode, Claude Code, Codex, Kimi, Cursor, Pi, DeepChat, Cherry Studio, and MiniMax Code
- **Interactive selection**: Friendly CLI selector with time-based grouping
- **URI direct access**: View or export any session by its URI without searching
- **Head metadata**: `--head` reuses bounded discovery metadata without rereading the transcript and marks incomplete message counts as unknown
- **Statistics**: `--stats` shows session and message counts grouped by agent and time, reporting known subtotals separately from sessions with unknown counts
- **Provider capabilities**: `--providers` reports URI schemes, export formats, keyword fast paths, and local search-root status without scanning sessions
- **AI collect**: `--collect` summarizes sessions over a date range using your configured LLM, with `pm` and `insight` modes
- **Relative collect windows**: Explicit `-days N` selects today minus N days through today; `-since/-until` takes precedence, while collect without either remains today-only
- **Collect dry-run**: `--collect --dry-run` previews provider breakdown, session/chunk counts, concurrency, and save path
- **External agent handoff**: `--collect --emit-prompt` outputs a self-contained prompt with safe read-only URI commands and candidate manifests for external agents without requiring local LLM configuration
- **Full-text search**: `--search` requires every distinct whitespace-delimited term, allows terms to match across corpus fields, keeps CJK matches contiguous, and gives FTS5 and in-process fallbacks the same literal semantics
- **Structured queries**: `-query` treats its keyword as one normalized literal phrase and supports `provider:`, `role:`, `path:`, and `limit:` filters (`role:` snippets come only from allowed messages)
- **Scoped queries**: `agents://<path>?q=keyword&providers=codex,claude` for repo-scoped searches
- **Multi-format export**: `--format json,markdown,raw,print` with `md` alias for markdown
- **Localized CLI**: `--lang en|zh` for user-facing messages and diagnostics
- **Predictable exit codes**: `0` success (including legitimately empty results), `1` could not complete the request, `2` usage error
- **Config-driven**: `~/.config/agent-dump/config.toml` for AI provider, shortcuts, and agent deny-lists

## Documentation

Full documentation and Python source: [xingkaixin/agent-dump](https://github.com/xingkaixin/agent-dump).
Changelog: [CHANGELOG.md](https://github.com/xingkaixin/agent-dump/blob/main/CHANGELOG.md).
