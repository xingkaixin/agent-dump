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
- **会话统计**: `--stats` 查看按 Agent 和时间分组的会话使用统计
- **全文搜索**: 基于 SQLite FTS5 的本地全文搜索，覆盖标题、消息、reasoning 和 tool state (`--search`)

## 路径发现

`agent-dump` 按以下顺序解析会话数据根目录：官方环境变量 → 工具默认目录 → 本地开发回退路径 `data/<agent>`。

- **Codex**: `CODEX_HOME` -> `~/.codex` -> `data/codex`
- **Claude Code**: `CLAUDE_CONFIG_DIR` -> `~/.claude` -> `data/claudecode`
- **Kimi**: `KIMI_SHARE_DIR` -> `~/.kimi` -> `data/kimi`
- **OpenCode**: `XDG_DATA_HOME/opencode` -> Windows 数据目录 (`LOCALAPPDATA/opencode` 或 `APPDATA/opencode`) -> `~/.local/share/opencode` -> `data/opencode`

注意：

- Windows 上建议优先配置工具官方环境变量。
- `data/<agent>` 回退路径保留用于本地开发和测试。

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

`@agent-dump/cli` 会在安装阶段下载当前平台对应的原生二进制，并在落盘前校验发布时生成的 checksum。

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
- `codex://threads/<session_id>` - Codex 会话
- `kimi://<session_id>` - Kimi 会话
- `claude://<session_id>` - Claude Code 会话
- `cursor://<requestid>` - Cursor 会话（`requestid` 作为 URI 标识符）

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
uv run agent-dump --list -query 'bug provider:codex path:. limit:20'  # 结构化查询：关键词 + provider + path
uv run agent-dump --interactive -query 'role:user limit:20 refactor'  # 结构化查询带 role 和全局 limit
uv run agent-dump 'agents://.?q=refactor&providers=codex,claude'  # 查询当前仓库最近的相关会话
uv run agent-dump 'agents://.?q=refactor&providers=codex,claude&roles=user&limit=20'  # 结构化查询 URI
uv run agent-dump --list 'agents:///Users/me/work/repo?providers=codex,opencode'  # 按绝对路径查询
uv run agent-dump --interactive 'agents://~/work/repo?q=bug'  # 按路径作用域进入交互式选择
uv run agent-dump --list -page-size 10        # 参数保留兼容，当前在 --list 模式下不生效

# 交互式导出模式
uv run agent-dump --interactive               # 交互模式（默认 7 天）
uv run agent-dump --interactive -days 3       # 交互模式（3 天）
uv run agent-dump -days 3                     # 自动启用列表模式
uv run agent-dump -query 报错                 # 自动启用列表模式

# 说明：interactive + --query 时，Agent 列表仅显示命中关键词的工具，
#       且括号内会话数量为过滤后的命中数量。
#
# 查询歧义规则：
# - `error:timeout` 仍是纯关键词查询。
# - `codex,kimi:报错` 仍是旧版 agent 限定查询语法。
# - 仅当已知 key 出现时才激活结构化模式：provider / role / path / cwd / limit。
# - `role:...` 将关键词匹配限制在指定角色的消息中。
# - `limit:...` 截断最终全局匹配结果集，不是 per-agent 分页。

# URI 模式 - 直接查看会话内容
uv run agent-dump opencode://<session-id>     # 查看 OpenCode 会话内容
uv run agent-dump codex://<session-id>        # 查看 Codex 会话内容
uv run agent-dump kimi://<session-id>         # 查看 Kimi 会话内容
uv run agent-dump claude://<session-id>       # 查看 Claude Code 会话内容
uv run agent-dump cursor://<request-id>       # 查看 Cursor 会话内容
uv run agent-dump codex://<session-id> --head # 查看轻量会话元数据，不导出也不打印正文
uv run agent-dump codex://<session-id> --format json --output ./my-sessions  # 导出 JSON 文件
uv run agent-dump codex://<session-id> --format markdown --output ./my-sessions  # 导出 Markdown 文件
uv run agent-dump codex://<session-id> --format print,json --output ./my-sessions # 打印并导出 JSON
uv run agent-dump codex://<session-id> --format json,markdown,raw --output ./my-sessions  # 同时导出多种格式
uv run agent-dump cursor://<request-id> --format json --output ./my-sessions  # Cursor 支持 JSON 导出
uv run agent-dump cursor://<request-id> --format print,json --output ./my-sessions # Cursor 打印 + JSON
uv run agent-dump codex://<session-id> --format json --summary --output ./my-sessions  # 导出包含 AI summary 的 JSON
uv run agent-dump codex://<session-id> --format print,json --summary --output ./my-sessions # 打印并导出带 summary 的 JSON

