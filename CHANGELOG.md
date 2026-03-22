# Changelog

[中文](docs/zh/CHANGELOG.md)

## [0.6.9] - 2026-03-22

### Added

- **Collect agent-specific deny filtering**
  - `--collect` now supports `[agent.<name>].deny` in `config.toml`
  - Sessions are ignored during collect when their `cwd`/project directory matches a deny path or is inside that path
  - Filtering is scoped to collect mode only and does not affect regular export, `--list`, `--interactive`, or URI flows

### Documentation

- Added collect config example for `[agent.claudecode].deny` and documented its collect-only scope

## [0.6.8] - 2026-03-16

### Added

- **Collect structured multi-stage reduction pipeline**
  - Rewrote collect summary from a simple "summarize each session then merge" approach into a full multi-stage pipeline: `scan_sessions → plan_chunks → summarize_chunks → merge_sessions → tree_reduction → render_final → write_output`
  - Uses a fixed JSON schema (10 structured fields: topics, decisions, key_actions, etc.) to generate summaries for each chunk
  - Aggregates all session summaries through tree reduction (GROUP_SIZE=8), layer by layer
  - Added `--save` option to specify the collect output path (directory or `.md` file)
  - Disabled thinking/reasoning for OpenAI and Anthropic requests to reduce unnecessary token overhead
  - stderr displays multi-stage progress events (scan_sessions, plan_chunks, summarize_chunks, etc.)

### Changed

- **Collect summary structure adjustment**
  - Session summaries now use structured JSON (10 fields) instead of free-text markdown
  - Output filename reverted to `agent-dump-collect-YYYYMMDD-YYYYMMDD.md` (customizable via `--save`)

### Improved

- Expanded test coverage for collect multi-stage progress and `--save` path resolution
- Improved test type safety using typed Session factories instead of mock objects

### Documentation

- Updated README/README_zh `--collect` description with multi-stage pipeline details and `--save` usage

### Dependencies

- Bump ruff 0.15.2 → 0.15.6, ty 0.0.18 → 0.0.23

### CI

- Added Cloudflare Pages deployment support and analytics tracking script (web landing page infrastructure, not visible to CLI users)

## [0.6.7] - 2026-03-10

### Changed

- **Collect summary pipeline**
  - `--collect` now summarizes each session first, then generates one final summary to avoid oversized prompts
  - Added configurable `[collect].summary_concurrency` for per-session summary fan-out
  - Shows session-summary progress from `0/N` on stderr during collect runs, with loading updates while AI requests are in flight
  - Writes collect reports as `agent-dump-collect-YYYYMMDD-YYYYMMDD.md`

## [0.6.6] - 2026-03-05

### Added

- **Collect summary mode**
  - Added `--collect` to gather session print content in a date range and summarize with AI
  - Added `-since/--since` and `-until/--until` date parameters (`YYYY-MM-DD` / `YYYYMMDD`)
  - Writes markdown report to terminal and `agent-dump-collect-YYYYMMDD.md` in current directory
- **Config management mode**
  - Added `--config view|edit` for AI config inspection and interactive editing
  - Added cross-platform config path resolution:
    - macOS/Linux: `~/.config/agent-dump/config.toml`
    - Windows: `%APPDATA%/agent-dump/config.toml`
  - Added config validation gates before running collect
- **URI summary mode**
  - Added `--summary` for URI mode AI summaries
  - Summary generation requires URI mode with `--format` including `json`
  - Falls back to warning-only behavior when config is missing/incomplete or AI requests fail

### Improved

- Expanded test coverage for collect date rules, collect output writing, config flow, and CLI mode dispatch

### Documentation

- Updated `skills/agent-dump/SKILL.md` and recipes with installation entrypoints and environment selection rules

### CI

- Staged native binaries in the release workflow

## [0.6.5] - 2026-03-03

### Added

