![logo](https://raw.githubusercontent.com/xingkaixin/agent-dump/refs/heads/main/assets/logo.png)

# Agent Dump

AI Coding Assistant Session Export Tool - Supports exporting session data from multiple AI coding tools to JSON format.

## Supported AI Tools

- **OpenCode** - Open source AI coding assistant
- **Claude Code** - Anthropic's AI coding tool *(Planned)*
- **Code X** - GitHub Copilot Chat *(Planned)*
- **More Tools** - PRs are welcome to support other AI coding tools

## Features

- **Interactive Selection**: Provides a friendly command-line interactive interface using questionary
- **Batch Export**: Supports exporting all sessions from the last N days
- **Specific Export**: Export specific sessions by session ID
- **Session List**: Only list sessions without exporting them
- **Statistics**: Exports include statistics such as token usage and cost
- **Message Details**: Fully retains session messages, tool calls, and other details

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

### Interactive Export (Default)

```bash
# Option 1: Use the command-line entry point
uv run agent-dump

# Option 2: Run as a module
uv run python -m agent_dump
```

After running, it will display the list of sessions from the last 7 days. Use the spacebar to select/deselect, and press Enter to confirm the export.

### Command-line Arguments

```bash
uv run agent-dump --days 3                    # Export sessions from the last 3 days
uv run agent-dump --agent claude              # Specify the Agent tool name
uv run agent-dump --output ./my-sessions      # Specify the output directory
uv run agent-dump --list                      # Only list sessions
uv run agent-dump --export ses_abc,ses_xyz    # Export sessions with specific IDs
```

### Full Parameter Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--days` | Query sessions from the last N days | 7 |
| `--agent` | Agent tool name | opencode |
| `--output` | Output directory | ./sessions |
| `--export` | Export specific session IDs (comma-separated) | - |
| `--list` | Only list sessions, do not export | - |

## Project Structure

```text
.
├── src/
│   └── agent_dump/      # Main package directory
│       ├── __init__.py  # Package initialization
│       ├── __main__.py  # python -m agent_dump entry point
│       ├── cli.py       # Command-line interface
│       ├── db.py        # Database operations
│       ├── exporter.py  # Export logic
│       └── selector.py  # Interactive selection
├── tests/               # Test directory
├── pyproject.toml       # Project configuration
├── Makefile            # Automated commands
├── ruff.toml           # Code style configuration
├── data/               # Database directory
│   └── opencode/
│       └── opencode.db
└── sessions/           # Export directory
    └── {agent-name}/   # Exported files categorized by tool
        └── ses_xxx.json
```

## Development

```bash
# Lint code
make lint

# Auto-fix linting issues
make lint.fix

# Format code
make lint.fmt

# Type checking
make check
```

## Dependencies

- Python >= 3.14
- prompt-toolkit >= 3.0.0
- questionary >= 2.1.1
- ruff >= 0.15.2 (Development)
- ty >= 0.0.18 (Development)

## License

MIT
