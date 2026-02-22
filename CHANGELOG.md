# Changelog

## [Unreleased]

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

[0.2.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.2.0
[0.1.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.1.0
