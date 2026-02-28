# Changelog

## [Unreleased]

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

[0.6.2]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.2
[0.6.1]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.1
[0.6.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.0
[0.5.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.5.0
[0.4.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.4.0
[0.3.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.3.0
[0.2.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.2.0
[0.1.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.1.0