# 搜索模式（全文搜索）
uv run agent-dump --search "auth timeout"           # 搜索匹配关键词的会话
uv run agent-dump --search "认证"                    # 支持 CJK 关键词搜索
uv run agent-dump --search "auth" --list -days 30   # 与 list + days 组合
uv run agent-dump --reindex                         # 强制重建搜索索引

# 统计模式
uv run agent-dump --stats                     # 显示最近 7 天会话统计
uv run agent-dump --stats -days 30            # 显示最近 30 天会话统计

# collect 模式（按时间段汇总并调用 AI 总结）
uv run agent-dump --collect
uv run agent-dump --collect -since 2026-03-01 -until 2026-03-05
uv run agent-dump --collect -since 20260301 -until 20260305
uv run agent-dump --collect --save ./reports
uv run agent-dump --collect --save ./reports/weekly.md
uv run agent-dump --collect --save /tmp/agent-dump-reports
uv run agent-dump --collect --save /tmp/agent-dump-reports/weekly.md
uv run agent-dump --collect 'agents://.?q=refactor&providers=codex,claude'
uv run agent-dump --shortcut ob 20260408

# 说明：--collect 会先把每条 session 转成高信号事件流，按预算切 chunk，
#       为每个 chunk 请求固定 JSON 结构摘要，再做 session 级 deterministic merge，
#       最后通过 tree reduction 聚合结构化结果，再交给 Markdown prompt。
# 说明：--collect 会在 stderr 输出多阶段进度，包括 scan_sessions、plan_chunks、
#       summarize_chunks、merge_sessions、tree_reduction、render_final、write_output。
# 说明：collect 输出文件名示例：agent-dump-collect-20260301-20260305.md。
# 说明：--save 接受目录或 .md 文件路径。缺失的非 .md 路径会被当作目录处理。

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
# --head 是 URI 发现模式，不能替代 --format print，也不能与 --format/--summary 组合。
```

### 完整参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `uri` | 用于直接查看的 Agent Session URI（如 `opencode://session-id`），或作用域查询 URI，如 `agents://.?q=refactor&providers=codex,claude&roles=user&limit=20` | - |
| `--interactive` | 进入交互式模式选择和导出会话 | - |
| `-d`, `-days` | 查询最近 N 天的会话 | 7 |
| `-q`, `-query` | 查询过滤。支持 legacy `keyword` 或 `agent1,agent2:keyword`（如 `codex,kimi:报错`），也支持结构化条件如 `bug provider:codex role:user path:. limit:20`。`cwd:` 是 `path:` 的别名。未知结构化 key 会被拒绝。不能与 `agents://...` 查询 URI 同时使用。 | - |
| `--head` | 仅 URI 模式。打印轻量会话元数据用于发现，不导出文件也不打印正文。不能与 `--format` 或 `--summary` 组合。 | - |
| `--collect` | 按日期范围采集会话 print 内容，可选通过 `agents://...` 查询 URI 约束范围。将会话转成高信号事件流，按固定 JSON schema 做 chunk 摘要，session 级 deterministic merge，再 tree-reduce 结构化结果生成最终 AI 总结。多阶段进度显示在 stderr。 | - |
| `--stats` | 显示最近 N 天会话使用统计，按 Agent 和时间分组。支持 `-days`。不能与其他模式同时使用。 | - |
| `--search` | 基于 SQLite FTS5 的本地全文搜索，覆盖会话标题、消息内容、reasoning 和 tool state。双分词器（`unicode61` + `trigram`）支持 CJK。索引过期或 FTS5 不可用时自动回退到文件扫描。可与 `--list` 组合。 | - |
| `--reindex` | 强制重建全文搜索索引。索引损坏或手动修改会话数据后使用。 | - |
| `--shortcut` | 运行已配置的快捷预设。示例：`agent-dump --shortcut ob 20260408` | - |
| `-since`, `--since` | collect 开始日期，支持 `YYYY-MM-DD` 或 `YYYYMMDD` | - |
| `-until`, `--until` | collect 结束日期，支持 `YYYY-MM-DD` 或 `YYYYMMDD` | - |
| `--save` | collect 输出路径。支持绝对/相对目录或 `.md` 文件路径。未提供文件名时使用默认 collect 文件名。 | - |
| `-config`, `--config` | 配置管理：`view` 或 `edit` | - |
| `--list` | 仅列出会话不导出，并输出全部匹配会话（若指定 `-days` 或 `-query` 且未指定 `--interactive` 则自动启用） | - |
| `-format`, `--format` | 输出格式。支持逗号分隔多值：`json \\| markdown \\| raw \\| print`，兼容 `md` 别名。默认：URI 模式为 `print`，非 URI 模式为 `json`。URI 模式可混用 `print,json`；`--interactive` 不支持 `print`；`--list` 下会警告并忽略；`--head` 不能与此选项组合。Cursor URI 仅支持 `json` 和 `print`（不支持 `raw/markdown`）。 | - |
| `-summary`, `--summary` | 仅 URI 模式生效。开启后仅在 `--format` 包含 `json` 且 AI 配置完整时生成 summary；否则仅 warning 并继续导出（不启用 summary）。AI 请求期间会在 stderr 显示 loading 提示。不能与 `--head` 组合。 | - |
| `-p`, `-page-size` | 为兼容保留，当前在 `--list` 模式下不生效 | 20 |
| `-output`, `--output` | 输出目录。`json/raw` 优先级：`--output` > `config.toml` `[export].output` > `./sessions`。相对路径从 agent-dump 执行目录解析。Markdown 仍使用 `./sessions`，除非显式传入 `--output`。`--list` 下会警告并忽略。 | `config export.output` 或 `./sessions` |
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

