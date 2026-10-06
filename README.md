![logo](https://raw.githubusercontent.com/xingkaixin/agent-dump/refs/heads/main/assets/logo.png)

# Agent Dump

A local AI session tool for individual developers and AI Agents. Find, read, export, and reuse conversations from supported coding tools without modifying their source data.

[Usage guides](https://agent-dump.xingkaixin.me/guides/): export Codex or Claude Code sessions, search past decisions, hand context to an agent, create work reports, and save conversations to Obsidian.

## Get started

[Install the CLI](#installation), then choose a workflow. You need session history already saved on this machine by a [supported tool](#supported-ai-tools). Custom directories and content limits are described under [Path Discovery](#path-discovery).

### For developers

```bash
# Browse conversations active in the last week
agent-dump browse --time-field updated --days 7

# Find a past discussion in this project
agent-dump search 'auth timeout' --query 'path:.' --days 30

# Export a result using its URI
agent-dump export codex://SESSION_ID --format markdown --output ./sessions
```

Copy a real URI from the list or search results in place of `codex://SESSION_ID`. Search defaults to sessions created in the time window; add `--time-field updated` for recent activity. Use `--interactive` to select several sessions for export.

### For AI Agents

```bash
# Inspect supported formats and source paths, then find candidates
agent-dump providers --json
agent-dump list --time-field updated --days 7 --json

# Inspect one session, then obtain instructions for paginated reading
agent-dump head codex://SESSION_ID --json
agent-dump read-prompt codex://SESSION_ID

# Prepare a report task for an external Agent; no API configuration needed
agent-dump collect --days 7 --emit-prompt --save ./reports/weekly.md
```

Follow the generated read commands and cursors until `has_more=false` to cover the selected content. Check exit codes and `status`; a partial result is not a complete reading. `--emit-prompt` creates instructions, not the report itself. See [machine-readable output](#machine-readable-output), [cited context exports](#message-locations-and-context), and the [Agent recipes](skills/agent-dump/references/cli-recipes.md).

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

- **Find past work**: Search titles, messages, reasoning, and tool state; filter by Provider, project path, role, or recent activity.
- **Read in context**: Browse in the terminal, open a Session URI, or give an Agent bounded JSON pages with continuation cursors.
- **Reuse with sources**: Export sessions or selected context to supported formats, retaining URI and message locators in context exports.
- **Summarize conversations**: Collect all eligible user/assistant text through bounded chunks, or hand the task to an external Agent. Failures are marked as incomplete.
- **Automate**: Query metadata, capabilities, search evidence, and statistics as JSON; unknown facts remain explicit.

Available formats and message details depend on the source tool. Normalized output does not reproduce every private field or attachment file. Run `agent-dump --providers --json` to inspect capabilities.

## Installation

The Rust release provides the `agent-dump` CLI. Install with uv:

```bash
uv tool install agent-dump
```

Prebuilt artifacts support macOS x64/arm64, Linux x64 (glibc ≥ 2.17), and Windows x64. Wheel installation needs no Rust compiler. See [source builds and Python API migration](docs/cli-compatibility.md#source-builds-and-python-api-migration) for other requirements and older integrations.

### Other command entry points

| Purpose | Command |
| --- | --- |
| Install with pip | `pip install agent-dump` |
| Run with uvx | `uvx agent-dump --help` |
| Run with npx | `npx @agent-dump/cli --help` |
| Run with bunx | `bunx @agent-dump/cli --help` |

All usage examples below use `agent-dump`. When using uvx, npx, or bunx, replace only that command prefix. The arguments are the same.

The `bunx`, `npx`, and global npm/pnpm/Bun installation paths require Node.js 22 or newer. The npm wrapper preserves registry, authentication, proxy, and CA settings, then verifies the platform-package checksum. Unsupported platforms receive a diagnostic and a link to GitHub releases.

Supported npm native targets:

<!-- native-targets:start -->
- `darwin-x64`
- `darwin-arm64`
- `linux-x64`
- `win32-x64`
<!-- native-targets:end -->

### Native installation: curl, Homebrew and Scoop

These channels are available starting with v1.0.0 and install the native CLI without Python, Node.js or Rust.

**macOS / Linux shell installer** (macOS x64/arm64; Linux x64 with glibc ≥ 2.17):

```bash
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh
```

The installer verifies SHA-256 and the executable version before replacing an existing installation. It defaults to `~/.local/bin`, does not use sudo or edit shell configuration, and prints a PATH hint when needed. Run it again to update. To choose a version or directory, pass variables to `sh`:

```bash
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | AGENT_DUMP_VERSION=1.1.1 AGENT_DUMP_INSTALL_DIR="$HOME/.local/bin" sh
```

Uninstall the default shell installation with `rm "$HOME/.local/bin/agent-dump"`. Package-manager symlinks are not overwritten; update those installations through their original manager.

**Homebrew** (macOS x64/arm64 and Linux x64):

```bash
brew install xingkaixin/tap/agent-dump
brew upgrade agent-dump
# Uninstall: brew uninstall agent-dump
```

**Scoop** (Windows x64, with Scoop already installed):

```powershell
scoop bucket add xingkaixin https://github.com/xingkaixin/scoop-bucket
scoop install xingkaixin/agent-dump
scoop update agent-dump
# Uninstall: scoop uninstall agent-dump
```

Linux ARM64, musl/Alpine, and Windows ARM64 do not have native builds. When changing installation channels, remove the old installation or check which executable your PATH selects.

### Install as an Agent skill

```bash
npx skills add xingkaixin/agent-dump
```

## Usage

### Interactive Export

```bash
# Enter interactive mode to select and export sessions
agent-dump --interactive
```

In a terminal this opens the session reader (same as `--browse`) with sessions from the last 7 days. Press Space to mark sessions and `e` to export the marked ones. Without a terminal, the line-based numbered selection prompt is kept.

Running `agent-dump` without arguments shows help. If multiple explicit modes are supplied, agent-dump preserves the existing mode priority and prints a warning listing the lower-priority options it ignored.

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
| `0` | The command did what was asked — including when the result set is legitimately empty (no sessions in the `--days` window, a keyword or `--search` that matched nothing), and when interactive export partially succeeds. |
| `1` | The command could not do what was asked: no provider data exists on this machine, a URI did not resolve to a session, every requested interactive export failed, or an argument combination is invalid. |
| `2` | Argument usage error, raised by `argparse` (unknown flag, invalid `--format` value). |

This makes `agent-dump --list && ...` meaningful: it succeeds when sessions were
listed and fails when there is nothing to list because no provider has data.

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

## Command-line Arguments

Use `agent-dump --help` for the current option list. These examples extend the [getting-started workflows](#get-started).

### Commands

A leading command is shorthand for the matching option; option-based invocations keep working unchanged.

| Command | Equivalent |
| --- | --- |
| `list` | `--list` |
| `search <TERMS>` | `--search <TERMS>` |
| `browse` | `--browse` |
| `export <URI>` | `<URI> --format json` unless `--format` is given |
| `export` (no URI) | `--interactive` |
| `head <URI>` / `read <URI>` / `read-prompt <URI>` | `<URI> --head` / `--read` / `--read-prompt` |
| `collect` / `stats` / `providers` / `reindex` | `--collect` / `--stats` / `--providers` / `--reindex` |
| `config <view\|edit>` | `--config <view\|edit>` |
| `shortcut <NAME> [ARGS]` | `--shortcut <NAME> [ARGS]` |

A bare URI still prints the session to the terminal.

```bash
# Filter by Provider, project path, or message role
agent-dump --list --query 'error provider:codex,kimi' --days 30
agent-dump --list --query 'bug path:"/Users/me/My Project"'
agent-dump --interactive --query 'role:user limit:20 refactor'
agent-dump --list 'agents://.?q=refactor&providers=codex,claude&roles=user&limit=20'

# Export several formats, or add an AI summary to JSON
agent-dump --interactive --format json,markdown --output ./sessions
agent-dump codex://SESSION_ID --format print,json --output ./sessions
agent-dump codex://SESSION_ID --format json --summary --output ./sessions

# Search, inspect statistics, or rebuild the index
agent-dump --search 'auth timeout' --days 30
agent-dump --stats --days 30
agent-dump --reindex

# Collect a report or preview its workload
agent-dump --collect --days 7 --save ./reports
agent-dump --collect --since 2026-03-01 --until 2026-03-05 --save ./reports/weekly.md
agent-dump --collect --collect-mode insight --dry-run
agent-dump --shortcut ob 20260408

# Inspect or edit configuration
agent-dump --config view
agent-dump --config edit
```

`--query` uses the same matching as `--search`: whitespace-separated literal terms must all occur, anywhere in the title or transcript. Structured keys (`provider`, `role`, `path`, `limit`) activate structured parsing; quote values containing spaces. `role` restricts matching to those messages, and `limit` applies to the final global results. `error:timeout` remains a plain term. Lists print all matches; interactive Provider counts reflect the filtered results.

Collect uses explicit `--since`/`--until` first, then explicit `--days`, otherwise today. `--save` accepts a directory or a `.md` file, with absolute or relative paths. The [collect section](#collect-configuration-file) describes full input coverage, exclusions, progress, and incomplete reports.

### Summarize with an external agent

Generate a self-contained task prompt instead of configuring an AI endpoint. No skill is required:

```bash
agent-dump --collect --emit-prompt \
  --since 20260824 --until 20260830 \
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
- All collect exclusions and query filters still apply. Dates include both endpoints and select visible text by its **actual local date**, splitting long sessions across days. Candidate discovery does not exclude old sessions; generation reads their visible text to retain only sessions with in-range activity. The external Agent then applies dates using read-page `text_spans`. The manifest is not a content snapshot.
- Before reading transcripts, validate the manifest end marker, candidate count, unique URIs, JSON lengths, and command
  identities. Parseable JSON alone does not prove completeness. Recover a damaged manifest from the full saved file first;
  otherwise regenerate the prompt at most once with the original selection conditions and capture output directly.
  Regeneration creates a new candidate manifest, not the old snapshot. If the conditions are unknown or recovery fails,
  ask the user before delivering a partial report from a damaged manifest.
- Read each session with `--read --order asc --json`, then continue with `--read --cursor <next_cursor> --json` until
  `has_more=false`. Save each page and its diagnostics separately. Process every fragment of long messages; a successful
  page request does not mean complete reading. Analyze only visible user/assistant text without `--details`. Partial reads,
  missing pages, and changing revisions must be disclosed; never combine notes from different revisions.
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

<details>
<summary>Compatibility aliases</summary>

Existing calls still accept `-days`, `-query`, `-format`, `-output`, `-summary`, `-config`, `-since`, `-until`, `-page-size`, and `-v`. `--capabilities`, `md`, `cwd:`, and the legacy Provider query prefix also remain available. See the [compatibility reference](docs/cli-compatibility.md) for their standard equivalents.

</details>

### Full Parameter Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `uri` | Agent session URI to dump (e.g., `opencode://session-id`), or a scoped query URI such as `agents://.?q=refactor&providers=codex,claude&roles=user&limit=20` | - |
| `--interactive`, `-i` | Open the session reader to select and export sessions (same as `--browse` in a terminal) | - |
| `--days`, `-d` | Query sessions from the last positive N days. Values outside the supported calendar range are rejected. In collect mode, applies when `--since/--until` are omitted. | 7 outside collect; today only in collect |
| `--time-field` | Use `created` or `updated` time for the `--days` window in list/search/browse/interactive modes. | `created` |
| `--query`, `-q` | Query filter. Keyword terms are split on whitespace and matched case-insensitively like `--search`; every term must occur in the session title or logical transcript. Supports a plain keyword or structured terms like `bug provider:codex role:user path:. limit:20`. Structured values containing spaces support shell-style quoting and escaping. `limit` must be a positive signed 64-bit integer. Unknown structured keys are rejected. Cannot be combined with `agents://...` query URIs. | - |
| `--head` | URI mode only. Print bounded discovery metadata without rereading the transcript; message count is exact when discovery scanned the complete source and explicitly `unknown` otherwise. Does not export files or print body content. Cannot be combined with `--format` or `--summary`. | - |
| `--collect` | Collect sessions by date range, optionally constrained by `--query` or an `agents://...` query URI (mutually exclusive). Only visible user/assistant text is summarized; system/developer/tool messages, reasoning, plans, tool calls, and tool results are excluded, and empty projected sessions are ignored. PM mode extracts requests, decisions, and agent-reported outcomes before deterministic session merge and tree reduction. Multi-stage progress is shown on stderr. | - |
| `--collect-mode` | collect output mode: `pm` for project-management summaries, `insight` for author insight summaries. | `pm` |
| `--dry-run` | Use with `--collect` to preview provider breakdown, session/chunk counts, concurrency, date range, and save path while skipping AI calls and file writes. | - |
| `--emit-prompt` | Use with `--collect` to print a self-contained task for an external agent, without AI configuration or report writes. Incompatible with `--dry-run`; `--save` specifies the eventual report path. | - |
| `--stats` | Show session usage statistics for the last N days, grouped by agent and time. If any message count is unknown, reports the known subtotal and number of unknown Sessions instead of presenting a partial sum as a total. Supports `--days` and `--query`; use it as a standalone mode. | - |
| `--providers` | Show the registered provider capability matrix, including URI schemes, supported and unsupported export formats, and whether local search roots exist. Does not scan sessions. | - |
| `--search` | Full-text search across provider-normalized session titles, messages, reasoning, and tool state using local SQLite FTS5; raw provider metadata is not searched. Whitespace-delimited terms are matched literally (FTS5 operator syntax such as `AND`/`NEAR`/`*` is not interpreted), all distinct terms are required, and terms may occur in different corpus fields. CJK terms require literal adjacency. FTS5-unavailable and unsupported-tokenizer cases use the same in-process logical-text matcher; unreadable sessions and index errors are reported on stderr. Cached session text not seen for 30 days is removed automatically. Can be combined with `--list`. | - |
| `--reindex` | Force rebuild of the full-text search index. Use when index is corrupted or after manual session data changes. | - |
| `--lang` | Force the CLI message locale (`en` or `zh`). Overrides locale detection from `LANG`/`LC_ALL`. | auto-detected |
| `--no-metadata-summary` | Hide the per-session metadata summary line in list and interactive views. | off |
| `-v`, `--version` | Print the version and exit. | - |
| `--shortcut` | Run a configured shortcut preset. Example: `agent-dump --shortcut ob 20260408` | - |
| `--since` | collect start date, supports `YYYY-MM-DD` or `YYYYMMDD` | - |
| `--until` | collect end date, supports `YYYY-MM-DD` or `YYYYMMDD` | - |
| `--save` | collect report path. Supports absolute/relative directory or `.md` file path. If no filename is provided, the default collect filename is used. With `--emit-prompt`, the path is included as an instruction for the external agent; no report is written. | - |
| `--config` | Config management: `view` or `edit` | - |
| `--list` | Only list sessions without exporting and print all matched sessions (auto-activated if `--days` or `--query` is specified without `--interactive`) | - |
| `--format` | Output format. Supports comma-separated values: `json \\| markdown \\| raw \\| print`. Default: URI mode `print`, non-URI mode `json`. URI mode can mix `print,json`; `--interactive` does not support `print`; `--list` ignores this option with warning; `--head` cannot be combined with this option. Cursor supports only `json` and `print` (no `raw/markdown`). | - |
| `--summary` | URI mode only. When enabled, summary is generated only if `--format` includes `json` and AI config is complete; otherwise a warning is shown and export continues without summary. During AI requests, a loading hint is shown on stderr. Cannot be combined with `--head`. | - |
| `--page-size`, `-p` | Compatibility only; ignored. For reading pages, use `--read` with `--limit` / `--max-chars`. | 20 |
| `--output` | Output directory. For `json/raw`, priority is `--output` > `config.toml` `[export].output` > `./sessions`. Relative paths are resolved from the current working directory. Markdown keeps using `./sessions` unless `--output` is explicitly passed. Ignored in `--list` with warning. | `config export.output` or `./sessions` |
| `-h, --help` | Show help message | - |

When URI mode combines `print` with file formats, a print read/render failure is reported without blocking file exports. Raw source copying can still succeed when normalized parsing fails. Exit status remains `0` if any requested output succeeds, otherwise `1`.

### Python API migration

See [CLI migration and the frozen Python release](docs/cli-compatibility.md#source-builds-and-python-api-migration).

### collect configuration file

Discovery failures are counted separately because the number of missing sessions is unknown. Reads that fail during query filtering also count as session read failures. These gaps are included in saved reports and completion logs; `--emit-prompt` carries them in its task metadata and fails if failures leave no candidates.

File discovery failures include partially unreadable providers. Valid sessions remain usable, but collect reports and handoff metadata mark discovery as incomplete; `--emit-prompt` exits with failure if no candidates remain after discovery failures.

When some session reads or summaries fail, collection continues with successful sessions. The saved Markdown includes a fixed incomplete-report notice with failure and included-session counts; an entirely failed run still fails.

Collect discovers candidate sessions without a creation-time cutoff and processes user/assistant visible text only within the requested local dates. A session spanning several days is split into separate daily units before summarization; session counts remain unique URI counts. Text without a reliable timestamp is excluded and reported as an incomplete date-coverage gap (including undated Kimi context and inferred Cursor times). No session creation/update time is substituted. Query filters select candidates; limits apply to unique sessions after text-date filtering. Events, including long individual messages, are split into chunks of at most 3,200 Unicode characters including labels. Chunk summaries are merged in groups of at most eight; large final reports are rendered in separate source-preserving groups. Model inputs are limited to 64,000 characters per request. Oversized metadata or derived summaries fail explicitly; source text is never silently truncated. Partial reports list omitted session URIs. Full input coverage does not mean a summary preserves every detail.

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

### Recently active sessions

```bash
agent-dump --list --time-field updated -d 7 --json
agent-dump --search 'database locked' --time-field updated -d 7
agent-dump --browse --time-field updated -d 7
agent-dump --interactive --time-field updated -d 7
```

`--days` uses creation time by default. Add `--time-field updated` to find sessions whose Provider-reported `updated_at` falls within the last N days, including sessions created much earlier. `--time-field created` explicitly selects the existing default. This option is available only for list, search, browse and interactive modes; collect dates and statistics retain their existing meaning.

Activity lists order by updated time before applying a result limit. Human lists and interactive selection retain Provider groups; dates and Today/Yesterday groups use the selected time field. Search still orders primarily by relevance. JSON records retain both original timestamps. Discovery may scan metadata outside the creation-time window to find old active sessions; filtering uses the existing Provider-projected `updated_at` fact without adding a separate file-modification-time filter. Provider coverage and partial-discovery diagnostics remain unchanged.

### Machine-readable output

Add `--json` to list, search or statistics mode to write one JSON object to stdout. Diagnostics go to stderr. Existing `--format json` file exports are unchanged.

```bash
agent-dump --list --json
agent-dump --search 'timeout' --json --query 'provider:codex'
agent-dump --stats --json
agent-dump codex://SESSION_ID --head --json
agent-dump --providers --json
```

The envelope contains `schema_version: 1`, `kind` (list/search/stats), `status` (ok/partial/error), `data`, `failed_providers`, `failed_sessions`, and `error`. Incomplete discovery or failed query reads produce partial results. List/search data is an array; statistics data contains total/by_provider/by_time. Unknown directories, models and message counts are null; timestamps use UTC ISO 8601. Statistics expose known_messages and unknown_message_count_sessions separately. Time buckets use creation dates in the local timezone.

No matches produce an empty array and exit 0. No available source without an explicit Provider scope produces error and exit 1. Argument/execution failures may only emit stderr diagnostics; always check the exit code. Session context, `--read`, `--head`, and `--providers` also accept `--json`; other modes reject it.

`agent-dump <URI> --head --json` returns `kind: "head"` and one session record in `data`, with the same facts as list output plus `project`, `version`, and `subtargets`. It does not request a full transcript. The URI is canonical, unknown directories/models/message counts remain null, and recoverable lookup diagnostics produce `status: "partial"` with details on stderr.

`agent-dump --providers --json` returns `kind: "providers"` and a `data` array containing each Provider's name, display name, scheme, identifier label, optional ID prefixes, supported `formats`, and `search_roots` with label/path/exists. This inspects capabilities and path existence without reading session contents. An existing root does not guarantee a readable session. Both envelopes use `schema_version: 1`; failures return a nonzero exit code and may leave stdout empty.


### Message locations and context

```bash
agent-dump --search 'database locked' --locate --json --query 'provider:codex'
agent-dump codex://SESSION_ID --message 'REVISION:POSITION' --before 2 --after 3
agent-dump codex://SESSION_ID --message 'REVISION:POSITION' --json
agent-dump codex://SESSION_ID --message 'REVISION:POSITION' --before 2 --after 3 --format json,markdown --output excerpts
```

Pass `locations[].locator` from search unchanged to `--message`. Positions are one-based normalized message ordinals. Locators bind to the transcript snapshot; rerun search after content changes. Context defaults to three messages on either side; zero selects only the target, and ranges clamp at transcript boundaries. Reading a range still parses the source transcript; this is not partial disk I/O.

`--locate` requires `--search`. It returns messages containing any search term, respecting role filters, while all terms must still match the session. Title-only matches have empty locations; failed location reads have null locations and partial status. Search without --locate is unchanged.

`--message` cannot combine with `--head` or `--summary`. Without `--format`, it prints context; `--json` writes a context envelope to stdout with kind=context and data containing uri, locator, total_messages, start/end and messages (position plus normalized message). Invalid or stale locators exit nonzero; JSON diagnostics go only to stderr.

Use `--format json,markdown` to export the selected context. Files are named `<id>.messages-<start>-<end>.json` / `.md` under the Provider's output directory, separate from full-session exports. Both formats retain the canonical Session URI, the locator (revision plus target position), the absolute message range, and status. JSON retains normalized message records; Markdown renders their searchable text. Recoverable source diagnostics mark the file `partial` and are reported on stderr. Stale locators are rejected before file creation. Provider format restrictions still apply; raw/print file formats and `--json` with file-export options are rejected. `--output` requires an explicit `--format`; output-directory defaults follow full-session export rules.

### On-demand reading and Agent read prompts

Give an Agent this single command to obtain instructions and executable commands for reading a session in bounded pages, without installing a skill or configuring MCP:

```bash
agent-dump codex://SESSION_ID --read-prompt
```

`--read-prompt` works with every registered Provider, including Claude Code, OpenCode, ZCode, Kimi, Cursor, Pi, DeepChat, Cherry Studio and MiniMax Code. It validates the URI syntax without discovering sources, reading transcripts, calling a model or creating files. Generated commands use the running native executable's absolute path and require the original Provider path environment variables. Instructions follow `--lang en|zh`. Generating a prompt does not confirm that the session exists or has been read.

Direct reading is also available:

```bash
agent-dump codex://SESSION_ID --read --json
agent-dump codex://SESSION_ID --read --cursor 'data.next_cursor from the previous page' --json
agent-dump claude://SESSION_ID --read --role user --match 'database migration' --limit 10 --json
agent-dump opencode://SESSION_ID --read --order asc --max-chars 4000 --details --json
```

| Option | Behavior |
| --- | --- |
| `--read` | Page one session; text by default, structured stdout with `--json` |
| `--read-prompt` | Generate self-contained reading instructions; conflicts with `--read` and `--json` |
| `--limit` | At most 1–100 messages per page, default 20; these are messages, not conversation turns |
| `--max-chars` | At most 1–100000 Unicode characters of message text per page, default 12000; excludes JSON framing and cursor metadata |
| `--order` | `desc` (default) traverses original message positions backwards; `asc` traverses forwards |
| `--cursor` | Continue using an unchanged cursor; selection, order and budgets are retained and cannot be overridden |
| `--role` | Select one normalized role; surrounding whitespace and argument case are ignored |
| `--match` | Case-insensitive literal phrase in each message's selected text view, with whitespace normalized; filtering precedes pagination |
| `--details` | Include the readable projection of reasoning, plans and structured tool state; default is text parts only |

Read options require `--read` and cannot mix with list, search, collect, export, `--head`, `--summary` or `--message`. Existing full URI printing, `--search` and `--query` keep their semantics. Matching is not regex, semantic or cross-message search. Add `--details` to search tool details. Both views skip messages with no readable text, do not read attachments, and do not represent every raw Provider field. Nonempty role/match values are limited to 100/4096 UTF-8 bytes; read URIs to 4096 bytes.

JSON contains `schema_version: 1`, `kind: read`, `status`, `has_more` and `data`. Data includes uri, revision, total_messages before filtering, options, messages and next_cursor. Each fragment contains its original one-based position, a locator usable with `--message`, role, text, total_chars, and zero-based Unicode start/end offsets [start,end). `truncated` marks a partial message. Long messages resume at the next character through the cursor; characters within a message always traverse forwards.

`has_more=false` means the selected view has no more matching content. Budget pagination does not make status partial. Recoverable source diagnostics produce partial status with details on stderr. No matches succeed with an empty array. Invalid, cross-session or stale cursors exit nonzero with empty stdout. Restart when the transcript changes; never combine revisions as one snapshot. Cursors do not preserve historical snapshots.

Bounded output reduces content returned to the Agent, but reading may still parse the full source transcript; it does not promise partial disk I/O. Sources remain read-only and retain each Provider's existing data and platform support limits.

Read pages without `--details` include `messages[].text_spans`: local `date` (null when unknown or inferred) and absolute Unicode `start`/`end` offsets within the message text. Spans are clipped to each returned fragment; subtract the fragment start when slicing its text. Separators between text parts are not dated. Collect handoffs use these spans to split and filter actual activity dates.

### TUI session reader

```bash
agent-dump --browse
agent-dump --browse --query 'provider:codex path:.' --days 30
agent-dump --browse 'agents://.?providers=codex,claude'
agent-dump --browse --search "database lock" --format json,markdown --output ./exports
```

`--browse` requires an interactive terminal. By default, it selects sessions created in the last seven days and sorts them by update time. Add `--time-field updated` to filter by recent activity. It supports existing query filters and agents:// query URIs, and reads the selected transcript on demand (content filtering itself may read multiple sessions). Wide terminals show list and transcript panes; below 90 columns Tab switches between single panes. Provider sources remain read-only. The reader does not live-refresh active sessions; reopen it to refresh the list.

- Up/Down or j/k move or scroll in the focused pane; Enter/Right opens the transcript, Left returns to the list.
- Tab switches panes; PageUp/PageDown scroll pages; Home/End jump to either end.
- `s` searches sessions using all words, within the current Provider/path/date/role/limit scope. `--browse --search "database lock"` starts with the same search and relevance order. With a role filter, all words must occur in one message of that role. Hit navigation visits messages containing any search word. The header shows scope and search mode; `?` shows full scope and help. `c` clears search text while keeping scope.
- `/` starts literal search within the current session; Enter searches, Esc cancels input, n/N jumps to the next/previous matching message. Search expands tool details.
- `t` toggles tool details; `y` sends a URI clipboard request (requires terminal OSC 52 support).
- `x` previews the current matching message with three surrounding messages on each side. `+`/`-` changes that radius; n/N changes the hit. `e` exports exactly this range as JSON and/or Markdown with source URI and message positions. If the source changed since preview, export is rejected. `x` or Esc returns to the full session.
- Space marks sessions for batch export. Outside excerpt preview, `e` exports all marked sessions, or the selected session when none are marked, using --format, --output and existing Provider capabilities. Default is JSON; print is not supported.
- q/Esc/Ctrl-C close the reader and restore the terminal, exiting 0.

Empty search results stay open so `s` can change the search and `c` can clear it. Provider/path/date/role/limit filters stay fixed during a reader session; change CLI arguments and reopen to widen them. Unavailable sources or non-terminal input fail. Individual read errors are displayed while other sessions remain selectable. In a terminal, `--interactive` opens this reader. Without a terminal, `--interactive` keeps the line-based selection prompt for pipelines.

## Project Structure

```text
Cargo.toml      # Workspace, shared dependencies/lints and CLI release version
rustfmt.toml    # Stable Rustfmt, edition 2024, 80 columns
src/            # CLI workflows, Collect and terminal interaction
crates/agent-dump-core/ # Providers, sessions, queries and export engine
resources/      # Embedded locales and prompts
tests/cli/      # Rust CLI contracts and optional historical comparisons
tests/tooling/  # Packaging, benchmark and documentation checks
scripts/        # Validated CLI benchmarks and paired release eval
packaging/      # Maturin builds and installation verification
npm/            # Node launcher and platform packages
docs/           # Architecture, migration and acceptance evidence
web/            # Landing page
```

## Development

Rust is the build and runtime implementation starting with v1.0.0, with Ratatui for terminal interaction. The old Python application has been removed from the working tree. CI and `just isok` run Rust behavior contracts without the historical Python CLI. Optional differential tests install the immutable 0.15.9 wheel in an isolated reference environment through `just test-differential`. See [P2](docs/rust-p2-completion.md), [P3–P5](docs/rust-p3-p5-completion.md), [P6 acceptance](docs/rust-p6-completion.md), and the [final performance report](docs/benchmarks/rust-p6.md).

```bash
# Run Cargo directly from the repository root
cargo build --locked --release
cargo test --locked --workspace

# Run full CI checks without the historical Python reference
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
- Native installer assets share the same verified binaries. After publication, `distribution.yml` syncs Homebrew and Scoop using the repository secret `DISTRIBUTION_TOKEN`; it can be retried separately for the latest stable release.
- Retrying the same release skips byte-identical registry artifacts and fails if an existing version or asset differs
- npm publishing waits until each package is downloadable with the expected integrity before proceeding to the next package; native packages precede the CLI wrapper
- The npm CLI package installs the matching native binary during `npm`/`npx` installation and verifies its checksum
- PyPI publishing uses `UV_PUBLISH_TOKEN`, stored as an environment secret in the GitHub `release` environment
- npm publishing uses Trusted Publisher/OIDC for every `@agent-dump/*` package, bound to this repository,
  `release.yml`, and the GitHub `release` environment; it does not use an `NPM_TOKEN` secret

## License

MIT
