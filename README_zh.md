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
- **直接文本查看**: 通过 URI 直接在终端查看会话内容（如 `agent-dump opencode://session-id`）
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

### 方式三：使用 bunx / npx 直接运行（无需 Python）

```bash
# 从 npm 直接运行
bunx @agent-dump/cli --help
npx @agent-dump/cli --help
```

当前支持的平台：

- `darwin-x64`
- `darwin-arm64`
- `linux-x64`
- `win32-x64`

若平台暂不支持，wrapper 会输出当前检测到的 `platform/arch`，并提示前往 GitHub Releases 页面。

### 方式四：本地开发

```bash
# 克隆仓库
git clone https://github.com/xingkaixin/agent-dump.git
cd agent-dump

# 使用 uv 安装依赖
uv sync

# 本地安装测试
uv tool install . --force
```

### 方式五：安装为 Skill 使用

```bash
npx skills add xingkaixin/agent-dump
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

### URI 模式（直接文本查看）

无需导出文件，直接在终端查看会话内容：

```bash
# 通过 URI 查看指定会话
uv run agent-dump opencode://session-id-abc123

# URI 格式在列表模式和交互选择器中显示
#   • 会话标题 (opencode://session-id-abc123)
```

支持的 URI 协议：
- `opencode://<session_id>` - OpenCode 会话
- `codex://<session_id>` - Codex 会话  
- `codex://thread/<session_id>` - Codex 会话  
- `kimi://<session_id>` - Kimi 会话
- `claude://<session_id>` - Claude Code 会话

### 命令行参数

```bash
# 显示帮助
uv run agent-dump                             # 显示帮助信息
uv run agent-dump --help                      # 显示详细帮助

# 列表模式（输出全部匹配内容，不分页）
uv run agent-dump --list                      # 列出最近 7 天的会话
uv run agent-dump --list -days 3              # 列出最近 3 天的会话
uv run agent-dump --list -query 报错          # 列出匹配关键词“报错”的会话
uv run agent-dump --list -query codex,kimi:报错  # 仅在 Codex/Kimi 范围内查询
uv run agent-dump --list -page-size 10        # 参数保留兼容，当前在 --list 模式下不生效

# 交互式导出模式
uv run agent-dump --interactive               # 交互模式（默认 7 天）
uv run agent-dump --interactive -days 3       # 交互模式（3 天）
uv run agent-dump -days 3                     # 自动启用列表模式
uv run agent-dump -query 报错                 # 自动启用列表模式

# 说明：interactive + --query 时，Agent 列表仅显示命中关键词的工具，
#       且括号内会话数量为过滤后的命中数量。

# URI 模式 - 直接查看会话内容
uv run agent-dump opencode://<session-id>     # 查看 OpenCode 会话内容
uv run agent-dump codex://<session-id>        # 查看 Codex 会话内容
uv run agent-dump kimi://<session-id>         # 查看 Kimi 会话内容
uv run agent-dump claude://<session-id>       # 查看 Claude Code 会话内容
uv run agent-dump codex://<session-id> --format json --output ./my-sessions  # 导出 JSON 文件
uv run agent-dump codex://<session-id> --format markdown --output ./my-sessions  # 导出 Markdown 文件
uv run agent-dump codex://<session-id> --format print,json --output ./my-sessions # 打印并导出 JSON
uv run agent-dump codex://<session-id> --format json,markdown,raw --output ./my-sessions  # 同时导出多种格式
uv run agent-dump codex://<session-id> --format json --summary --output ./my-sessions  # 导出包含 AI summary 的 JSON
uv run agent-dump codex://<session-id> --format print,json --summary --output ./my-sessions # 打印并导出带 summary 的 JSON

# collect 模式（按时间段汇总并调用 AI 总结）
uv run agent-dump --collect
uv run agent-dump --collect -since 2026-03-01 -until 2026-03-05
uv run agent-dump --collect -since 20260301 -until 20260305

# 配置模式
uv run agent-dump --config view
uv run agent-dump --config edit

# 其他选项
uv run agent-dump --interactive --format json # 交互式导出 JSON（默认）
uv run agent-dump --interactive --format markdown   # 交互式导出 Markdown
uv run agent-dump --interactive --format json,markdown,raw # 交互式多格式导出
uv run agent-dump --interactive -output ./my-sessions  # 指定输出目录

# 兼容说明
# md 仍可作为 markdown 的别名使用，例如：--format md,raw
```

### 完整参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `uri` | Agent Session URI 用于直接查看（如 `opencode://session-id`） | - |
| `--interactive` | 进入交互式模式选择和导出会话 | - |
| `-d`, `-days` | 查询最近 N 天的会话 | 7 |
| `-q`, `-query` | 查询过滤。支持 `keyword` 或 `agent1,agent2:keyword`（如 `codex,kimi:报错`） | - |
| `--collect` | 按日期范围采集会话 print 内容并调用 AI 总结 | - |
| `-since`, `--since` | collect 开始日期，支持 `YYYY-MM-DD` 或 `YYYYMMDD` | - |
| `-until`, `--until` | collect 结束日期，支持 `YYYY-MM-DD` 或 `YYYYMMDD` | - |
| `-config`, `--config` | 配置管理：`view` 或 `edit` | - |
| `--list` | 仅列出会话不导出，并输出全部匹配会话（若指定 `-days` 或 `-query` 且未指定 `--interactive` 则自动启用） | - |
| `-format`, `--format` | 输出格式。支持逗号分隔多值：`json \\| markdown \\| raw \\| print`，兼容 `md` 别名。默认：URI 模式为 `print`，非 URI 模式为 `json`。URI 模式可混用 `print,json`；`--interactive` 不支持 `print`；`--list` 下会警告并忽略。 | - |
| `-summary`, `--summary` | 仅 URI 模式生效。开启后仅在 `--format` 包含 `json` 且 AI 配置完整时生成 summary；否则仅 warning 并继续导出（不启用 summary）。 | - |
| `-p`, `-page-size` | 为兼容保留，当前在 `--list` 模式下不生效 | 20 |
| `-output`, `--output` | 输出目录。`--interactive` 可用；URI 模式在包含任意文件导出格式（`json/markdown/raw`）时生效；`--list` 下会警告并忽略。 | ./sessions |
| `-h, --help` | 显示帮助信息 | - |

### collect 配置文件

默认配置文件路径：

- macOS/Linux: `~/.config/agent-dump/config.toml`
- Windows: `%APPDATA%/agent-dump/config.toml`

配置示例：

```toml
[ai]
provider = "openai" # openai | anthropic
base_url = "https://api.openai.com/v1"
model = "gpt-4.1-mini"
api_key = "sk-..."
```

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
# 运行所有检查（lint、类型检查、测试）
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

# 构建当前平台原生二进制
just build-native

# 同步 npm 包版本
just build-npm

# 运行 npm wrapper 测试和 smoke 检查
just test-npm-smoke
```

## 许可证

MIT
