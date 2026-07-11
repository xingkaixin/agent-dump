# AGENTS.md

> 本文档用于帮助 AI Agents 快速理解本项目结构、开发规范和行为约束

## 1. Agent 行为约束（必读）

以下约束适用于所有自动化修改，防止过度优化或破坏性变更。

### 1.1 API 稳定性约束

- **不得破坏公开 API**：`__init__.py` 导出的符号集合必须保持稳定
- **不得删除或重命名已导出的函数/类**：如需变更，保留旧接口并标记 `@deprecated`
- **CLI 行为变更必须同步更新测试**：参数、输出格式、退出码的修改需配套更新 `test_cli.py`
- **默认行为必须向后兼容**：新增功能默认关闭，不得改变现有执行路径

### 1.2 代码质量约束

- **所有新增函数必须补充测试**：单元测试覆盖核心逻辑，mock 测试覆盖 CLI 交互
- **不允许随意新增第三方依赖**：如需添加，必须在代码注释中说明必要性
- **不得引入循环导入**：模块间依赖保持单向
- **类型注解必须完整**：函数参数和返回值需标注类型

### 1.3 数据安全约束

- **Provider 数据源只读访问**：导出、搜索、统计、collect 均只读取本地会话源
- **Provider schema 只在对应 Agent 内处理**：OpenCode/ZCode/Cursor 的 SQLite 细节、JSONL provider 的文件结构都封装在各自 Agent
- **不得删除或修改用户数据**：禁止对用户会话目录、数据库、JSONL 源文件执行写入或清理
- **临时文件必须清理**：使用 `tempfile` 模块并确保清理

### 1.4 架构边界约束

- **cli.py 只负责参数解析和工作流调度**：业务逻辑必须下沉到具体模块
- **Provider 读取逻辑禁止写入 cli.py**：所有会话发现、读取、导出实现封装在 `BaseAgent` 子类
- **UI 逻辑与业务逻辑分离**：selector 层不得直接操作数据库或文件系统
- **跨模式共享逻辑进入 cli_shared.py**：URI、format、渲染、导出调度等复用入口集中维护

---

## 2. 公共接口声明（Public API Surface）

以下接口由 `src/agent_dump/__init__.py` 的 `__all__` 定义，属于稳定公开 API。变更时必须保持向后兼容，并同步更新本节、README 与测试。

### 2.1 稳定公开 API（Stable Public API）

| 符号 | 来源模块 | 说明 |
|------|----------|------|
| `__version__` | `agent_dump.__about__` | 包版本号，单一版本源 |
| `AgentScanner` | `agent_dump.scanner` | 按 registry 创建并扫描所有 provider |
| `BaseAgent` | `agent_dump.agents.base` | Provider 实现的抽象基类 |
| `Session` | `agent_dump.agents.base` | 统一会话数据模型 |
| `OpenCodeAgent` | `agent_dump.agents.opencode` | OpenCode provider |
| `ZCodeAgent` | `agent_dump.agents.zcode` | ZCode provider |
| `CodexAgent` | `agent_dump.agents.codex` | Codex provider |
| `KimiAgent` | `agent_dump.agents.kimi` | Kimi provider |
| `ClaudeCodeAgent` | `agent_dump.agents.claudecode` | Claude Code provider |
| `CursorAgent` | `agent_dump.agents.cursor` | Cursor provider |
| `PiAgent` | `agent_dump.agents.pi` | Pi provider |

### 2.2 内部实现（Internal Implementation）

以下模块是当前实现边界，外部调用方应优先使用上表公开 API 或 CLI：

| 模块 | 职责 |
|------|------|
| `agent_registry.py` | 注册 provider、URI scheme、用户可见路径说明 |
| `cli.py` | 参数解析、模式选择、依赖装配 |
| `cli_shared.py` | CLI 共享能力：URI、format、导出调度、诊断渲染 |
| `session_workflow.py` | list / interactive / query 会话工作流 |
| `uri_workflow.py` | 单 URI 查看、head、summary、单会话导出 |
| `collect_workflow.py` | collect 模式编排、dry-run、保存路径解析 |
| `maintenance_workflow.py` | stats 与 reindex 模式 |
| `rendering.py` | print/head/markdown 渲染与 format 导出分发 |
| `query_filter.py` | `-query` 与 `agents://` 查询 URI 解析、过滤、搜索匹配 |
| `search_index.py` | SQLite FTS5 搜索索引 |
| `selector.py` | 终端交互选择与非 TTY 输入回退 |
| `config.py` | TOML 配置加载、编辑与校验 |