- **Official agent data path discovery**
  - Supports `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, and `KIMI_SHARE_DIR`
  - Uses `XDG_DATA_HOME` on Unix and `LOCALAPPDATA` / `APPDATA` on Windows for OpenCode data discovery
  - Keeps fallback to home directories and local `data/` fixtures for development
- **npm wrapper and standalone native binaries**
  - Adds `bunx @agent-dump/cli` and `npx @agent-dump/cli` as no-Python entry points
  - Publishes platform-specific binaries for macOS, Linux, and Windows

### Changed

- **Release versioning and distribution pipeline**
  - Moves package version metadata to `src/agent_dump/__about__.py` as the single source of truth
  - Validates version parity between Git tags and package metadata during release builds
  - Uses a unified GitHub release workflow for PyPI publishing and native binary delivery

### Improved

- Expanded regression coverage for path resolution, CLI path reporting, and version consistency
- Added smoke tests and PyInstaller packaging adjustments for packaged binary installs

## [0.6.4] - 2026-03-02

### Added

- **Kimi total token extraction from raw session files**
  - Exports `stats.total_tokens` from the last `_usage.token_count` entry in `context.jsonl`
  - Falls back to `wire.jsonl` when `context.jsonl` is unavailable
  - Keeps `total_input_tokens` and `total_output_tokens` extraction from wire usage records

## [0.6.3] - 2026-03-01

### Added

- **Multi-format export and raw session output**
  - `--format` now supports comma-separated values such as `json,markdown,raw`
  - Added `raw` export support for all agents
  - Keeps `md` as a compatibility alias for `markdown`
- **Codex plan export reconstruction**
  - Extracts assistant `<proposed_plan>` blocks as structured `plan` parts
  - Merges the following user approval or rejection into `approval_status` and `output`
  - Hides consumed approval messages from exported conversations to avoid duplication

### Changed

- **Mode-specific format behavior**
  - URI mode can combine `print` with file exports like `print,json`
  - Interactive mode supports `json`, `markdown`, and `raw`, but rejects `print`
- **Codex skill wrapper export behavior**
  - Converts `<skill><name>...</name></skill>` user wrapper messages into assistant `tool=skill` entries in JSON export
  - Keeps non-JSON session data unchanged so text rendering still preserves the original payload

### Improved

- Expanded Codex regression coverage for plan approval handling and skill export conversion

## [0.6.2] - 2026-02-28

### Fixed

- **Codex response export deduplication**
  - Exports visible assistant `reasoning` and `text` content only from `response_item`
  - Prevents duplicate assistant thinking/commentary caused by mirrored `event_msg` records

### Changed

- **Codex `apply_patch` tool export shape**
  - Normalizes `custom_tool_call(name=apply_patch)` as `tool=patch`
  - Rebuilds patch input into per-file operation blocks under `state.arguments.content`
  - Uses diff text for file edits, final file content for new files, and empty content for delete/pure-move operations
  - Keeps raw patch text for debugging and preserves tool output backfilling by `call_id`

## [0.6.1] - 2026-02-28

### Added

- **Kimi parser support for `context.jsonl` sessions**
  - Supports Kimi's newer session storage layout
  - Normalizes tool titles and skips noisy `SetTodoList` tool entries

### Fixed

- **Codex export reconstruction**
  - Corrected exported timestamps for reconstructed messages and tool calls
  - Improved assistant/tool grouping so tool calls no longer attach to reasoning-only messages
- **Claude Code tool trace export**
  - Cleans tool traces in exported conversations
  - Backfills missing tool outputs when reconstructing assistant state

### Improved

- Expanded regression coverage for Kimi, Codex, and Claude Code session parsing
- Added `.uv-cache/` to `.gitignore`

## [0.6.0] - 2026-02-26

### Breaking Changes

- **CLI option syntax update for filter/paging flags**
  - `--days` -> `-days` (short alias `-d`)
  - `--query` -> `-query` (short alias `-q`)
  - `--page-size` -> `-page-size` (short alias `-p`)
  - `--list`, `--interactive`, `--output` keep double-dash style

### Added

- **Internationalization support (English/Chinese)**
  - New `--lang {en,zh}` option to force CLI language
  - Introduced centralized translation module for user-facing messages
- **Export format selection via `--format`**
  - Supports `json`, `md`, and `print`
  - Adds Markdown export path for session output

### Changed

- **Format defaults by mode**
  - URI mode defaults to `print`
  - Interactive/export workflows default to `json`
- **Python compatibility baseline**
  - Adjusted code paths to support Python `>=3.10`

### Improved

- **CI automation**
  - Added GitHub Actions workflow to run lint, type check, and tests
  - Expanded CI Python matrix coverage (3.10-3.14)

### Documentation

- Updated README/README_zh with new CLI option syntax and format usage examples
- Added Skills integration docs and CLI recipes under `skills/agent-dump/`

## [0.5.0] - 2026-02-24

### Added

- **Query filtering (`--query`)** across agents
  - Supports both `keyword` and `agent1,agent2:keyword` formats
  - Supports agent alias `claude` -> `claudecode`
  - Adds keyword matching on session title/content for faster targeting
- **Codex URI variant support**: `codex://threads/<session_id>`
  - `codex://threads/<id>` and `codex://<id>` now resolve to the same session

### Changed

- **List mode output behavior** (`--list`)
  - Now prints all matched sessions in one pass (no pagination prompts)
  - `--page-size` remains accepted for backward compatibility but is ignored in list mode

