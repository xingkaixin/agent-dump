# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.1.0