### 2.3 作为库使用示例

```python
from pathlib import Path

from agent_dump import AgentScanner

scanner = AgentScanner()

for agent in scanner.get_available_agents():
    sessions = agent.get_sessions(days=7)
    if not sessions:
        continue

    output_dir = Path("./sessions") / agent.name
    exported_path = agent.export_session(sessions[0], output_dir)
    print(f"{agent.display_name}: {exported_path}")
```

---

## 3. 数据流概述

### 3.1 列表与交互导出

```
CLI (cli.py)
  ↓ 解析参数、加载配置、选择模式
Session workflow (session_workflow.py)
  ↓ 创建扫描器
AgentScanner (scanner.py)
  ↓ 从 registry 创建 provider
BaseAgent 子类 (agents/*.py)
  ↓ scan / get_sessions 返回 Session
Selector / Query / Search
  ↓ 选择或过滤 Session
Rendering / export dispatch (rendering.py, cli_shared.py)
  ↓ 调用 agent.export_session / export_raw_session / markdown renderer
输出到 sessions/<agent>/ 或 --output 目录
```

### 3.2 URI 模式

```
CLI uri 参数
  ↓
uri_support.parse_uri()
  ↓
uri_support.find_session_by_id()
  ↓
agent.get_session_head / agent.get_session_data / agent.export_session
  ↓
print、head、json、markdown、raw、summary
```

### 3.3 collect 模式

```
--collect
  ↓
collect_workflow.handle_collect_mode()
  ↓
AgentScanner + 可选 agents:// 查询 URI
  ↓
collect.py 将 Session 渲染为高信号事件流
  ↓
LLM chunk summary → session merge → tree reduction
  ↓
Markdown 输出到 --save 或默认文件名
```

改动某个阶段时，必须维护上下游契约：
- Provider 返回 `Session`，完整内容通过 `get_session_data()` 获取。
- URI scheme 由 `agent_registry.AGENT_REGISTRATIONS` 统一声明。
- 输出格式由 `cli_shared.VALID_FORMATS`、`rendering.export_session_in_format()` 和模式校验共同约束。

---

## 4. 项目结构

```
agent-dump/
├── src/agent_dump/
│   ├── __init__.py              # 顶层公开 API
│   ├── __about__.py             # 单一版本源
│   ├── __main__.py              # python -m agent_dump 入口
│   ├── agent_registry.py        # provider 注册表
│   ├── cli.py                   # CLI 参数解析与模式分发
│   ├── cli_shared.py            # CLI 共享工具
│   ├── session_workflow.py      # list / interactive / query 工作流
│   ├── uri_workflow.py          # URI 工作流
│   ├── collect_workflow.py      # collect 工作流
│   ├── maintenance_workflow.py  # stats / reindex 工作流
│   ├── collect.py               # collect 核心逻辑
│   ├── collect_llm.py           # collect LLM 请求
│   ├── collect_models.py        # collect 输出字段定义
│   ├── config.py                # 配置加载与编辑
│   ├── diagnostics.py           # 结构化诊断
│   ├── i18n.py                  # 中英文文案
│   ├── message_filter.py        # 消息过滤
│   ├── paths.py                 # 搜索根路径模型
│   ├── query_filter.py          # 查询解析与过滤
│   ├── rendering.py             # print/head/markdown/json/raw 渲染调度
│   ├── scanner.py               # AgentScanner
│   ├── search_index.py          # FTS5 搜索索引
│   ├── selector.py              # 交互式选择
│   ├── time_utils.py            # 时间与时区工具
│   ├── uri_support.py           # URI 解析与查找
│   └── agents/
│       ├── __init__.py          # provider 导出
│       ├── base.py              # BaseAgent 与 Session
│       ├── opencode.py          # OpenCode SQLite provider
│       ├── zcode.py             # ZCode SQLite provider
│       ├── codex.py             # Codex JSONL provider
│       ├── kimi.py              # Kimi JSONL provider
│       ├── claudecode.py        # Claude Code JSONL provider
│       ├── cursor.py            # Cursor SQLite provider
│       ├── pi.py                # Pi JSONL provider
│       ├── file_sessions.py     # 文件型 provider 共享基类（扫描/剪枝/并行解析/定位）
│       ├── jsonl_scan.py        # JSONL 扫描辅助
│       └── title_fallback.py    # 标题回退策略
├── tests/
│   ├── test_agents/             # provider 合约和实现测试
│   ├── test_cli.py              # CLI 参数与模式分发测试
│   ├── test_cli_shared.py       # 共享 CLI 能力测试
│   ├── test_collect.py          # collect 核心测试
│   ├── test_config.py           # 配置测试
│   ├── test_maintenance_workflow.py
│   ├── test_query_filter.py
│   ├── test_scanner.py
│   ├── test_search_index.py
│   ├── test_selector.py
│   └── test_version.py
├── skills/agent-dump/           # Codex skill 文档与命令 recipes
├── npm/                         # npm wrapper 与平台包
├── web/                         # 静态站点
├── data/<agent>/                # 本地开发回退数据目录
├── sessions/                    # 默认导出目录
├── pyproject.toml
├── ruff.toml
└── justfile
```

