![logo](https://raw.githubusercontent.com/xingkaixin/agent-dump/refs/heads/main/assets/logo.png)

# Agent Dump

AI Coding Assistant Session Export Tool - Exports JSON, Markdown, and raw session data from multiple AI coding tools, with direct URI printing.

Step-by-step guide: [Export a Codex session to Markdown](https://agent-dump.xingkaixin.me/guides/export-codex-session/).

## Supported AI Tools

- **OpenCode** - Open source AI coding assistant
- **ZCode** - ZCode coding assistant sessions
- **Claude Code** - Anthropic's AI coding tool
- **Codex** - OpenAI's command-line AI coding assistant
- **Kimi** - Moonshot AI assistant
- **Cursor** - Cursor composer sessions
- **Pi** - Earendil's AI coding agent
- **DeepChat** - Current local sessions from unencrypted databases
- **Cherry Studio** - Local 2.x chats and agent sessions
- **MiniMax Code** - Current CLI sessions from local SQLite storage
- **More Tools** - PRs are welcome to support other AI coding tools

## Features

- **Interactive Selection**: Provides a friendly command-line interactive interface using Ratatui
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
- **OpenCode**: `OPENCODE_DB` selects one database (relative to `XDG_DATA_HOME/opencode` or `~/.local/share/opencode`). Otherwise use `opencode.db` there, then the legacy Windows `LOCALAPPDATA`/`APPDATA` location, then `data/opencode/opencode.db`.
- **ZCode**: macOS `~/.zcode/cli/db/db.sqlite`; Windows `%USERPROFILE%\.zcode\cli\db\db.sqlite`; no Linux default path
- **Cursor**: Cursor's default user `globalStorage/state.vscdb`
- **Pi**: `PI_HOME` -> `~/.pi` -> `data/pi`
- **DeepChat**: `DEEPCHAT_USER_DATA_DIR/app_db/agent.db`; defaults to macOS `~/Library/Application Support/DeepChat/app_db/agent.db`, Windows `%APPDATA%\DeepChat\app_db\agent.db`, or Linux `${XDG_CONFIG_HOME:-~/.config}/DeepChat/app_db/agent.db`.
- **Cherry Studio**: `CHERRY_STUDIO_USER_DATA_DIR/Data/cherrystudio.sqlite`; otherwise the first existing database in the user data directories configured by `~/.cherrystudio/boot-config.json`, then the platform default: macOS `~/Library/Application Support/CherryStudio`, Windows `%APPDATA%\CherryStudio`, or Linux `${XDG_CONFIG_HOME:-~/.config}/CherryStudio` (each with `Data/cherrystudio.sqlite`). The override is provided by agent-dump; use it for portable/dev installations or to select among multiple installations.
- **MiniMax Code**: `MINIMAX_DATA_DIR` → `MAVIS_DATA_DIR` → `~/.minimax`; the database is `v2/sqlite/runtime-state.sqlite` under the selected root. Only one root is selected; a missing explicit path never falls back to another installation.

Notes:

- On Windows, prefer configuring the tool's official environment variable when available.
- The `data/<agent>` fallback is kept for local development and tests.

DeepChat reads saved sessions in the current `agent.db`, including migrated history, ACP sessions, and subagent sessions; drafts are excluded. It supports listing, query, search, stats, collect, and print / JSON / Markdown exports. Structured messages take precedence over the `content` fallback. Text, reasoning, and tool records are normalized; compaction markers do not enter collect. JSON also retains attachment references, links, and other message blocks. Attachment files and offloaded tool output are not read. Token totals come from message records; billing cost is unavailable.

SQLCipher databases, direct reads of legacy `chat.db`, and raw export are unsupported. The reader does not run DeepChat migrations or Tape recovery. Set `DEEPCHAT_USER_DATA_DIR` to read a custom user data directory.

Cherry Studio supports listing, query, search, stats, collect, and print / JSON / Markdown exports from its current 2.x database, including migrated history. Ordinary chats expose only the active root-to-leaf path; other branches and parallel model replies are excluded from exports, search, and counts. Structural roots and empty reserved user leaves are excluded. Agent sessions are read chronologically and use their workspace as the working directory; ordinary chats have no working directory. Deleted sessions and chat messages are excluded.

Text, reasoning, tool calls/results, code, and translations are normalized. JSON retains file references and control events; compaction summaries and internal events do not enter collect or search. Token totals come from message stats. Per-currency costs are preserved in JSON without conversion or an aggregate billing total. The reader never opens attachment files, scans SDK logs, or runs application migrations. Direct reads of 1.x IndexedDB/Redux data and raw export are unsupported.

MiniMax Code supports listing, query, search, stats, collect, and print / JSON / Markdown exports from the current CLI's migrated display messages. Visible conversations, child tasks, and archived sessions are included; hidden and internal peek/channel/cron sessions are excluded. Messages follow database row order and preserve text, reasoning, tool state/results, and attachment references. Compaction, review, and system events do not enter collect or search. The model comes from session metadata and remains unknown when absent; JSON retains recorded per-message token usage without estimating billing cost.

Set `MINIMAX_DATA_DIR` explicitly for custom profiles, earlier source builds using `~/.minimax-code`, or other directories. The reader does not read model-context JSONL or attachment files, run migrations, or recover rewound messages. Raw export, direct legacy storage reads, and desktop data are unsupported. Pending migrations and corrupt sessions produce diagnostics instead of appearing empty. See the [MiniMax Code design and acceptance scope](docs/minimax-provider-design.md).

OpenCode supports legacy SQLite and 2.x `session_v2/session_message`. When both schemas coexist, V2 wins for the same session ID; legacy-only sessions remain readable. V2 messages follow `seq` order, and counts include system and status records. Synthetic input, system/skill messages, compaction and shell records are excluded from collect. `OPENCODE_DB` selects a custom or channel database; a missing explicit path never falls back, and `:memory:` is unavailable. Attachments stay in JSON metadata without fetching referenced files. Running and archived records remain readable; pending inbox items are excluded. Raw export remains normalized `.raw.json`, not an OpenCode import file. See the [design and acceptance scope](docs/opencode-v2-design.md).

## Installation

Starting with v1.0.0, distribution artifacts use Rust. Version 0.15.9 is the last Python release. Rust wheels provide only the `agent-dump` command: Python imports and `python -m agent_dump` are no longer included. Applications using the old API can pin `agent-dump==0.15.9`.

Prebuilt artifacts support macOS x64/arm64, Linux x64 (glibc ≥ 2.17), and Windows x64. Linux musl/Alpine has no prebuilt wheel. Wheel installation needs no Rust compiler; building from Git/sdist requires Rust 1.90.0 and a C toolchain.

```bash
pip install agent-dump
```

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

# Build the native CLI
cargo build --locked --release

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
agent-dump --interactive

# Or use the source build
./target/release/agent-dump --interactive
```

After running, it will display the list of sessions from the last 7 days grouped by time (Today, Yesterday, This Week, This Month, Earlier). Use the spacebar to select/deselect, and press Enter to confirm the export.

> **Note:** Starting from v0.3.0, the default behavior has changed. Running `agent-dump` without arguments now shows the help message. Use `--interactive` to enter interactive mode.
>
> If multiple explicit modes are supplied, agent-dump preserves the existing mode priority and prints a warning listing the lower-priority options it ignored.

### URI Mode (Direct Text Dump)

Quickly view session content directly in the terminal without exporting to a file:

```bash
# View a specific session by URI
agent-dump opencode://session-id-abc123

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
- `deepchat://<session_id>` - DeepChat sessions
- `cherry://topic-<id>` / `cherry://session-<id>` - Cherry Studio chats / agent sessions
- `minimax://<session_id>` - MiniMax Code CLI sessions

### Typical Errors

`agent-dump` reports actionable diagnostics instead of a single opaque failure line.
Messages follow the CLI locale (`--lang en|zh`). Common examples:

```text
Diagnostic
Summary: No usable local session data found.
Searched roots:
  - Codex: CODEX_HOME/sessions: /Users/me/.codex/sessions
  - OpenCode: XDG/default opencode.db: /Users/me/.local/share/opencode/opencode.db
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
Summary: The current request uses an export capability Cursor does not support.
Capability gap: Cursor supports only json, print; requested raw
Next steps:
  - Remove `raw` and use a supported format.
  - For further processing, export JSON first and convert afterwards.
```

### Exit Codes

Explicit provider scopes (`provider:`, legacy provider prefixes, or `providers=` in query URIs) are applied before discovery. Unselected providers are not scanned. An empty explicit scope result keeps the mode’s no-match behavior, without probing unrelated providers.

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
agent-dump                             # Show help message
agent-dump --help                      # Show detailed help

# List mode (prints all matches, no pagination)
agent-dump --list                      # List sessions from last 7 days
agent-dump --list -days 3              # List sessions from last 3 days
agent-dump --list -query error         # List sessions matching keyword "error"
agent-dump --list -query codex,kimi:error  # Query only within Codex/Kimi
agent-dump --list -query 'bug provider:codex path:.'  # Structured query: keyword + provider + path
agent-dump --list -query 'bug path:"/Users/me/My Project"'  # Quote structured values containing spaces
agent-dump --interactive -query 'role:user limit:20 refactor'  # Structured query with role and global limit
agent-dump 'agents://.?q=refactor&providers=codex,claude'  # Query recent sessions for current repo
agent-dump 'agents://.?q=refactor&providers=codex,claude&roles=user&limit=20'  # Structured query URI
agent-dump --list 'agents:///Users/me/work/repo?providers=codex,opencode'  # Query by absolute path
agent-dump --interactive 'agents://~/work/repo?q=bug'  # Path-scoped interactive selection
agent-dump --list -page-size 10        # Accepted for compatibility but currently ignored

# Interactive export mode
agent-dump --interactive               # Interactive mode (default 7 days)
agent-dump --interactive -days 3       # Interactive mode (3 days)
agent-dump -days 3                     # Auto-activates list mode
agent-dump -query error                # Auto-activates list mode

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
agent-dump opencode://<session-id>     # View OpenCode session content
agent-dump zcode://<session-id>        # View ZCode session content
agent-dump codex://<session-id>        # View Codex session content
agent-dump kimi://<session-id>         # View Kimi session content
agent-dump claude://<session-id>       # View Claude Code session content
agent-dump cursor://<request-id>       # View Cursor session content
agent-dump pi://<session-id>           # View Pi session content
agent-dump deepchat://<session-id>     # View DeepChat session content
agent-dump minimax://<session-id>      # View MiniMax Code session content
agent-dump codex://<session-id> --head # View lightweight session metadata before exporting
agent-dump codex://<session-id> --format json --output ./my-sessions  # Export JSON file
agent-dump codex://<session-id> --format markdown --output ./my-sessions  # Export Markdown file
agent-dump codex://<session-id> --format print,json --output ./my-sessions # Print and export JSON
agent-dump codex://<session-id> --format json,markdown,raw --output ./my-sessions  # Export multiple formats
agent-dump cursor://<request-id> --format json --output ./my-sessions  # Cursor supports JSON export
agent-dump cursor://<request-id> --format print,json --output ./my-sessions # Cursor print + JSON
agent-dump codex://<session-id> --format json --summary --output ./my-sessions  # Export JSON with AI summary
agent-dump codex://<session-id> --format print,json --summary --output ./my-sessions # Print, export JSON, and include summary

# Search mode (full-text)
agent-dump --search "auth timeout"          # Search sessions matching keyword
agent-dump --search "认证"                   # CJK keyword search works
agent-dump --search "auth" --list -days 30  # Combine with list + days
agent-dump --reindex                        # Force rebuild search index

# Note: search results include provider, updated time, URI, rank, and highlighted snippets.

# Statistics mode
agent-dump --stats                    # Show session stats for last 7 days
agent-dump --stats -days 30           # Show session stats for last 30 days

# Provider capabilities (read-only; --capabilities is an alias)
agent-dump --providers

# collect mode (time-range summary with AI)
agent-dump --collect
agent-dump --collect -days 7
agent-dump --collect -since 2026-03-01 -until 2026-03-05
agent-dump --collect -since 20260301 -until 20260305
agent-dump --collect --collect-mode insight
agent-dump --collect --save ./reports
agent-dump --collect --save ./reports/weekly.md
agent-dump --collect --save /tmp/agent-dump-reports
agent-dump --collect --save /tmp/agent-dump-reports/weekly.md
agent-dump --collect 'agents://.?q=refactor&providers=codex,claude'
agent-dump --collect --dry-run -since 20260301 -until 20260305 --save ./reports
agent-dump --shortcut ob 20260408

# Note: --collect keeps only visible user/assistant text, excluding system/developer/tool messages,
#       reasoning, plans, tool calls, and tool results. Sessions empty after this projection are ignored.
#       PM chunks summarize requests, decisions, and agent-reported outcomes, then merge per session
#       and reduce within each date/project group (or each session in insight mode).
#       Final Markdown input retains these sources; inputs over 64,000 characters require a narrower range/query.
# Note: collect date precedence is explicit -since/-until, then explicit -days, then today only.
# Note: --collect --dry-run completes scanning, query filtering, and chunk planning, then
#       prints provider breakdown, session/chunk counts, concurrency, dates, and save path preview.
# Note: during --collect, stderr shows multi-stage progress such as scan_sessions,
#       plan_chunks, summarize_chunks, merge_sessions, tree_reduction, render_final, and write_output.
# Note: unreadable sessions are reported on stderr; readable sessions without visible dialogue are silently ignored.
# Note: collect writes files like agent-dump-collect-20260301-20260305.md.
# Note: --save accepts either a directory or a .md file path. Missing non-.md paths are treated as directories.

# config mode
agent-dump --config view
agent-dump --config edit

# Other options
agent-dump --interactive --format json # Interactive export as JSON (default)
agent-dump --interactive --format markdown   # Interactive export as Markdown
agent-dump --interactive --format json,markdown,raw # Interactive multi-format export
agent-dump --interactive -output ./my-sessions  # Specify output directory

# Compatibility note
# md remains available as an alias for markdown, e.g. --format md,raw
# --head is a URI discovery mode. It does not replace --format print and cannot be combined with --format/--summary.
```

### Summarize with an external agent

Generate a self-contained task prompt instead of configuring an AI endpoint. No skill is required:

```bash
agent-dump --collect --emit-prompt \
  -since 20260824 -until 20260830 \
  --collect-mode pm --save ./reports/weekly.md

# Keep an existing collect shortcut and opt in for this invocation
agent-dump --shortcut ob 20260831 --emit-prompt
```

These commands print the prompt directly. For agent execution, **save stdout and stderr to separate private files
on the first invocation** so a command tool's output limit cannot discard candidates. A macOS/Linux shortcut example
(no additional CLI option is needed):

```bash
(
  umask 077
  collect_task_dir=$(mktemp -d) || exit 1
  agent-dump --shortcut ob 20260831 --emit-prompt \
    > "$collect_task_dir/prompt.md" 2> "$collect_task_dir/diagnostics.txt"
  collect_exit_code=$?
  printf 'Exit: %s\nPrompt: %s\nDiagnostics: %s\n' \
    "$collect_exit_code" "$collect_task_dir/prompt.md" "$collect_task_dir/diagnostics.txt"
  exit "$collect_exit_code"
)
```

Give the agent both file paths. It should read the instructions, validate the full manifest programmatically, and
process it in batches, without printing the entire file back into tool output. On other platforms, likewise use a
private temporary directory, capture both streams separately, and check the exit code.

Give the prompt to an agent that can run commands and read/write files in the same local environment.
It includes a fixed candidate manifest, per-session read commands, the working directory and timezone,
the existing `pm`/`insight` report requirements, and the absolute final report path.
Commands use the running native executable; they do not require another global install.
Keep the same provider-path environment variables. If the original runtime is no longer available,
confirm a replacement entry point before proceeding.

- stdout contains the prompt; diagnostics go to stderr. `--save` still names the **final report**, not the prompt file.
- Generation does not validate AI settings, call a model, plan summary chunks, write collect logs, or create the report.
  Content queries may still read transcripts and update the local search index while selecting candidates.
- All collect exclusions and query filters still apply. Dates include both endpoints and select sessions by their local
  **creation date**, not individual message timestamps. The manifest is not a content snapshot.
- Before reading transcripts, validate the manifest end marker, candidate count, unique URIs, JSON lengths, and command
  identities. Parseable JSON alone does not prove completeness. Recover a damaged manifest from the full saved file first;
  otherwise regenerate the prompt at most once with the original selection conditions and capture output directly.
  Regeneration creates a new candidate manifest, not the old snapshot. If the conditions are unknown or recovery fails,
  ask the user before delivering a partial report from a damaged manifest.
- Save each session's stdout/stderr separately and read the transcript in bounded chunks through EOF; successful export
  does not mean complete reading. Analyze only visible user/assistant text and do not switch to JSON to inspect tool results.
  A complete manifest with individual unreadable sources may produce a report disclosing those gaps.
- Ignore sessions without substantive visible dialogue. Keep approvals or duplicate transcripts only when they change a
  request, decision, or outcome, and keep the current reporting process out of the work being summarized. Replacing an existing
  report requires explicit user permission; prepare and verify the new content before replacing the old report.
- `--emit-prompt` requires collect mode and conflicts with `--dry-run`. No matching candidates produces no prompt
  and exits `0`; no available provider or a preparation error exits `1`.
- To make this permanent for a shortcut, add `"--emit-prompt"` to its `args`; shortcut expansion needs no special handling.

Like the built-in collect prompts, the generated model instructions and report headings are Chinese;
`--lang` controls CLI help and diagnostics. Treat the prompt's titles and paths as private data.
External processing is subject to the chosen agent's data-transfer policy, not necessarily offline.
Generating a prompt does not mean that a report has been created, and does not automatically launch an external agent.

### Full Parameter Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `uri` | Agent session URI to dump (e.g., `opencode://session-id`), or a scoped query URI such as `agents://.?q=refactor&providers=codex,claude&roles=user&limit=20` | - |
| `--interactive` | Run in interactive mode to select and export sessions | - |
| `-d`, `-days`, `--days` | Query sessions from the last positive N days. Values outside the supported calendar range are rejected. In collect mode, applies when `-since/-until` are omitted. | 7 outside collect; today only in collect |
| `-q`, `-query` | Query filter. The keyword is one case-insensitive literal phrase after whitespace normalization, matched within a session title or logical transcript. Supports legacy `keyword` or `agent1,agent2:keyword` (e.g. `codex,kimi:error`), and structured terms like `bug provider:codex role:user path:. limit:20`. `cwd:` is an alias of `path:`. Structured values containing spaces support shell-style quoting and escaping. `limit` must be a positive signed 64-bit integer. Unknown structured keys are rejected. Cannot be combined with `agents://...` query URIs. | - |
| `--head` | URI mode only. Print bounded discovery metadata without rereading the transcript; message count is exact when discovery scanned the complete source and explicitly `unknown` otherwise. Does not export files or print body content. Cannot be combined with `--format` or `--summary`. | - |
| `--collect` | Collect sessions by date range, optionally constrained by `-query` or an `agents://...` query URI (mutually exclusive). Only visible user/assistant text is summarized; system/developer/tool messages, reasoning, plans, tool calls, and tool results are excluded, and empty projected sessions are ignored. PM mode extracts requests, decisions, and agent-reported outcomes before deterministic session merge and tree reduction. Multi-stage progress is shown on stderr. | - |
| `--collect-mode` | collect output mode: `pm` for project-management summaries, `insight` for author insight summaries. | `pm` |
| `--dry-run` | Use with `--collect` to preview provider breakdown, session/chunk counts, concurrency, date range, and save path while skipping AI calls and file writes. | - |
| `--emit-prompt` | Use with `--collect` to print a self-contained task for an external agent, without AI configuration or report writes. Incompatible with `--dry-run`; `--save` specifies the eventual report path. | - |
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
| `--save` | collect report path. Supports absolute/relative directory or `.md` file path. If no filename is provided, the default collect filename is used. With `--emit-prompt`, the path is included as an instruction for the external agent; no report is written. | - |
| `-config`, `--config` | Config management: `view` or `edit` | - |
| `--list` | Only list sessions without exporting and print all matched sessions (auto-activated if `-days` or `-query` is specified without `--interactive`) | - |
| `-format`, `--format` | Output format. Supports comma-separated values: `json \\| markdown \\| raw \\| print`, with `md` kept as an alias. Default: URI mode `print`, non-URI mode `json`. URI mode can mix `print,json`; `--interactive` does not support `print`; `--list` ignores this option with warning; `--head` cannot be combined with this option. Cursor supports only `json` and `print` (no `raw/markdown`). | - |
| `-summary`, `--summary` | URI mode only. When enabled, summary is generated only if `--format` includes `json` and AI config is complete; otherwise a warning is shown and export continues without summary. During AI requests, a loading hint is shown on stderr. Cannot be combined with `--head`. | - |
| `-p`, `-page-size`, `--page-size` | Accepted for compatibility; currently ignored | 20 |
| `-output`, `--output` | Output directory. For `json/raw`, priority is `--output` > `config.toml` `[export].output` > `./sessions`. Relative paths are resolved from the current working directory. Markdown keeps using `./sessions` unless `--output` is explicitly passed. Ignored in `--list` with warning. | `config export.output` or `./sessions` |
| `-h, --help` | Show help message | - |

When URI mode combines `print` with file formats, a print read/render failure is reported without blocking file exports. Raw source copying can still succeed when normalized parsing fails. Exit status remains `0` if any requested output succeeds, otherwise `1`.

### Python API migration

Rust releases distribute a CLI only. Call `agent-dump` as a subprocess and use JSON exports for structured data. The frozen Python implementation is retained in Git history and installed separately for differential verification. Existing API consumers should migrate to the CLI or pin `agent-dump==0.15.9`.

### collect configuration file

Discovery failures are counted separately because the number of missing sessions is unknown. Reads that fail during query filtering also count as session read failures. These gaps are included in saved reports and completion logs; `--emit-prompt` carries them in its task metadata and fails if failures leave no candidates.

File discovery failures include partially unreadable providers. Valid sessions remain usable, but collect reports and handoff metadata mark discovery as incomplete; `--emit-prompt` exits with failure if no candidates remain after discovery failures.

When some session reads or summaries fail, collection continues with successful sessions. The saved Markdown includes a fixed incomplete-report notice with failure and included-session counts; an entirely failed run still fails.

Collect preserves visible message text within a 12,000-character per-session extraction budget (including event labels). Text beyond that budget is omitted and marked as truncated for the final summary.

PM summaries merge sessions only within the same date and known working directory. Sessions without a working directory retain separate attribution.

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

Collect, `--collect --dry-run`, and `--collect --emit-prompt` require valid TOML and exclusion arrays containing only nonempty path strings. Invalid configuration stops the command before session discovery or AI requests; compatibility parsing never disables exclusions for collect.

`[export].output` defines the global default output root for `json/raw` exports. It accepts absolute or relative paths. Relative paths are resolved from the directory where `agent-dump` is executed, not from the config file location.

`[shortcut.<name>]` defines a reusable shortcut preset. `params` declares positional input names. `args` declares the expanded CLI argv template. When `date` is provided, `{year}` / `{month}` / `{year_month}` are derived automatically.

When `agent-dump` writes `config.toml`, it preserves comments, whitespace, and field order, escapes TOML-sensitive characters, and restricts the file to owner-only permissions (`0600`) because it may contain an API key.
Legacy invalid TOML can still be read for compatibility, but `--config edit` refuses to rewrite it because a safe round trip cannot preserve unknown values. Fix the invalid escaping manually or replace the file before editing.

## Project Structure

```text
Cargo.toml      # Workspace, shared dependencies/lints and CLI release version
rustfmt.toml    # Stable Rustfmt, edition 2024, 80 columns
src/            # CLI workflows, Collect and terminal interaction
crates/agent-dump-core/ # Providers, sessions, queries and export engine
resources/      # Embedded locales and prompts
tests/cli/      # CLI contracts and external Python reference comparison
tests/tooling/  # Packaging, benchmark and documentation checks
scripts/        # Validated CLI benchmarks and paired release eval
packaging/      # Maturin builds and installation verification
npm/            # Node launcher and platform packages
docs/           # Architecture, migration and acceptance evidence
web/            # Landing page
```

## Development

Rust is the build and runtime implementation starting with v1.0.0, with Ratatui for terminal interaction. The old Python application has been removed from the working tree. Differential tests install the immutable 0.15.9 wheel in an isolated reference environment. See [P2](docs/rust-p2-completion.md), [P3–P5](docs/rust-p3-p5-completion.md), [P6 acceptance](docs/rust-p6-completion.md), and the [final performance report](docs/benchmarks/rust-p6.md).

```bash
# Run Cargo directly from the repository root
cargo build --locked --release
cargo test --locked --workspace

# Run full CI checks, including the isolated historical Python reference
# (includes npm tests when Node.js is available, and the landing page check when pnpm is)
just isok

# Check Rustfmt, strict Clippy and Ruff
just lint

# Auto-fix linting issues
just lint-fix

# Format code
just fmt

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

Both crates inherit workspace lints: unsafe code is denied, Clippy all/pedantic are denied, and nursery warnings fail the gate through `-D warnings`. Explicit exceptions and their reasons are documented in the [development guide](docs/development-guide.md#rust-格式与-lint). Existing CLI differential and tooling tests remain in `tests/`.

## Release

```bash
# 1. Update the package version in a single place
$EDITOR Cargo.toml

# 2. Commit and merge to main

# 3. Create and push a release tag
git tag v{version}
git push origin v{version}
```

- The tag release workflow is [`release.yml`](./.github/workflows/release.yml)
- Only tags matching `vX.Y.Z` trigger the unified release pipeline
- Release publishes PyPI artifacts, GitHub release assets, and npm packages for `@agent-dump/cli`
- Retrying the same release skips byte-identical registry artifacts and fails if an existing version or asset differs
- npm publishing waits until each package is downloadable with the expected integrity before proceeding to the next package; native packages precede the CLI wrapper
- The npm CLI package installs the matching native binary during `npm`/`npx` installation and verifies its checksum
- PyPI publishing uses `UV_PUBLISH_TOKEN`, stored as an environment secret in the GitHub `release` environment
- npm publishing uses Trusted Publisher/OIDC for every `@agent-dump/*` package, bound to this repository,
  `release.yml`, and the GitHub `release` environment; it does not use an `NPM_TOKEN` secret

## License

MIT