[collect]
summary_concurrency = 4

[export]
output = "../exports"

[shortcut.ob]
params = ["date"]
args = [
  "--collect",
  "--save", "~/Dropbox/OBSIDIAN/XingKaiXin/00_Inbox/{year}/{year_month}/agent-dump-collect-{date}.md",
  "--since", "{date}",
  "--until", "{date}",
]

[agent.claudecode]
deny = [
  "/Users/Kevin/workspace/projects/work/fin-agent/agent",
]
```

`[agent.<name>].deny` 仅对 `--collect` 生效。当会话 `cwd` 与配置路径匹配或位于该路径下时，collect 阶段会忽略该会话。

`[export].output` 定义 `json/raw` 导出的全局默认输出根目录。接受绝对或相对路径。相对路径从 `agent-dump` 执行目录解析，而非配置文件所在目录。

`[shortcut.<name>]` 定义可复用的快捷预设。`params` 声明位置输入名称。`args` 声明展开的 CLI argv 模板。提供 `date` 时，`{year}` / `{month}` / `{year_month}` 会自动派生。

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

## 发布

```bash
# 1. 在单一位置更新版本号
$EDITOR src/agent_dump/__about__.py

# 2. 提交并合并到 main

# 3. 创建并推送发布标签
git tag v{version}
git push origin v{version}
```

- 标签发布工作流为 [`release.yml`](./.github/workflows/release.yml)
- 仅匹配 `vX.Y.Z` 的标签会触发统一发布流水线
- 发布包含 PyPI 制品、GitHub Release 资产和 `@agent-dump/cli` npm 包
- npm CLI 包在 `npm`/`npx` 安装阶段会下载并校验匹配的原生二进制
- 在 GitHub `pypi` 环境中配置 `UV_PUBLISH_TOKEN`
- 在 GitHub `release` 环境中配置 `NPM_TOKEN`

## 许可证

MIT
