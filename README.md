![logo](https://raw.githubusercontent.com/xingkaixin/agent-dump/refs/heads/main/assets/logo.png)

# Agent Dump

AI Coding Assistant Session Export Tool - Exports JSON, Markdown, and raw session data from multiple AI coding tools, with direct URI printing.

## Supported AI Tools

- **OpenCode** - Open source AI coding assistant
- **ZCode** - ZCode coding assistant sessions
- **Claude Code** - Anthropic's AI coding tool
- **Codex** - OpenAI's command-line AI coding assistant
- **Kimi** - Moonshot AI assistant
- **Cursor** - Cursor composer sessions
- **Pi** - Earendil's AI coding agent
- **More Tools** - PRs are welcome to support other AI coding tools

## Features

- **Interactive Selection**: Provides a friendly command-line interactive interface using questionary
- **Multi-Agent Support**: Automatically scan session data from multiple AI tools
- **Batch Export**: Supports exporting all sessions from the last N days
- **Specific Export**: Export specific sessions by URI
- **Session List**: Only list sessions without exporting them
- **Direct Text Dump**: View session content directly in terminal via URI (e.g., `agent-dump opencode://session-id`)
- **Statistics**: Exports include statistics such as token usage and cost
- **Message Details**: Fully retains session messages, tool calls, and other details
- **Smart Title Extraction**: Automatically extract session titles from agent metadata
- **Session Statistics**: View usage statistics grouped by agent and time (`--stats`)
- **Full-Text Search**: Local SQLite FTS5 search across session titles, messages, reasoning, and tool state (`--search`); terms are matched literally
- **Ranked Search Evidence**: Search results include rank, URI, updated time, and highlighted snippets
- **Actionable Diagnostics**: CLI errors show checked roots, parsed URI fields, capability gaps, and next steps (localized via `--lang en|zh`)

## Path Discovery

`agent-dump` resolves most session roots in this order: official environment variable, tool default directory, then local development fallback under `data/<agent>`. ZCode currently uses only its macOS/Windows default database path.

- **Codex**: `CODEX_HOME` -> `~/.codex` -> `data/codex`
- **Claude Code**: `CLAUDE_CONFIG_DIR` -> `~/.claude` -> `data/claudecode`
- **Kimi**: `KIMI_SHARE_DIR` -> `~/.kimi` -> `data/kimi`
- **OpenCode**: `XDG_DATA_HOME/opencode` -> Windows data directory (`LOCALAPPDATA/opencode` or `APPDATA/opencode`) -> `~/.local/share/opencode` -> `data/opencode`
- **ZCode**: macOS `~/.zcode/cli/db/db.sqlite`; Windows `%USERPROFILE%\.zcode\cli\db\db.sqlite`; no Linux default path
- **Cursor**: Cursor's default user `globalStorage/state.vscdb`
- **Pi**: `PI_HOME` -> `~/.pi` -> `data/pi`

Notes:

- On Windows, prefer configuring the tool's official environment variable when available.
- The `data/<agent>` fallback is kept for local development and tests.

## Installation

### Method 1: Install using uv tool (Recommended)

```bash
# Install from PyPI (Available after release)
uv tool install agent-dump

# Install directly from GitHub
uv tool install git+https://github.com/xingkaixin/agent-dump
```

### Method 2: Run directly using uvx (No installation required)

```bash
# Run from PyPI (Available after release)
uvx agent-dump --help

# Run directly from GitHub
uvx --from git+https://github.com/xingkaixin/agent-dump agent-dump --help
```

### Method 3: Run directly using bunx / npx (No Python required)

```bash
# Run from npm
bunx @agent-dump/cli --help
npx @agent-dump/cli --help
```

The `bunx`, `npx`, and global npm/pnpm/Bun installation paths all require Node.js 22 or newer.
They execute the same Node.js package wrapper before launching the native binary.

`@agent-dump/cli` delegates the platform-package download to npm, preserving scoped registries,
authentication, proxy, and CA settings, then verifies the published checksum before installation.

Supported native targets:

<!-- native-targets:start -->
- `darwin-x64`
- `darwin-arm64`
- `linux-x64`
- `win32-x64`
<!-- native-targets:end -->

If your platform is unsupported, the wrapper prints the detected platform/arch pair and points to the GitHub releases page.

### Method 4: Local Development

```bash
# Clone the repository
git clone https://github.com/xingkaixin/agent-dump.git
cd agent-dump

# Use uv to install dependencies
uv sync

# Local installation test
uv tool install . --force
```

### Method 5: Install as a Skill

```bash
npx skills add xingkaixin/agent-dump
```

## Usage

### Interactive Export

```bash
# Enter interactive mode to select and export sessions
uv run agent-dump --interactive

# Or run as a module
uv run python -m agent_dump --interactive
```

After running, it will display the list of sessions from the last 7 days grouped by time (Today, Yesterday, This Week, This Month, Earlier). Use the spacebar to select/deselect, and press Enter to confirm the export.

> **Note:** Starting from v0.3.0, the default behavior has changed. Running `agent-dump` without arguments now shows the help message. Use `--interactive` to enter interactive mode.
>
> If multiple explicit modes are supplied, agent-dump preserves the existing mode priority and prints a warning listing the lower-priority options it ignored.

### URI Mode (Direct Text Dump)

Quickly view session content directly in the terminal without exporting to a file:

```bash
# View a specific session by URI
uv run agent-dump opencode://session-id-abc123

# The URI format is shown in list mode and interactive selector
#   • Session Title (opencode://session-id-abc123)
```

Supported URI schemes:
- `opencode://<session_id>` - OpenCode sessions
- `zcode://<session_id>` - ZCode sessions
- `codex://<session_id>` - Codex sessions
- `codex://threads/<session_id>` - Codex sessions
- `kimi://<session_id>` - Kimi sessions
- `claude://<session_id>` - Claude Code sessions
- `cursor://<requestid>` - Cursor sessions (`requestid` is used as URI identifier)
- `pi://<session_id>` - Pi sessions

### Typical Errors

`agent-dump` reports actionable diagnostics instead of a single opaque failure line.
Messages follow the CLI locale (`--lang en|zh`). Common examples:

```text
Diagnostic
Summary: No usable local session data found.
Searched roots:
  - Codex: CODEX_HOME/sessions: /Users/me/.codex/sessions
  - OpenCode: XDG/LOCALAPPDATA opencode.db: /Users/me/.local/share/opencode/opencode.db
Next steps:
  - Confirm the agent has produced session data on this machine.
  - If you use a custom directory, check that the relevant environment variable points at it.
```

```text
Diagnostic
Summary: No matching session found.
Parsed URI: codex://session-123
  - scheme: codex
  - session_id: session-123
Details:
  - Scanned the currently available providers, but no session id matched.
Next steps:
  - Run `agent-dump --list` to confirm the session still exists.
  - Check that the session id in the URI is complete and belongs to that provider.
```

```text
Diagnostic
Summary: The current URI requested an export capability Cursor does not support.
Capability gap: Cursor URI supports only json, print; requested raw
Next steps:
  - Remove `raw` and use a supported format.
  - For further processing, export JSON first and convert afterwards.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | The command did what was asked — including when the result set is legitimately empty (no sessions in the `-days` window, a keyword or `--search` that matched nothing), and when interactive export partially succeeds. |
| `1` | The command could not do what was asked: no provider data exists on this machine, a URI did not resolve to a session, every requested interactive export failed, or an argument combination is invalid. |
| `2` | Argument usage error, raised by `argparse` (unknown flag, invalid `--format` value). |

This makes `agent-dump --list && ...` meaningful: it succeeds when sessions were
listed and fails when there is nothing to list because no provider has data.

## Command-line Arguments

```bash
# Display help
uv run agent-dump                             # Show help message
uv run agent-dump --help                      # Show detailed help

# List mode (prints all matches, no pagination)
uv run agent-dump --list                      # List sessions from last 7 days
uv run agent-dump --list -days 3              # List sessions from last 3 days
uv run agent-dump --list -query error         # List sessions matching keyword "error"
uv run agent-dump --list -query codex,kimi:error  # Query only within Codex/Kimi
uv run agent-dump --list -query 'bug provider:codex path:.'  # Structured query: keyword + provider + path
uv run agent-dump --list -query 'bug path:"/Users/me/My Project"'  # Quote structured values containing spaces
uv run agent-dump --interactive -query 'role:user limit:20 refactor'  # Structured query with role and global limit
uv run agent-dump 'agents://.?q=refactor&providers=codex,claude'  # Query recent sessions for current repo
uv run agent-dump 'agents://.?q=refactor&providers=codex,claude&roles=user&limit=20'  # Structured query URI
uv run agent-dump --list 'agents:///Users/me/work/repo?providers=codex,opencode'  # Query by absolute path
uv run agent-dump --interactive 'agents://~/work/repo?q=bug'  # Path-scoped interactive selection
uv run agent-dump --list -page-size 10        # Accepted for compatibility but currently ignored

# Interactive export mode
uv run agent-dump --interactive               # Interactive mode (default 7 days)
uv run agent-dump --interactive -days 3       # Interactive mode (3 days)
uv run agent-dump -days 3                     # Auto-activates list mode
uv run agent-dump -query error                # Auto-activates list mode

# Note: in interactive mode with --query, only agents with keyword matches are shown,
#       and the count shown for each agent is the post-filter matched count.
#
# Query ambiguity rules:
# - `error:timeout` remains a plain keyword query.
# - `codex,kimi:error` remains the legacy agent-scoped query syntax.
# - Structured mode is activated only when a known key appears: provider / role / path / cwd / limit.
# - Quote or escape structured values containing spaces, for example `path:"/Users/me/My Project"`.
# - `role:...` constrains keyword matching to messages of those roles.
# - `limit:...` truncates the final global matched result set.

# URI mode - Direct text dump
uv run agent-dump opencode://<session-id>     # View OpenCode session content
uv run agent-dump zcode://<session-id>        # View ZCode session content
uv run agent-dump codex://<session-id>        # View Codex session content
uv run agent-dump kimi://<session-id>         # View Kimi session content
uv run agent-dump claude://<session-id>       # View Claude Code session content
uv run agent-dump cursor://<request-id>       # View Cursor session content
uv run agent-dump pi://<session-id>           # View Pi session content
uv run agent-dump codex://<session-id> --head # View lightweight session metadata before exporting
uv run agent-dump codex://<session-id> --format json --output ./my-sessions  # Export JSON file
uv run agent-dump codex://<session-id> --format markdown --output ./my-sessions  # Export Markdown file
uv run agent-dump codex://<session-id> --format print,json --output ./my-sessions # Print and export JSON
uv run agent-dump codex://<session-id> --format json,markdown,raw --output ./my-sessions  # Export multiple formats
uv run agent-dump cursor://<request-id> --format json --output ./my-sessions  # Cursor supports JSON export
uv run agent-dump cursor://<request-id> --format print,json --output ./my-sessions # Cursor print + JSON
uv run agent-dump codex://<session-id> --format json --summary --output ./my-sessions  # Export JSON with AI summary
uv run agent-dump codex://<session-id> --format print,json --summary --output ./my-sessions # Print, export JSON, and include summary

# Search mode (full-text)
uv run agent-dump --search "auth timeout"          # Search sessions matching keyword
uv run agent-dump --search "认证"                   # CJK keyword search works
uv run agent-dump --search "auth" --list -days 30  # Combine with list + days
uv run agent-dump --reindex                        # Force rebuild search index

# Note: search results include provider, updated time, URI, rank, and highlighted snippets.

# Statistics mode
uv run agent-dump --stats                    # Show session stats for last 7 days
uv run agent-dump --stats -days 30           # Show session stats for last 30 days

# Provider capabilities (read-only; --capabilities is an alias)
uv run agent-dump --providers

# collect mode (time-range summary with AI)
uv run agent-dump --collect
uv run agent-dump --collect -days 7
uv run agent-dump --collect -since 2026-03-01 -until 2026-03-05
uv run agent-dump --collect -since 20260301 -until 20260305
uv run agent-dump --collect --collect-mode insight
uv run agent-dump --collect --save ./reports
uv run agent-dump --collect --save ./reports/weekly.md
uv run agent-dump --collect --save /tmp/agent-dump-reports
uv run agent-dump --collect --save /tmp/agent-dump-reports/weekly.md
uv run agent-dump --collect 'agents://.?q=refactor&providers=codex,claude'
uv run agent-dump --collect --dry-run -since 20260301 -until 20260305 --save ./reports
uv run agent-dump --shortcut ob 20260408

# Note: --collect converts each session into high-signal events, plans chunks by budget,
#       requests fixed JSON summaries per chunk, merges them deterministically per session,
#       then uses tree reduction for the final aggregate before rendering Markdown.
# Note: collect date precedence is explicit -since/-until, then explicit -days, then today only.
# Note: --collect --dry-run completes scanning, query filtering, and chunk planning, then
#       prints provider breakdown, session/chunk counts, concurrency, dates, and save path preview.
# Note: during --collect, stderr shows multi-stage progress such as scan_sessions,
#       plan_chunks, summarize_chunks, merge_sessions, tree_reduction, render_final, and write_output.
# Note: unreadable sessions are reported on stderr and omitted while readable sessions continue.
# Note: collect writes files like agent-dump-collect-20260301-20260305.md.
# Note: --save accepts either a directory or a .md file path. Missing non-.md paths are treated as directories.

# config mode
uv run agent-dump --config view
uv run agent-dump --config edit

# Other options
uv run agent-dump --interactive --format json # Interactive export as JSON (default)
uv run agent-dump --interactive --format markdown   # Interactive export as Markdown
uv run agent-dump --interactive --format json,markdown,raw # Interactive multi-format export
uv run agent-dump --interactive -output ./my-sessions  # Specify output directory

# Compatibility note
# md remains available as an alias for markdown, e.g. --format md,raw
# --head is a URI discovery mode. It does not replace --format print and cannot be combined with --format/--summary.
```

### Full Parameter Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `uri` | Agent session URI to dump (e.g., `opencode://session-id`), or a scoped query URI such as `agents://.?q=refactor&providers=codex,claude&roles=user&limit=20` | - |
| `--interactive` | Run in interactive mode to select and export sessions | - |
| `-d`, `-days` | Query sessions from the last positive N days. Values outside the supported calendar range are rejected. In collect mode, applies when `-since/-until` are omitted. | 7 outside collect; today only in collect |
| `-q`, `-query` | Query filter. The keyword is one case-insensitive literal phrase after whitespace normalization, matched within a session title or logical transcript. Supports legacy `keyword` or `agent1,agent2:keyword` (e.g. `codex,kimi:error`), and structured terms like `bug provider:codex role:user path:. limit:20`. `cwd:` is an alias of `path:`. Structured values containing spaces support shell-style quoting and escaping. `limit` must be a positive signed 64-bit integer. Unknown structured keys are rejected. Cannot be combined with `agents://...` query URIs. | - |
| `--head` | URI mode only. Print bounded discovery metadata without rereading the transcript; message count is exact when discovery scanned the complete source and explicitly `unknown` otherwise. Does not export files or print body content. Cannot be combined with `--format` or `--summary`. | - |
| `--collect` | Collect session print content by date range, optionally constrained by an `agents://...` query URI, convert sessions into high-signal event streams, summarize fixed-schema JSON chunks, merge them deterministically per session, then tree-reduce the structured results into one final AI summary. Multi-stage progress is shown on stderr. | - |
| `--collect-mode` | collect output mode: `pm` for project-management summaries, `insight` for author insight summaries. | `pm` |
| `--dry-run` | Use with `--collect` to preview provider breakdown, session/chunk counts, concurrency, date range, and save path while skipping AI calls and file writes. | - |
| `--stats` | Show session usage statistics for the last N days, grouped by agent and time. If any message count is unknown, reports the known subtotal and number of unknown Sessions instead of presenting a partial sum as a total. Supports `-days` and `-query`; use it as a standalone mode. | - |
| `--providers`, `--capabilities` | Show the registered provider capability matrix, including URI schemes, supported and unsupported export formats, and whether local search roots exist. Does not scan sessions. | - |
| `--search` | Full-text search across provider-normalized session titles, messages, reasoning, and tool state using local SQLite FTS5; raw provider metadata is not searched. Whitespace-delimited terms are matched literally (FTS5 operator syntax such as `AND`/`NEAR`/`*` is not interpreted), all distinct terms are required, and terms may occur in different corpus fields. CJK terms require literal adjacency. FTS5-unavailable and unsupported-tokenizer cases use the same in-process logical-text matcher; unreadable sessions and index errors are reported on stderr. Cached session text not seen for 30 days is removed automatically. Can be combined with `--list`. | - |
| `--reindex` | Force rebuild of the full-text search index. Use when index is corrupted or after manual session data changes. | - |
| `--lang` | Force the CLI message locale (`en` or `zh`). Overrides locale detection from `LANG`/`LC_ALL`. | auto-detected |
| `--no-metadata-summary` | Hide the per-session metadata summary line in list and interactive views. | off |
| `-v`, `--version` | Print the version and exit. | - |
| `--shortcut` | Run a configured shortcut preset. Example: `agent-dump --shortcut ob 20260408` | - |
| `-since`, `--since` | collect start date, supports `YYYY-MM-DD` or `YYYYMMDD` | - |
| `-until`, `--until` | collect end date, supports `YYYY-MM-DD` or `YYYYMMDD` | - |
| `--save` | collect output path. Supports absolute/relative directory or `.md` file path. If no filename is provided, the default collect filename is used. | - |
| `-config`, `--config` | Config management: `view` or `edit` | - |
| `--list` | Only list sessions without exporting and print all matched sessions (auto-activated if `-days` or `-query` is specified without `--interactive`) | - |
| `-format`, `--format` | Output format. Supports comma-separated values: `json \\| markdown \\| raw \\| print`, with `md` kept as an alias. Default: URI mode `print`, non-URI mode `json`. URI mode can mix `print,json`; `--interactive` does not support `print`; `--list` ignores this option with warning; `--head` cannot be combined with this option. Cursor URI only supports `json` and `print` (no `raw/markdown`). | - |
| `-summary`, `--summary` | URI mode only. When enabled, summary is generated only if `--format` includes `json` and AI config is complete; otherwise a warning is shown and export continues without summary. During AI requests, a loading hint is shown on stderr. Cannot be combined with `--head`. | - |
| `-p`, `-page-size` | Accepted for compatibility; currently ignored | 20 |
| `-output`, `--output` | Output directory. For `json/raw`, priority is `--output` > `config.toml` `[export].output` > `./sessions`. Relative paths are resolved from the current working directory. Markdown keeps using `./sessions` unless `--output` is explicitly passed. Ignored in `--list` with warning. | `config export.output` or `./sessions` |
| `-h, --help` | Show help message | - |

### Library Usage

The top-level public API matches `agent_dump.__all__`:

| Symbol | Description |
|--------|-------------|
| `__version__` | Package version |
| `AgentScanner` | Scans every provider in the current registry |
| `BaseAgent` | Provider abstract base class |
| `Session` | Unified session data model |
| `OpenCodeAgent` | OpenCode provider |
| `ZCodeAgent` | ZCode provider |
| `CodexAgent` | Codex provider |
| `KimiAgent` | Kimi provider |
| `ClaudeCodeAgent` | Claude Code provider |
| `CursorAgent` | Cursor provider |
| `PiAgent` | Pi provider |

```python
from pathlib import Path

from agent_dump import AgentScanner

scanner = AgentScanner()

for agent in scanner.get_available_agents():
    sessions = agent.get_sessions(days=7)
    if not sessions:
        continue

    output_dir = Path("./sessions") / agent.name
    exported_path = agent.export_session(sessions[0], output_dir)
    print(f"{agent.display_name}: {exported_path}")
```

### collect configuration file

Default config path:

- macOS/Linux: `~/.config/agent-dump/config.toml`
- Windows: `%APPDATA%/agent-dump/config.toml`

Example:

```toml
[ai]
provider = "openai" # openai | anthropic
base_url = "https://api.openai.com/v1"
model = "gpt-4.1-mini"
api_key = "sk-..."

[collect]
summary_concurrency = 4 # 1-32

[export]
output = "../exports"

[shortcut.ob]
params = ["date"]
args = [
  "--collect",
  "--save", "~/Dropbox/OBSIDIAN/XingKaiXin/00_Inbox/{year}/{year_month}/agent-dump-collect-{date}.md",
  "--since", "{date}",
  "--until", "{date}",
]

[agent.claudecode]
deny = [
  "/Users/Kevin/workspace/projects/work/fin-agent/agent",
]
```

`[agent.<name>].deny` only applies to `--collect`. When a session `cwd` matches one of the configured paths, or is inside that path, the session is ignored during collect.

`[export].output` defines the global default output root for `json/raw` exports. It accepts absolute or relative paths. Relative paths are resolved from the directory where `agent-dump` is executed, not from the config file location.

`[shortcut.<name>]` defines a reusable shortcut preset. `params` declares positional input names. `args` declares the expanded CLI argv template. When `date` is provided, `{year}` / `{month}` / `{year_month}` are derived automatically.

When `agent-dump` writes `config.toml`, it escapes TOML-sensitive characters and restricts the file to owner-only permissions (`0600`) because it may contain an API key.
Legacy invalid TOML can still be read for compatibility, but `--config edit` refuses to rewrite it because a safe round trip cannot preserve unknown values. Fix the invalid escaping manually or replace the file before editing.

## Project Structure

```text
.
├── src/
│   └── agent_dump/             # Main package directory
│       ├── __init__.py         # Top-level public API
│       ├── __about__.py        # Single version source
│       ├── __main__.py         # python -m agent_dump entry point
│       ├── agent_registry.py   # Provider registry
│       ├── bounded_concurrency.py # Bounded Future scheduling
│       ├── cli.py              # Argument parsing and mode dispatch
│       ├── cli_shared.py       # Shared CLI helpers
│       ├── command_plan.py     # Normalizes CLI arguments into one command plan
│       ├── shortcut.py         # Expands configured shortcuts into regular arguments
│       ├── session_workflow.py # list / interactive / query workflow
│       ├── uri_workflow.py     # URI workflow
│       ├── collect_workflow.py # collect workflow
│       ├── maintenance_workflow.py # providers / stats / reindex workflows
│       ├── collect.py          # Collect compatibility imports
│       ├── collect_dates.py    # Collect date-range parsing
│       ├── collect_events.py   # Collect event extraction, rendering and chunking
│       ├── collect_llm.py      # Collect LLM requests
│       ├── collect_models.py   # Collect output models
│       ├── collect_output.py   # Collect Markdown output
│       ├── collect_logging.py  # Collect private diagnostics logging
│       ├── collect_prompts.py  # Collect prompt construction
│       ├── collect_progress.py # Collect progress and run stats
│       ├── collect_reduction.py # Collect concurrent summaries and reduction
│       ├── collect_requests.py # Collect retries and structured responses
│       ├── collect_sessions.py # Collect session filtering, reading, and chunk planning
│       ├── collect_summary.py  # Collect summary schema, payload merge, and JSON extraction
│       ├── coercion.py         # Fault-tolerant conversion of untrusted provider scalars
│       ├── config.py           # TOML configuration models and persistence
│       ├── config_command.py   # Interactive configuration command workflow
│       ├── diagnostics.py      # Structured diagnostics
│       ├── export_paths.py     # Safe export path construction
│       ├── i18n.py             # Language selection and translation runtime
│       ├── i18n_en.py          # English translation catalog
│       ├── i18n_keys.py        # Translation key definitions
│       ├── i18n_zh.py          # Chinese translation catalog
│       ├── message_filter.py   # Shared message filtering
│       ├── paths.py            # Search root models
│       ├── private_files.py     # Owner-only permissions for tool-created files
│       ├── prompt_safety.py    # Safe summary request composition and typed data envelopes
│       ├── provider_diagnostics.py # Structured provider warning boundary
│       ├── rendering.py        # print/head/markdown/json/raw rendering dispatch
│       ├── exporting.py        # Unified export execution and structured outcome
│       ├── output_formats.py   # Output format definitions and capability validation
│       ├── query_filter.py     # Query parsing and filtering
│       ├── query_semantics.py  # Literal Query/Search semantics and corpus
│       ├── search_index.py     # FTS5 search index
│       ├── search_diagnostics.py # Structured search diagnostics
│       ├── scanner.py          # Agent scanner
│       ├── selector.py         # Interactive selection
│       ├── session_data.py     # Bounded request cache and bulk-read leases
│       ├── session_exports.py  # Default JSON and raw session file writes
│       ├── session_projection.py # Default title, head, and summary projections
│       ├── terminal_output.py  # Safe interpolation of dynamic terminal fields
│       ├── text_safety.py      # Output sanitizing for third-party session text
│       ├── time_utils.py       # Time and timezone helpers
│       ├── transcript.py       # Read-only view over normalized messages
│       ├── uri_support.py      # URI parsing and session lookup
│       └── agents/             # Provider modules directory
│           ├── __init__.py     # Provider exports
│           ├── base.py         # BaseAgent and Session
│           ├── opencode.py     # OpenCode Agent
│           ├── zcode.py        # ZCode Agent
│           ├── claudecode.py   # Claude Code Agent
│           ├── claude_transcript.py # Claude JSONL transcript decoder
│           ├── codex.py        # Codex Agent
│           ├── codex_transcript.py # Codex response stream decoder
│           ├── codex_enrichment.py # Codex subagent and skill enrichment
│           ├── codex_patch.py  # Codex apply_patch parser
│           ├── cursor.py       # Cursor Agent
│           ├── cursor_storage.py # Cursor read-only SQLite access
│           ├── cursor_transcript.py # Cursor transcript decoder
│           ├── kimi.py         # Kimi Agent
│           ├── kimi_wire.py    # Kimi wire event stream parser
│           ├── pi.py           # Pi Agent
│           ├── file_sessions.py # Shared file-backed provider base
│           ├── jsonl_scan.py   # Bounded JSONL object scan and diagnostics
│           ├── message_assembly.py # Normalized message builders
│           ├── message_types.py # Internal normalized message/session types
│           └── title_fallback.py # Shared title fallback rules
├── tests/                      # Test directory
├── skills/agent-dump/          # Codex skill docs
├── npm/                        # npm wrapper and platform packages
├── web/                        # Astro landing page (en + zh + ja)
├── pyproject.toml              # Project configuration
├── justfile                    # Automated commands
├── ruff.toml                   # Code style configuration
└── sessions/                   # Default export directory
    └── {agent-name}/           # Exported files categorized by tool
        └── ses_xxx.json
```

## Development

```bash
# Run local CI checks with the current Python
# (includes npm tests when Node.js is available, and the landing page check when pnpm is)
just isok

# Lint code
just lint

# Auto-fix linting issues
just lint-fix

# Format code
just lint-format

# Type checking
just check

# Testing
just test

# Build a standalone binary for the current platform
just build-native

# Sync npm package metadata
just build-npm

# Run npm wrapper tests and smoke checks
just test-npm-smoke
```

## Release

```bash
# 1. Update the package version in a single place
$EDITOR src/agent_dump/__about__.py

# 2. Commit and merge to main

# 3. Create and push a release tag
git tag v{version}
git push origin v{version}
```

- The tag release workflow is [`release.yml`](./.github/workflows/release.yml)
- Only tags matching `vX.Y.Z` trigger the unified release pipeline
- Release publishes PyPI artifacts, GitHub release assets, and npm packages for `@agent-dump/cli`
- Retrying the same release skips byte-identical registry artifacts and fails if an existing version or asset differs
- The npm CLI package installs the matching native binary during `npm`/`npx` installation and verifies its checksum
- PyPI publishing uses `UV_PUBLISH_TOKEN`, stored as an environment secret in the GitHub `release` environment
- npm publishing uses Trusted Publisher/OIDC for every `@agent-dump/*` package, bound to this repository,
  `release.yml`, and the GitHub `release` environment; it does not use an `NPM_TOKEN` secret

## License

MIT