---

## 5. 核心模块

### 5.1 `cli.py`

职责：
- 解析 `argparse` 参数。
- 根据 `uri`、`--collect`、`--stats`、`--reindex`、`--list`、`--interactive` 选择模式。
- 装配 workflow 依赖对象。
- 处理顶层参数冲突、退出码、诊断输出。

约束：
- Provider 数据读取、导出、搜索实现必须下沉到 provider、workflow 或 shared 模块。
- 新 CLI 参数必须补充 `tests/test_cli.py` 覆盖。

### 5.2 `BaseAgent` 与 `Session`

`src/agent_dump/agents/base.py` 定义统一 provider contract：

```python
@dataclass
class Session:
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    source_path: Path
    metadata: dict[str, Any]


class BaseAgent(ABC):
    name: str
    display_name: str

    def scan(self) -> list[Session]: ...
    def is_available(self) -> bool: ...
    def get_sessions(self, days: int = 7) -> list[Session]: ...
    def export_session(self, session: Session, output_dir: Path) -> Path: ...
    def get_session_data(self, session: Session) -> dict: ...
```

可选扩展点：
- `get_session_uri(session)`：默认返回 `<agent>://<session.id>`。
- `find_session_by_id(session_id)`：URI 定位使用。默认全量扫描后按 id 匹配；provider 应尽量用直接查找（SQL 主键、文件名定位）覆盖。
- `filter_sessions_by_keyword(sessions, keyword)`：关键词过滤使用。默认返回 `None`（由索引/文件扫描兜底）；存储支持时 provider 用只读查询覆盖（如 OpenCode 的 SQL LIKE）。
- `unsupported_uri_formats`（类属性）：声明 URI 模式下不支持的导出格式（如 Cursor 的 `raw`/`markdown`），由 `cli_shared.validate_uri_agent_formats()` 统一校验。
- `get_search_roots()`：结构化诊断和路径发现使用。
- `get_session_head(session)`：URI `--head` 使用。
- `get_session_summary_fields(session)`：列表和交互视图元数据摘要使用。
- `export_raw_session(session, output_dir)`：默认复制原始单文件，目录型 source 会返回能力缺失诊断。

### 5.3 `agent_registry.py`

所有 provider 在 `AGENT_REGISTRATIONS` 中注册：

| provider name | display name | URI scheme |
|---------------|--------------|------------|
| `opencode` | OpenCode | `opencode://` |
| `zcode` | ZCode | `zcode://` |
| `codex` | Codex | `codex://`、`codex://threads/` |
| `kimi` | Kimi | `kimi://` |
| `claudecode` | Claude Code | `claude://` |
| `cursor` | Cursor | `cursor://` |
| `pi` | Pi | `pi://` |