### Fixed

- **Message filtering in exports and URI text rendering**
  - Filters `developer` role messages
  - Filters injected context-like user messages (e.g. AGENTS/instructions/environment blocks)
  - Reduces prompt/context noise in exported session data

### Improved

- **Test coverage**
  - Added comprehensive CLI tests (URI parsing, list behavior, message filtering)
  - Added targeted tests for query filtering and Codex export filtering

## [0.4.0] - 2026-02-23

### Added

- **URI Mode** - Direct session text dump via agent session URIs
  - New command: `agent-dump <uri>` (e.g., `opencode://session-id`)
  - Supported URI schemes: `opencode://`, `codex://`, `kimi://`, `claude://`
  - Renders formatted session text with message content directly to terminal
  - Useful for quick inspection of session content without exporting to file
- **Agent Session URI Display** - Show URIs in CLI list and interactive selector
  - Each session now displays its unique URI for easy reference
  - Copy-paste friendly format for URI mode usage
- **Development Command** - Added `just isok` to run lint, check, and test in one command

### Fixed

- **Session Listing Interrupt Handling** - Properly handle quit and interrupt signals
  - Returns boolean from `display_sessions_list` to indicate user quit intent
  - Handles `EOFError` and `KeyboardInterrupt` as quit signals

## [0.3.0] - 2026-02-23

### Breaking Changes

- **CLI default behavior changed**: Running `agent-dump` without arguments now shows help instead of entering interactive mode
  - Use `--interactive` flag to enter interactive selection mode
  - Use `--days N` without other flags to auto-activate list mode

### Added

- **Pagination support** for list mode (`--list`)
  - New `--page-size` parameter to control sessions per page (default: 20)
  - Interactive pagination with "Press Enter to see more, or 'q' to quit"
- **Time-based grouping** in interactive mode
  - Sessions grouped by: Today, Yesterday, This Week, This Month, Earlier
  - Visual separators between time groups for easier navigation
- **Large session warning**: Shows warning when more than 100 sessions are found, suggesting to use `--days` to narrow the range

### Fixed

- **`--days` filter now works correctly in `--list` mode**
  - Previously showed all scanned sessions regardless of time filter
  - Now properly filters sessions based on the specified time range
- **Timezone compatibility**: Fixed datetime comparison errors between offset-naive and offset-aware datetimes
  - Claude Code and Codex agents use UTC-aware datetimes
  - OpenCode and Kimi agents use naive datetimes
  - All comparisons now normalized to UTC

### Improved

- Interactive agent selection now shows filtered session counts based on `--days` parameter
- Better user experience with clear prompts and navigation instructions

## [0.2.0] - 2026-02-22

### Added

- Multi-agent support with extensible architecture
  - Added `BaseAgent` abstract class and `Session` data model
  - Implemented agents for OpenCode, Codex, Kimi, and Claude Code
  - Added `AgentScanner` to discover available agents and sessions
  - Refactored CLI to support agent selection and unified export format
- Smart session title extraction for Claude Code and Codex
  - Claude Code: Use `sessions-index.json` metadata for titles when available
  - Codex: Use global state `thread-titles` cache for titles when available
  - Both: Fall back to message extraction if metadata not found

### Changed

- Replaced `inquirer` with `questionary` for interactive selection
- Reorganized project structure with `agents/` directory
- Removed old `db.py` and `exporter.py` modules in favor of agent-based approach
- Updated tests to work with new architecture

### Improved

- Error handling across all agents with try-catch blocks and descriptive messages
- Standardized imports with UTC timezone handling
- Fixed key binding safety checks in selector module
- Improved title extraction for Claude Code's content list format
- Used consistent file opening mode across all agents

## [0.1.0] - 2025-02-21

### Added

- Initial release of agent-dump
- Support for OpenCode session export
- Interactive session selection with questionary
- Export sessions to JSON format
- Command-line interface with multiple options
  - `--days` - Filter sessions by recent days
  - `--agent` - Specify AI tool name
  - `--output` - Custom output directory
  - `--list` - List sessions without exporting
  - `--export` - Export specific session IDs
- Full session data export including messages, tool calls, and metadata
- Support for `uv tool install` and `uvx` execution

[0.6.8]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.8
[0.6.9]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.9
[0.6.7]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.7
[0.6.6]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.6
[0.6.5]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.5
[0.6.4]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.4
[0.6.3]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.3
[0.6.2]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.2
[0.6.1]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.1
[0.6.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.0
[0.5.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.5.0
[0.4.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.4.0
[0.3.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.3.0
[0.2.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.2.0
[0.1.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.1.0
