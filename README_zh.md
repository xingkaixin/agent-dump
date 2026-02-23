![logo](https://raw.githubusercontent.com/xingkaixin/agent-dump/refs/heads/main/assets/logo.png)

# Agent Dump

AI 编码助手会话导出工具 - 支持从多种 AI 编码工具的会话数据导出会话为 JSON 格式。

## 支持的 AI 工具

- **OpenCode** - 开源 AI 编程助手
- **Claude Code** - Anthropic 的 AI 编码工具
- **Codex** - OpenAI 的命令行 AI 编码助手
- **Kimi** - Moonshot AI 助手
- **更多工具** - 欢迎提交 PR 支持其他 AI 编码工具

## 功能特性

- **交互式选择**: 使用 questionary 提供友好的命令行交互界面
- **多 Agent 支持**: 自动扫描多种 AI 工具的会话数据
- **批量导出**: 支持导出最近 N 天的所有会话
- **指定导出**: 通过会话 ID 导出特定会话
- **会话列表**: 仅列出会话而不导出
- **统计数据**: 导出包含 tokens 使用量、成本等统计信息
- **消息详情**: 完整保留会话消息、工具调用等详细信息
- **智能标题提取**: 从各 Agent 元数据中自动提取会话标题

## 安装

### 方式一：使用 uv tool 安装（推荐）

```bash
# 从 PyPI 安装（发布后可使用）
uv tool install agent-dump

# 从 GitHub 直接安装
uv tool install git+https://github.com/xingkaixin/agent-dump
```

### 方式二：使用 uvx 直接运行（无需安装）

```bash
# 从 PyPI 运行（发布后可使用）
uvx agent-dump --help

# 从 GitHub 直接运行
uvx --from git+https://github.com/xingkaixin/agent-dump agent-dump --help
```

### 方式三：本地开发

```bash
# 克隆仓库
git clone https://github.com/xingkaixin/agent-dump.git
cd agent-dump

# 使用 uv 安装依赖
uv sync

# 本地安装测试
uv tool install . --force
```

## 使用方法

### 交互式导出

```bash
# 进入交互模式选择和导出会话
uv run agent-dump --interactive

# 或使用模块运行
uv run python -m agent_dump --interactive
```

运行后会显示最近 7 天的会话列表，按时间分组显示（今天、昨天、本周、本月、更早）。使用空格选择/取消，回车确认导出。

> **注意：** 从 v0.3.0 开始，默认行为已更改。直接运行 `agent-dump` 将显示帮助信息，需要使用 `--interactive` 进入交互模式。

### 命令行参数

```bash
# 显示帮助
uv run agent-dump                             # 显示帮助信息
uv run agent-dump --help                      # 显示详细帮助

# 列表模式（支持分页）
uv run agent-dump --list                      # 列出最近 7 天的会话
uv run agent-dump --list --days 3             # 列出最近 3 天的会话
uv run agent-dump --list --page-size 10       # 每页显示 10 个会话

# 交互式导出模式
uv run agent-dump --interactive               # 交互模式（默认 7 天）
uv run agent-dump --interactive --days 3      # 交互模式（3 天）
uv run agent-dump --days 3                    # 自动启用列表模式

# 其他选项
uv run agent-dump --output ./my-sessions      # 指定输出目录
uv run agent-dump --export ses_abc,ses_xyz    # 导出指定会话 ID
```

### 完整参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--interactive` | 进入交互式模式选择和导出会话 | - |
| `--days` | 查询最近 N 天的会话 | 7 |
| `--list` | 仅列出会话不导出（若指定 `--days` 但未指定 `--interactive` 则自动启用） | - |
| `--page-size` | 列表模式下每页显示的会话数量 | 20 |
| `--output` | 输出目录 | ./sessions |
| `--export` | 导出指定会话 ID（逗号分隔） | - |
| `-h, --help` | 显示帮助信息 | - |

## 项目结构

```
.
├── src/
│   └── agent_dump/          # 主包目录
│       ├── __init__.py      # 包初始化
│       ├── __main__.py      # python -m agent_dump 入口
│       ├── cli.py           # 命令行接口
│       ├── scanner.py       # Agent 扫描器
│       ├── selector.py      # 交互式选择
│       └── agents/          # Agent 模块目录
│           ├── __init__.py  # Agent 导出
│           ├── base.py      # BaseAgent 抽象基类
│           ├── opencode.py  # OpenCode Agent
│           ├── claudecode.py # Claude Code Agent
│           ├── codex.py     # Codex Agent
│           └── kimi.py      # Kimi Agent
├── tests/                   # 测试目录
├── pyproject.toml           # 项目配置
├── justfile                 # 自动化命令
├── ruff.toml                # 代码风格配置
└── sessions/                # 导出目录
    └── {agent-name}/        # 按工具分类的导出文件
        └── ses_xxx.json
```

## Development

```bash
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

## 许可证

MIT
