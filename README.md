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

### Method 3: Local Development

```bash
# Clone the repository
git clone https://github.com/xingkaixin/agent-dump.git
cd agent-dump

# Use uv to install dependencies
uv sync

# Local installation test
uv tool install . --force
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
- `codex://thread/<session_id>` - Codex sessions
- `kimi://<session_id>` - Kimi sessions
- `claude://<session_id>` - Claude Code sessions

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
uv run agent-dump --list -page-size 10        # Accepted but currently ignored in --list mode

# Interactive export mode
uv run agent-dump --interactive               # Interactive mode (default 7 days)
uv run agent-dump --interactive -days 3       # Interactive mode (3 days)
uv run agent-dump -days 3                     # Auto-activates list mode
uv run agent-dump -query error                # Auto-activates list mode

# Note: in interactive mode with --query, only agents with keyword matches are shown,
#       and the count shown for each agent is the post-filter matched count.

# URI mode - Direct text dump
uv run agent-dump opencode://<session-id>     # View OpenCode session content
uv run agent-dump codex://<session-id>        # View Codex session content
uv run agent-dump kimi://<session-id>         # View Kimi session content
uv run agent-dump claude://<session-id>       # View Claude Code session content

# Other options
uv run agent-dump --output ./my-sessions      # Specify output directory
uv run agent-dump --export ses_abc,ses_xyz    # Export specific session IDs
```

### Full Parameter Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `uri` | Agent session URI to dump (e.g., `opencode://session-id`) | - |
| `--interactive` | Run in interactive mode to select and export sessions | - |
| `-d`, `-days` | Query sessions from the last N days | 7 |
| `-q`, `-query` | Query filter. Supports `keyword` or `agent1,agent2:keyword` (e.g. `codex,kimi:error`) | - |
| `--list` | Only list sessions without exporting and print all matched sessions (auto-activated if `-days` or `-query` is specified without `--interactive`) | - |
| `-p`, `-page-size` | Accepted for compatibility; currently ignored in `--list` mode | 20 |
| `--output` | Output directory | ./sessions |
| `--export` | Export specific session IDs (comma-separated) | - |
| `-h, --help` | Show help message | - |

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
```

## License

MIT