`AgentScanner` 只从 registry 创建 provider。新增 provider 的入口是 registry。

### 5.4 `rendering.py` 与导出格式

当前格式：
- `json`：调用 `agent.export_session()`。
- `raw`：调用 `agent.export_raw_session()`。
- `markdown`：调用 `agent.get_session_data()` 后渲染 Markdown 文件。
- `print`：URI 模式直接打印 `render_session_text()` 结果。

格式相关入口：
- `cli_shared.VALID_FORMATS`
- `cli_shared.FORMAT_ALIASES`
- `cli_shared.validate_formats_for_mode()`
- `cli_shared.validate_uri_agent_formats()`
- `rendering.export_session_in_format()`

### 5.5 `query_filter.py` 与搜索

查询能力：
- legacy keyword：`-query "timeout"`
- legacy provider scope：`-query "codex,kimi:timeout"`
- structured query：`-query "bug provider:codex role:user path:. limit:20"`
- path-scoped URI：`agents://.?q=refactor&providers=codex,claude&roles=user&limit=20`
- full-text search：`--search "auth timeout"`，由 `search_index.py` 优先提供 FTS5 索引，必要时回退文件扫描

### 5.6 `collect` 模块

collect 模式入口：
- `collect_workflow.py`：参数校验、dry-run、保存路径、进度编排。
- `collect.py`：事件收集、chunk planning、摘要合并、tree reduction。
- `collect_llm.py`：AI 请求。
- `collect_models.py`：`pm` 和 `insight` 输出字段。

---

## 6. 扩展规范

### 6.1 支持新的 AI 工具

新增 provider 必须遵循 `BaseAgent` contract。

步骤：
1. 在 `src/agent_dump/agents/<agent_name>.py` 创建 `BaseAgent` 子类。会话以文件形式存储的 provider 应继承 `FileSessionAgent`，只需实现 `_iter_session_files()` 与 `_parse_session_file()`（可选 `_session_file_candidates()` 加速 URI 定位）。
2. 实现 `scan()`、`is_available()`、`get_sessions()`、`get_session_data()`、`export_session()`（继承 `FileSessionAgent` 时前三个由基类提供）。
3. 实现 `get_search_roots()`，让诊断信息显示真实搜索路径。
4. 在 `src/agent_dump/agent_registry.py` 添加 `AgentRegistration`，声明 `name`、`display_name`、`factory`、`uri_schemes`、`location_line`。
5. 在 `src/agent_dump/agents/__init__.py` 导出 provider。
6. 若该 provider 属于稳定库 API，在 `src/agent_dump/__init__.py` 导出，并更新本文件第 2 节、README 与 `tests/test_version.py`。
7. 为 provider 增加 `tests/test_agents/test_<agent>.py`，并在 `tests/test_agents/test_contracts.py` 补充合约用例。
8. 更新 `tests/test_scanner.py` 的 provider 数量或名称断言。
9. 更新 README、`skills/agent-dump/SKILL.md`、`skills/agent-dump/references/cli-recipes.md` 的 URI、路径发现和能力边界。

### 6.2 添加新的导出格式

步骤：
1. 在 `cli_shared.VALID_FORMATS` 添加格式名，必要时添加 `FORMAT_ALIASES`。
2. 在 `rendering.export_session_in_format()` 增加分发。
3. 若格式有模式限制，更新 `validate_formats_for_mode()` 或 `validate_uri_agent_formats()`。
4. 为 CLI 解析、分发、成功导出和错误路径补测试。
5. 更新 README 与 skill recipes。

### 6.3 添加新的 CLI 模式

步骤：
1. `cli.py` 添加参数和顶层分发。
2. 新建或复用 `*_workflow.py`，把流程依赖封装为 dataclass / Protocol，便于测试。
3. 复用逻辑进入 `cli_shared.py`。
4. 增加 `tests/test_cli.py` 分发测试和对应 workflow 测试。
5. 更新 README 与 skill recipes 的行为矩阵。

---

## 7. 测试规范

