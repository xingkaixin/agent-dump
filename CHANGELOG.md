# Changelog

[中文](docs/zh/CHANGELOG.md)

## [0.7.0] - 2026-04-18

### Added

- **`--stats` session usage statistics**
  - Added `--stats` mode to show session usage statistics for the last N days
  - Dimensions include: total sessions, total messages (when available), grouped by agent, and grouped by time (Today, Yesterday, This Week, This Month, Earlier)
  - Supports `-days` parameter to adjust the statistics time range

- **Concurrent scanner**
  - Agent availability checks and session scanning are now concurrent, significantly reducing scan time in multi-agent scenarios
  - URI session lookup is also concurrent, reducing single-URI resolution latency

- **Kimi project path resolution**
  - Kimi agent now reads project info from `kimi.json` to resolve project hashes into real cwd paths
  - Improves path display and filtering accuracy for Kimi sessions in `--collect` and `--list`

### Improved

- **Test type safety**
  - Removed redundant `# type: ignore` comments in scanner concurrent tests

### Changed

- **Build environment upgrade**
  - Release pipeline Node.js upgraded to v24
  - npm package publishing now enables provenance for supply-chain trust

- **Development config**
  - Added `.worktree` to `.gitignore`

## [0.6.20] - 2026-04-12

### Added

- **Lightweight session metadata preview with `--head`**
  - Added a dedicated `--head` URI mode that prints lightweight session metadata without rendering full session content or exporting files
  - Added shared agent hooks and metadata extraction for fields such as model, message count, cwd/project, and subtargets
  - Added CLI validation and regression coverage for `--head` interactions with `--format` and `--summary`

- **Richer query capabilities across CLI and URI flows**
  - Added scoped `agents://<path>?q=<keyword>&providers=<names>` query URIs so path-constrained filtering works across list, interactive, and collect modes
  - Added structured query syntax with `provider:`, `role:`, `path:`, and `limit:` filters while keeping legacy query behavior compatible
  - Added coverage for scoped and structured query parsing and filtering

- **Configurable default output directory for JSON/raw exports**
  - Added `[export].output` in `config.toml` as the default output directory for JSON and raw exports
  - Output directory precedence is now `--output` > config > `./sessions`, while markdown keeps using `./sessions` unless explicitly overridden

### Changed

- **Session listing metadata is now extracted more directly**
  - Added lightweight summary-field extraction for session listings so CLI and selector views can show better metadata without fully loading sessions
  - Improved listing output for supported agents with fields such as message count and model when available

- **Session title fallback is now consistent across agents**
  - Extracted shared title normalization and fallback resolution into a dedicated module
  - Claude Code and Codex now follow the same explicit → message → directory fallback chain for more stable titles

- **Error diagnostics are now structured and actionable**
  - Replaced opaque failure lines with structured diagnostics that expose candidate search roots, failure reasons, and next-step guidance
  - Updated agents to report searchable roots so CLI errors can explain what was checked instead of only reporting failure

### Fixed

- **Invalid structured query errors are clearer**
  - Refined the invalid query message wording and included explicit next-step guidance in the CLI output

## [0.6.19] - 2026-04-10

### Added

- **CLI shortcut presets for common workflows**
  - Added shortcut preset expansion so common CLI workflows can be invoked with shorter preset-style inputs
  - Added config and CLI coverage for preset parsing and expansion behavior

### Changed

- **Collect progress reporting now includes workload overview**
  - Added a collect start summary that reports session count, chunk count, configured concurrency, and agent distribution before summary work begins
  - Refined progress output to be more readable and contextual during collect runs, including TTY spinner cleanup before overview printing

- **Query filter now avoids redundant session-data scans**
  - When the source file is already directly searchable, query filtering now skips the fallback session-data search path
  - Added regression coverage for the new query filter behavior

## [0.6.18] - 2026-04-05

### Fixed

- **Cursor empty-message placeholders removed**
  - Stop emitting synthetic `[empty message]` entries for Cursor assistant bubbles that contain only whitespace and no tool/plan/text payload
  - This fixes both JSON export and `--format print` output so Cursor sessions no longer contain placeholder messages that were never part of the original conversation

### Changed

- **Cursor subagent export now preserves event ordering**
  - Export Cursor subagent calls as their own tool events at the original parent-turn timestamp instead of folding everything into one merged record
  - Append the subagent's final visible assistant output as a later standalone message at its real completion timestamp, preserving interleaving with other parent-session turns
  - Record subagent `prompt`, `model`, `subagent_type`, and `subagent_id` when available, while continuing to omit the subagent's internal intermediate steps

## [0.6.17] - 2026-04-03

### Added

