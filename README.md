![logo](https://raw.githubusercontent.com/xingkaixin/agent-dump/refs/heads/main/assets/logo.png)

# Agent Dump

AI Coding Assistant Session Export Tool - Supports exporting session data from multiple AI coding tools to JSON format.

## Supported AI Tools

- **OpenCode** - Open source AI coding assistant
- **Claude Code** - Anthropic's AI coding tool
- **Codex** - OpenAI's command-line AI coding assistant
- **Kimi** - Moonshot AI assistant
- **More Tools** - PRs are welcome to support other AI coding tools

## Features

- **Interactive Selection**: Provides a friendly command-line interactive interface using questionary
- **Multi-Agent Support**: Automatically scan session data from multiple AI tools
- **Batch Export**: Supports exporting all sessions from the last N days
- **Specific Export**: Export specific sessions by session ID
- **Session List**: Only list sessions without exporting them
- **Direct Text Dump**: View session content directly in terminal via URI (e.g., `agent-dump opencode://session-id`)
- **Statistics**: Exports include statistics such as token usage and cost
- **Message Details**: Fully retains session messages, tool calls, and other details
- **Smart Title Extraction**: Automatically extract session titles from agent metadata
- **Session Statistics**: View usage statistics grouped by agent and time (`--stats`)

## Path Discovery

`agent-dump` resolves session roots in this order: official environment variable, tool default directory, then local development fallback under `data/<agent>`.

- **Codex**: `CODEX_HOME` -> `~/.codex` -> `data/codex`
- **Claude Code**: `CLAUDE_CONFIG_DIR` -> `~/.claude` -> `data/claudecode`
- **Kimi**: `KIMI_SHARE_DIR` -> `~/.kimi` -> `data/kimi`
- **OpenCode**: `XDG_DATA_HOME/opencode` -> Windows data directory (`LOCALAPPDATA/opencode` or `APPDATA/opencode`) -> `~/.local/share/opencode` -> `data/opencode`

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

Supported native targets:

- `darwin-x64`
- `darwin-arm64`
- `linux-x64`
- `win32-x64`

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
- `codex://<session_id>` - Codex sessions
- `codex://threads/<session_id>` - Codex sessions
- `kimi://<session_id>` - Kimi sessions
- `claude://<session_id>` - Claude Code sessions
- `cursor://<requestid>` - Cursor sessions (`requestid` is used as URI identifier)

### Typical Errors

`agent-dump` now reports actionable diagnostics instead of a single opaque failure line. Common examples:

```text
诊断信息
结论: 未找到任何可用的本地会话数据。
searched roots:
  - Codex: CODEX_HOME/sessions: /Users/me/.codex/sessions
  - OpenCode: XDG/LOCALAPPDATA opencode.db: /Users/me/.local/share/opencode/opencode.db
下一步:
  - 确认对应 agent 已在本机生成过会话数据。
  - 若使用自定义目录，检查相关环境变量是否指向正确位置。
```

```text
诊断信息
结论: 未找到匹配的会话。
解析后的 URI: codex://session-123
  - scheme: codex
  - session_id: session-123
下一步:
  - 先运行 `agent-dump --list` 确认该会话是否仍存在。
  - 检查 URI 中的 session id 是否完整且对应正确 provider。
```

```text
诊断信息
结论: 当前 URI 请求了 Cursor 不支持的导出能力。
缺失能力: Cursor URI 仅支持 json 与 print；当前请求了 raw
下一步:
  - 移除 `raw` 或 `markdown`，改用 `json` 或 `print`。
```

### Command-line Arguments

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
uv run agent-dump --interactive -query 'role:user limit:20 refactor'  # Structured query with role and global limit
uv run agent-dump 'agents://.?q=refactor&providers=codex,claude'  # Query recent sessions for current repo
uv run agent-dump 'agents://.?q=refactor&providers=codex,claude&roles=user&limit=20'  # Structured query URI
uv run agent-dump --list 'agents:///Users/me/work/repo?providers=codex,opencode'  # Query by absolute path
uv run agent-dump --interactive 'agents://~/work/repo?q=bug'  # Path-scoped interactive selection
uv run agent-dump --list -page-size 10        # Accepted but currently ignored in --list mode

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
# - `role:...` constrains keyword matching to messages of those roles.
# - `limit:...` truncates the final global matched result set, not per-agent pagination.

# URI mode - Direct text dump
uv run agent-dump opencode://<session-id>     # View OpenCode session content
uv run agent-dump codex://<session-id>        # View Codex session content
uv run agent-dump kimi://<session-id>         # View Kimi session content
uv run agent-dump claude://<session-id>       # View Claude Code session content
uv run agent-dump cursor://<request-id>       # View Cursor session content
uv run agent-dump codex://<session-id> --head # View lightweight session metadata before exporting
uv run agent-dump codex://<session-id> --format json --output ./my-sessions  # Export JSON file
uv run agent-dump codex://<session-id> --format markdown --output ./my-sessions  # Export Markdown file
uv run agent-dump codex://<session-id> --format print,json --output ./my-sessions # Print and export JSON
uv run agent-dump codex://<session-id> --format json,markdown,raw --output ./my-sessions  # Export multiple formats
uv run agent-dump cursor://<request-id> --format json --output ./my-sessions  # Cursor supports JSON export
uv run agent-dump cursor://<request-id> --format print,json --output ./my-sessions # Cursor print + JSON
uv run agent-dump codex://<session-id> --format json --summary --output ./my-sessions  # Export JSON with AI summary
uv run agent-dump codex://<session-id> --format print,json --summary --output ./my-sessions # Print, export JSON, and include summary

# Statistics mode
uv run agent-dump --stats                    # Show session stats for last 7 days
uv run agent-dump --stats -days 30           # Show session stats for last 30 days

# collect mode (time-range summary with AI)
uv run agent-dump --collect
uv run agent-dump --collect -since 2026-03-01 -until 2026-03-05
uv run agent-dump --collect -since 20260301 -until 20260305
uv run agent-dump --collect --save ./reports
uv run agent-dump --collect --save ./reports/weekly.md
uv run agent-dump --collect --save /tmp/agent-dump-reports
uv run agent-dump --collect --save /tmp/agent-dump-reports/weekly.md
uv run agent-dump --collect 'agents://.?q=refactor&providers=codex,claude'
uv run agent-dump --shortcut ob 20260408

# Note: --collect converts each session into high-signal events, plans chunks by budget,
#       requests fixed JSON summaries per chunk, merges them deterministically per session,
#       then uses tree reduction for the final aggregate before rendering Markdown.
# Note: during --collect, stderr shows multi-stage progress such as scan_sessions,
#       plan_chunks, summarize_chunks, merge_sessions, tree_reduction, render_final, and write_output.
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
| `-d`, `-days` | Query sessions from the last N days | 7 |
| `-q`, `-query` | Query filter. Supports legacy `keyword` or `agent1,agent2:keyword` (e.g. `codex,kimi:error`), and structured terms like `bug provider:codex role:user path:. limit:20`. `cwd:` is an alias of `path:`. Unknown structured keys are rejected. Cannot be combined with `agents://...` query URIs. | - |
| `--head` | URI mode only. Print lightweight session metadata for discovery; does not export files or print body content. Cannot be combined with `--format` or `--summary`. | - |
| `--collect` | Collect session print content by date range, optionally constrained by an `agents://...` query URI, convert sessions into high-signal event streams, summarize fixed-schema JSON chunks, merge them deterministically per session, then tree-reduce the structured results into one final AI summary. Multi-stage progress is shown on stderr. | - |
| `--stats` | Show session usage statistics for the last N days, grouped by agent and time. Supports `-days`. Cannot be combined with other modes. | - |
| `--shortcut` | Run a configured shortcut preset. Example: `agent-dump --shortcut ob 20260408` | - |
| `-since`, `--since` | collect start date, supports `YYYY-MM-DD` or `YYYYMMDD` | - |
| `-until`, `--until` | collect end date, supports `YYYY-MM-DD` or `YYYYMMDD` | - |
| `--save` | collect output path. Supports absolute/relative directory or `.md` file path. If no filename is provided, the default collect filename is used. | - |
| `-config`, `--config` | Config management: `view` or `edit` | - |
| `--list` | Only list sessions without exporting and print all matched sessions (auto-activated if `-days` or `-query` is specified without `--interactive`) | - |
| `-format`, `--format` | Output format. Supports comma-separated values: `json \\| markdown \\| raw \\| print`, with `md` kept as an alias. Default: URI mode `print`, non-URI mode `json`. URI mode can mix `print,json`; `--interactive` does not support `print`; `--list` ignores this option with warning; `--head` cannot be combined with this option. Cursor URI only supports `json` and `print` (no `raw/markdown`). | - |
| `-summary`, `--summary` | URI mode only. When enabled, summary is generated only if `--format` includes `json` and AI config is complete; otherwise a warning is shown and export continues without summary. During AI requests, a loading hint is shown on stderr. Cannot be combined with `--head`. | - |
| `-p`, `-page-size` | Accepted for compatibility; currently ignored in `--list` mode | 20 |
| `-output`, `--output` | Output directory. For `json/raw`, priority is `--output` > `config.toml` `[export].output` > `./sessions`. Relative paths are resolved from the current working directory. Markdown keeps using `./sessions` unless `--output` is explicitly passed. Ignored in `--list` with warning. | `config export.output` or `./sessions` |
| `-h, --help` | Show help message | - |

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
summary_concurrency = 4

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

## Project Structure

```text
.
├── src/
│   └── agent_dump/          # Main package directory
│       ├── __init__.py      # Package initialization
│       ├── __main__.py      # python -m agent_dump entry point
│       ├── cli.py           # Command-line interface
│       ├── scanner.py       # Agent scanner
│       ├── selector.py      # Interactive selection
│       └── agents/          # Agent modules directory
│           ├── __init__.py  # Agent exports
│           ├── base.py      # BaseAgent abstract class
│           ├── opencode.py  # OpenCode Agent
│           ├── claudecode.py # Claude Code Agent
│           ├── codex.py     # Codex Agent
│           └── kimi.py      # Kimi Agent
├── tests/                   # Test directory
├── pyproject.toml           # Project configuration
├── justfile                 # Automated commands
├── ruff.toml                # Code style configuration
└── sessions/                # Export directory
    └── {agent-name}/        # Exported files categorized by tool
        └── ses_xxx.json
```

## Development

```bash
# Run all checks (lint, type check, test)
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
- The npm CLI package installs the matching native binary during `npm`/`npx` installation and verifies its checksum
- Configure `UV_PUBLISH_TOKEN` in the GitHub `pypi` environment
- Configure `NPM_TOKEN` in the GitHub `release` environment

## License

MIT