### 7.1 测试边界约束

- **CLI 相关逻辑必须通过 mock 验证**：
  - mock `sys.argv` 测试参数解析与模式分发
  - mock workflow handler 测试分发
  - mock `questionary.select` / `questionary.checkbox` 测试交互式选择
  - mock `sys.stdin` 测试简单输入模式

- **Provider 测试必须使用临时数据源**：
  - OpenCode / ZCode 使用 `tmp_path` 创建临时 SQLite 数据库。
  - Cursor 使用 `tmp_path` 创建临时 `state.vscdb` 与 workspaceStorage。
  - Codex / Kimi / Claude Code 使用 `tmp_path` 创建临时 JSONL 文件。
  - 使用 `monkeypatch` 注入 `CODEX_HOME`、`KIMI_SHARE_DIR`、`CLAUDE_CONFIG_DIR`、`CURSOR_DATA_PATH`、`PI_HOME` 或 `Path.home()`。

- **不允许真实访问用户目录**：
  - 禁止读取真实 `~/.codex`、`~/.claude`、`~/.kimi`、`~/.local/share/opencode`、`~/.zcode`、Cursor 用户目录。
  - 禁止写入真实 `~/sessions`。
  - 文件写入测试使用 `tmp_path`。

### 7.2 测试命令

```bash
# 运行所有测试
just test

# 详细输出
uv run pytest -v

# 运行特定测试
uv run pytest -k "test_name"
```

### 7.3 代码风格

```bash
# 代码检查
just lint          # ruff check
just lint-fix      # ruff check --fix
just lint-format   # ruff format
```

- 使用 Ruff 进行代码检查和格式化
- 配置位于 `ruff.toml`
- 单行最大长度 100
- 使用双引号

---

## 8. Provider 数据源说明

本节记录当前 provider 的数据源事实，用于测试和定位。Schema 细节属于 provider 内部实现。

### 8.1 OpenCode

- 路径：`XDG_DATA_HOME/opencode/opencode.db`、Windows data 目录、`~/.local/share/opencode/opencode.db`、`data/opencode/opencode.db`
- 存储：SQLite
- 当前表：`session`、`message`、`part`
- 时间戳：毫秒时间戳，读取时转换为 `datetime`
- JSON 字段：`message.data`、`part.data`

### 8.2 ZCode

- 路径：macOS `~/.zcode/cli/db/db.sqlite`；Windows `%USERPROFILE%\.zcode\cli\db\db.sqlite`
- Linux：无默认 ZCode 会话路径
- 存储：SQLite
- 当前核心表：`session`、`message`、`part`
- 时间戳：毫秒时间戳，读取时转换为 `datetime`
- JSON 字段：`message.data`、`part.data`
- URI：`zcode://<session_id>`

### 8.3 Codex

- 路径：`CODEX_HOME/sessions`、`~/.codex/sessions`、`data/codex`
- 存储：JSONL
- URI：`codex://<session_id>`、`codex://threads/<session_id>`

### 8.4 Kimi

- 路径：`KIMI_SHARE_DIR/sessions`、`~/.kimi/sessions`、`data/kimi`
- 存储：JSONL
- URI：`kimi://<session_id>`

### 8.5 Claude Code

- 路径：`CLAUDE_CONFIG_DIR/projects`、`~/.claude/projects`、`data/claudecode`
- 存储：JSONL
- URI：`claude://<session_id>`

### 8.6 Cursor

- 路径：`CURSOR_DATA_PATH` 或 Cursor 默认用户目录下的 `workspaceStorage`，并读取 `globalStorage/state.vscdb`
- 存储：SQLite `cursorDiskKV`
- URI：`cursor://<requestid>`
- 能力边界：Cursor URI 支持 `json` 与 `print`

### 8.7 Pi

- 路径：`PI_HOME/agent/sessions`、`~/.pi/agent/sessions`、`data/pi`
- 存储：JSONL
- URI：`pi://<session_id>`
- 当前格式：首行为 `type=session` header，后续 entry 通过 `id` / `parentId` 形成树形结构

---

## 9. 交互式 CLI 开发原则

