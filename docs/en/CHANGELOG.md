# Changelog

## [Unreleased]

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

[0.4.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.4.0
[0.3.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.3.0
[0.2.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.2.0
[0.1.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.1.0