- **CLI version flag**
  - Added `-v` / `--version` so the CLI can print the current `agent-dump` version and exit immediately
  - Added CLI coverage for the new version output path

### Changed

- **Timestamp normalization and local-time display**
  - Normalize parsed session timestamps to UTC internally before any downstream formatting or comparison
  - Display session times in the user's local timezone in CLI listing and interactive selection flows
  - Added regression coverage for timezone-aware formatting across shared agent parsing and selector/CLI output

## [0.6.16] - 2026-04-02

### Fixed

- **JSON export now creates missing output directories**
  - Made `export_session()` create the target output directory for Claude Code, Codex, Kimi, and OpenCode exports before writing JSON
  - Fixed URI-mode JSON exports such as `agent-dump claude://... --format json --output <path>` failing when the target `<path>/<agent>` directory did not already exist
  - Added regression coverage for both agent-level exports and CLI URI exports targeting previously missing directories

## [0.6.15] - 2026-03-31

### Fixed

- **npm wrapper runtime binary recovery**
  - Made `@agent-dump/cli` recover the vendored native binary at runtime when `vendor/<target>/agent-dump` is missing, instead of assuming installation hooks already populated it
  - Fixed `bunx @agent-dump/cli` failures where Bun left the main package installed but did not provide the vendored binary before first run

### CI

- **Release binary staging validation**
  - Added a release-time validation step to fail publishing if staged npm platform binaries are missing, empty, or staged as text stubs instead of native executables

## [0.6.14] - 2026-03-31

### Fixed

- **Windows npm wrapper installation reliability**
  - Reworked `@agent-dump/cli` to install the matching native binary into the main package during `npm`/`npx` installation instead of relying on platform `optionalDependencies`
  - Fixed Windows `npx @agent-dump/cli` failures where `@agent-dump/cli-win32-x64/package.json` could not be resolved on real installs
  - Added checksum generation and verification for native npm binaries during release and install flows

## [0.6.13] - 2026-03-31

### Added

- **Agent registry for centralized agent metadata**
  - Introduced `AgentRegistration` dataclass and a single `AGENT_REGISTRATIONS` tuple as the source of truth for all agent names, factories, URI schemes, and help text
  - Replaced scattered agent setup logic in CLI with registry-based helpers (`create_registered_agents`, `get_uri_scheme_map`, etc.)

### Changed

- **Collect mode module decomposition**
  - Extracted LLM HTTP transport into `collect_llm` (OpenAI/Anthropic request functions)
  - Extracted shared data models and constants into `collect_models`
  - Extracted workflow orchestration into `collect_workflow` with explicit dependency injection via `CollectWorkflowDeps`
- **CLI and rendering module separation**
  - Extracted session rendering and export logic into `rendering` module
  - Extracted URI parsing and session lookup into `uri_support` module
  - Simplified `cli.py` by delegating to the new focused modules

## [0.6.12] - 2026-03-26

### Added

- **Collect diagnostic logging and timeout configuration**
  - Added append-only JSONL diagnostics for collect runs, with a default log path under the config directory
  - Added `summary_timeout_seconds` to collect config so LLM summary requests can be tuned without code changes
  - Added `[logging]` config support to enable/disable collect diagnostics and override the log file path

## [0.6.11] - 2026-03-23

### Added

- **Cursor agent support across CLI and scanner**
  - Added `cursor` as a first-class agent option in CLI workflows and session scanning
  - Added Cursor coverage in README usage docs
- **Cursor request-id URI retrieval**
  - Cursor sessions can now be loaded by request-id style identifiers in URI flows

### Changed

- **Cursor session parsing quality**
  - Improved session title formatting for better readability
  - Refined message extraction and ordering behavior in Cursor conversations
- **Web landing page presentation**
  - Updated UI copy, structure, and styling for clearer product communication

### Fixed

- **Cursor session availability and ordering**
  - Streamlined session availability checks to avoid false positives in listing/export paths
  - Improved message sorting consistency during Cursor session rendering/export

## [0.6.10] - 2026-03-23

### Added

- **Codex subagent export support**
  - Treat `spawn_agent` as a `subagent` tool in unified JSON export and attach returned `subagent_id` / `nickname`
  - Convert `<subagent_notification>...</subagent_notification>` user payloads into assistant messages with matching subagent metadata
  - Render Codex subagent calls and final outputs in `--format print` as `Assistant (nickname)` messages
  - Filter Codex `wait_agent` tool parts from JSON export only, without changing raw parsing or other formats

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

[0.6.16]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.16
[0.6.13]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.13
[0.6.12]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.12
[0.6.10]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.10
[0.6.11]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.11
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
