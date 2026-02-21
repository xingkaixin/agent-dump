![logo](https://raw.githubusercontent.com/xingkaixin/agent-dump/refs/heads/main/assets/logo.png)

# Agent Dump

AI 编码助手会话导出工具 - 支持从多种 AI 编码工具的会话数据导出会话为 JSON 格式。

## 支持的 AI 工具

- **OpenCode** - 开源 AI 编程助手
- **Claude Code** - Anthropic 的 AI 编码工具 *(计划中)*
- **Code X** - GitHub Copilot Chat *(计划中)*
- **更多工具** - 欢迎提交 PR 支持其他 AI 编码工具

## 功能特性

- **交互式选择**: 使用 questionary 提供友好的命令行交互界面
- **批量导出**: 支持导出最近 N 天的所有会话
- **指定导出**: 通过会话 ID 导出特定会话
- **会话列表**: 仅列出会话而不导出
- **统计数据**: 导出包含 tokens 使用量、成本等统计信息
- **消息详情**: 完整保留会话消息、工具调用等详细信息

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

### 交互式导出（默认）

```bash
# 方式一：使用命令行入口
uv run agent-dump

# 方式二：使用模块运行
uv run python -m agent_dump
```

运行后会显示最近 7 天的会话列表，使用空格选择/取消，回车确认导出。

### 命令行参数

```bash
uv run agent-dump --days 3                    # 导出最近 3 天的会话
uv run agent-dump --agent claude              # 指定 Agent 工具名称
uv run agent-dump --output ./my-sessions      # 指定输出目录
uv run agent-dump --list                      # 仅列出会话
uv run agent-dump --export ses_abc,ses_xyz    # 导出指定 ID 的会话
```

### 完整参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--days` | 查询最近 N 天的会话 | 7 |
| `--agent` | Agent 工具名称 | opencode |
| `--output` | 输出目录 | ./sessions |
| `--export` | 导出指定会话 ID（逗号分隔） | - |
| `--list` | 仅列出会话，不导出 | - |

## 项目结构

```
.
├── src/
│   └── agent_dump/      # 主包目录
│       ├── __init__.py  # 包初始化
│       ├── __main__.py  # python -m agent_dump 入口
│       ├── cli.py       # 命令行接口
│       ├── db.py        # 数据库操作
│       ├── exporter.py  # 导出逻辑
│       └── selector.py  # 交互式选择
├── tests/               # 测试目录
├── pyproject.toml       # 项目配置
├── Makefile            # 自动化命令
├── ruff.toml           # 代码风格配置
├── data/               # 数据库目录
│   └── opencode/
│       └── opencode.db
└── sessions/           # 导出目录
    └── {agent-name}/   # 按工具分类的导出文件
        └── ses_xxx.json
```

## 开发

```bash
# 代码检查
make lint

# 自动修复
make lint.fix

# 代码格式化
make lint.fmt

# 类型检查
make check
```

## 依赖

- Python >= 3.14
- prompt-toolkit >= 3.0.0
- questionary >= 2.1.1
- ruff >= 0.15.2 (开发)
- ty >= 0.0.18 (开发)

## 许可证

MIT