本项目使用 `questionary` 库实现交互式命令行界面。开发时需遵循以下原则。

### 9.1 库的选择

- **使用 `questionary`**：基于 `prompt_toolkit`，提供良好的交互体验
- **避免使用 `inquirer`**：虽然 API 简单，但无法灵活自定义键绑定

### 9.2 基本使用模式

```python
import questionary
from questionary import Style

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.rendering import format_session_metadata_summary


def build_session_choices(sessions: list[Session], agent: BaseAgent):
    choices = []
    for session in sessions:
        label = agent.get_formatted_title(session)
        summary = format_session_metadata_summary(agent, session)
        choices.append(questionary.Choice(title=f"  {label}\n    {summary}", value=session))
    return choices


# 创建选项
choices = build_session_choices(sessions, agent)

# 创建问题
q = questionary.checkbox(
    "选择要导出的会话:",
    choices=choices,
    style=custom_style,
    instruction="\n↑↓ 移动  |  空格 选择/取消  |  回车 确认  |  q 退出",
)

# 添加自定义键绑定（重要）
q.application.key_bindings.add("q")(lambda event: event.app.exit(result=None))
q.application.key_bindings.add("Q")(lambda event: event.app.exit(result=None))

# 获取结果
selected = q.ask()
```

### 9.3 关键注意事项

- **属性访问**：Question 对象的 `app` 属性实际是 `application`
  ```python
  # 正确
  q.application.key_bindings.add(...)
  # 错误
  q.app.key_bindings.add(...)  # AttributeError
  ```

- **回调函数签名**：键绑定回调接收 `event` 参数
  ```python
  lambda event: event.app.exit(result=None)
  ```

- **退出机制**：
  - `Ctrl+C`：内置支持，抛出 `KeyboardInterrupt`
  - 自定义键：通过 `event.app.exit(result=None)` 退出
  - `result=None` 表示用户取消，返回空列表

### 9.4 Agent 约束（重要）

> ⚠️ **不得修改 questionary 键绑定行为**，除非明确重构 `selector.py` 层。

- 禁止删除 `q` 键退出功能
- 禁止修改 `space` 键选择行为
- 禁止修改 `enter` 键确认行为
- 新增自定义键绑定需更新本文档第 9.3 节

### 9.5 测试策略

```python
# 测试交互式选择需要 mock questionary.checkbox
with mock.patch("questionary.checkbox") as mock_checkbox:
    mock_checkbox.return_value.ask.return_value = sessions
    result = select_sessions_interactive(sessions, agent)
```

### 9.6 用户体验

- **显示标题**：优先显示会话标题，附加时间信息
- **操作提示**：在 `instruction` 中清晰说明所有可用操作
- **退出选项**：提供多种退出方式（`q` 键、`Ctrl+C`）
- **非终端回退**：检测 `is_terminal()`，非终端环境使用简单输入模式

---

## 10. 发布

```bash
# 构建包
just build

# 发布到 PyPI
just publish
```

### 添加依赖

```bash
# 生产依赖
uv add package-name

# 开发依赖
uv add --dev package-name
```

---

## 11. 相关文件

- `pyproject.toml` - 项目配置和依赖
- `ruff.toml` - 代码风格配置
- `README.md` - 英文用户文档
- `README_zh.md` - 中文用户文档
- `skills/agent-dump/SKILL.md` - Codex skill 主说明
- `skills/agent-dump/references/cli-recipes.md` - CLI 命令模板和行为矩阵
- `justfile` - 自动化命令

---

## 附录：快速检查清单

在提交变更前，确认以下事项：

- [ ] 没有破坏 `__init__.py` 导出的公开 API
- [ ] 公开 API 声明与 `src/agent_dump/__init__.py::__all__` 一致
- [ ] 新增函数有对应的单元测试
- [ ] CLI 变更同步更新了 `test_cli.py`
- [ ] Provider 测试使用临时数据源，没有访问真实用户目录
- [ ] README 与 skill recipes 已同步 CLI 能力边界
- [ ] 代码通过 `just isok` 检查
- [ ] 如修改架构、provider 或 CLI 模式，同步更新本文件
