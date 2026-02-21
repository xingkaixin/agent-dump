# AGENTS.md

> 本文档用于帮助 AI Agents 快速理解本项目结构和开发规范

## 项目概述

**agent-dump** 是一个 AI 编码助手会话导出工具，支持从 OpenCode 等 AI 编码工具中导出会话数据为 JSON 格式。

- **语言**: Python 3.14+
- **包管理**: uv
- **代码规范**: Ruff
- **构建工具**: Hatchling

## 项目结构

```
agent-dump/
├── src/agent_dump/           # 主包目录
│   ├── __init__.py           # 包初始化，公开 API
│   ├── __main__.py           # python -m agent_dump 入口
│   ├── cli.py                # 命令行接口和参数解析
│   ├── db.py                 # 数据库连接和查询操作
│   ├── exporter.py           # JSON 导出逻辑
│   └── selector.py           # 交互式会话选择
├── tests/                    # 测试目录
│   ├── conftest.py          # 测试配置和共享 fixtures
│   ├── test_db.py           # 数据库模块测试
│   ├── test_exporter.py     # 导出功能测试
│   ├── test_selector.py     # 选择器测试
│   └── test_cli.py          # CLI 测试
├── data/opencode/            # 本地数据库
├── sessions/                 # 导出目录
├── pyproject.toml            # 项目配置
├── ruff.toml                 # 代码风格配置
└── Makefile                  # 自动化命令
```

## 核心模块

### cli.py
命令行入口模块，处理参数解析和主流程控制。

```python
from agent_dump.cli import main
# 主函数入口
main()
```

**关键函数:**
- `main()` - 主入口，处理参数解析和工作流调度

### db.py
数据库操作模块，处理 SQLite 数据库连接和查询。

**关键函数:**
- `find_db_path() -> Path` - 自动查找数据库路径
- `get_recent_sessions(db_path, days=7) -> List[Dict]` - 获取最近 N 天的会话

### exporter.py
导出逻辑模块，处理会话数据的 JSON 序列化。

**关键函数:**
- `export_session(db_path, session, output_dir) -> Path` - 导出单个会话
- `export_sessions(db_path, sessions, output_dir) -> List[Path]` - 批量导出

### selector.py
交互式选择模块，提供终端和简单两种选择模式。

**关键函数:**
- `select_sessions_interactive(sessions) -> List[Dict]` - 交互式选择（questionary）
- `select_sessions_simple(sessions) -> List[Dict]` - 简单选择（stdin）
- `is_terminal() -> bool` - 检查是否在终端环境

## 使用方式

### 命令行

```bash
# 开发时
uv run agent-dump                    # 交互式导出
uv run agent-dump --days 3           # 导出最近 3 天
uv run agent-dump --list             # 仅列出会话
uv run agent-dump --export id1,id2   # 指定 ID 导出

# 模块方式
uv run python -m agent_dump
```

### 作为库使用

```python
from agent_dump import find_db_path, get_recent_sessions, export_session
from pathlib import Path

# 查找数据库
db_path = find_db_path()

# 获取最近 7 天的会话
sessions = get_recent_sessions(db_path, days=7)

# 导出第一个会话
output_dir = Path("./my-sessions")
export_session(db_path, sessions[0], output_dir)
```

## 开发规范

### 代码风格
- 使用 Ruff 进行代码检查和格式化
- 配置位于 `ruff.toml`
- 单行最大长度 100
- 使用双引号

### 命令

```bash
# 代码检查
make lint          # ruff check
make lint.fix      # ruff check --fix
make lint.fmt      # ruff format

# 类型检查（待配置）
make check         # ty check

# 测试
uv run pytest              # 运行所有测试
uv run pytest -v          # 详细输出
uv run pytest -k "test_name"  # 运行特定测试
```

### 添加依赖

```bash
# 生产依赖
uv add package-name

# 开发依赖
uv add --dev package-name
```

## 扩展指南

### 支持新的 AI 工具

要支持新的 AI 编码工具（如 Claude Code、Copilot Chat）：

1. **在 `db.py` 中添加新工具的数据库查找路径**

```python
def find_db_path():
    paths = [
        # OpenCode
        os.path.expanduser("~/.local/share/opencode/opencode.db"),
        # 新工具
        os.path.expanduser("~/.config/newtool/database.db"),
    ]
```

2. **在 `cli.py` 中添加新的 agent 选项**

```python
parser.add_argument(
    "--agent",
    type=str,
    default="opencode",
    choices=["opencode", "newtool"],  # 添加新选项
    help="Agent tool name",
)
```

3. **如有需要，创建新的数据解析模块**

如果新工具的数据库结构与 OpenCode 不同，建议：
- 创建 `parsers/` 子目录
- 为每个工具创建解析器类
- 在 `exporter.py` 中根据 agent 类型选择解析器

### 添加新的导出格式

1. 在 `exporter.py` 中创建新的导出函数
2. 在 `cli.py` 中添加格式选项

```python
# exporter.py
def export_session_markdown(db_path, session, output_dir) -> Path:
    """导出为 Markdown 格式"""
    # 实现导出逻辑
    pass
```

## 数据库结构

### OpenCode 数据库表

```sql
-- session 表
CREATE TABLE session (
    id TEXT PRIMARY KEY,
    title TEXT,
    time_created INTEGER,  -- 毫秒时间戳
    time_updated INTEGER,
    slug TEXT,
    directory TEXT,
    version INTEGER,
    summary_files TEXT
);

-- message 表
CREATE TABLE message (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    time_created INTEGER,
    data TEXT  -- JSON 格式
);

-- part 表
CREATE TABLE part (
    id TEXT PRIMARY KEY,
    message_id TEXT,
    time_created INTEGER,
    data TEXT  -- JSON 格式
);
```

## 注意事项

1. **数据库路径**: `find_db_path()` 会尝试多个路径，新工具需要添加对应路径
2. **时间戳**: 数据库存储的是毫秒时间戳，Python datetime 需要转换
3. **JSON 数据**: message 和 part 表中的 data 字段是 JSON 字符串
4. **交互模式**: `selector.py` 会根据是否在终端自动选择合适的模式

## 发布

```bash
# 构建包
uv build

# 发布到 PyPI
uv publish
```

## 相关文件

- `pyproject.toml` - 项目配置和依赖
- `ruff.toml` - 代码风格配置
- `README.md` - 用户文档（中文）
- `Makefile` - 自动化命令
