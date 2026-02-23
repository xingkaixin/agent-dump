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

- **数据库 schema 不可假设未来变更**：当前代码基于 OpenCode 当前版本 schema，不得硬编码 schema 假设
- **不得删除或修改用户数据**：导出工具只读访问数据库
- **临时文件必须清理**：使用 `tempfile` 模块并确保清理

### 1.4 架构边界约束

- **cli.py 只负责参数解析和工作流调度**：业务逻辑必须下沉到具体模块
- **数据库逻辑禁止写入 cli.py**：所有数据库操作封装在 `db.py`
- **UI 逻辑与业务逻辑分离**：selector 层不得直接操作数据库或文件系统

---

## 2. 公共接口声明（Public API Surface）

以下接口为稳定公开 API，变更需保持向后兼容。

### 2.1 稳定公开 API（Stable Public API）

位于 `src/agent_dump/__init__.py` 导出：

| 函数/类 | 模块 | 稳定性 |
|---------|------|--------|
| `find_db_path()` → `Path` | `db.py` | **稳定** |
| `get_recent_sessions(db_path, days=7)` → `List[Dict]` | `db.py` | **稳定** |
| `export_session(db_path, session, output_dir)` → `Path` | `exporter.py` | **稳定** |
| `export_sessions(db_path, sessions, output_dir)` → `List[Path]` | `exporter.py` | **稳定** |

### 2.2 内部实现（Internal Implementation）

以下函数为内部实现，不建议外部直接依赖，可能随版本变更：

| 函数/类 | 模块 | 稳定性 |
|---------|------|--------|
| `main()` | `cli.py` | 内部入口 |
| `select_sessions_interactive(sessions)` | `selector.py` | 内部 |
| `select_sessions_simple(sessions)` | `selector.py` | 内部 |
| `is_terminal()` → `bool` | `selector.py` | 内部 |

### 2.3 作为库使用示例

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

---

## 3. 数据流概述

简化的执行路径：

```
CLI (cli.py)
  ↓ 解析参数
找到数据库 (db.py::find_db_path)
  ↓ 查询
获取 sessions (db.py::get_recent_sessions)
  ↓ 交互选择
Selector (selector.py)
  ↓ 导出
Exporter (exporter.py::export_sessions)
  ↓ 写入
JSON 输出到磁盘
```

**重要**：改动某个阶段时，不得破坏上下游契约。例如：
- `db.py` 返回的 session dict 结构变更时，`selector.py` 和 `exporter.py` 需同步适配
- `selector.py` 的输出格式变更时，`exporter.py` 的输入处理需同步更新

---

## 4. 项目结构

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
└── justfile                  # 自动化命令
```

---

## 5. 核心模块

### 5.1 cli.py
命令行入口模块，**仅负责**：
- 参数解析（`argparse`）
- 工作流调度（调用 db → selector → exporter）
- 错误处理和退出码

**禁止**：直接操作数据库、直接写入文件、实现业务逻辑。

### 5.2 db.py
数据库操作模块，处理 SQLite 数据库连接和查询。

**职责**：
- 自动查找数据库路径（支持多路径回退）
- 执行 SQL 查询并返回结构化数据
- 时间戳转换（毫秒 → datetime）

### 5.3 exporter.py
导出逻辑模块，处理会话数据的 JSON 序列化。

**职责**：
- 单个/批量会话导出
- JSON 格式序列化（含缩进、中文编码）
- 输出目录管理

### 5.4 selector.py
交互式选择模块，提供终端和简单两种选择模式。

**职责**：
- 检测终端环境并选择合适的选择模式
- 交互式多选（`questionary`）
- 简单 stdin 输入模式（非终端环境）

---

## 6. 扩展规范

### 6.1 支持新的 AI 工具

新增 AI 工具支持必须遵循以下架构约束（非示例，是强规范）：

#### 架构要求

1. **每个 agent 对应一个 Parser 类**
   - 位置：`src/agent_dump/parsers/<agent_name>.py`
   - 基类：建议抽象基类定义统一接口（待实现）

2. **Parser 必须实现统一接口**：
   ```python
   class BaseParser(ABC):
       @abstractmethod
       def list_sessions(self, days: int = 7) -> List[Dict]:
           """列出最近 N 天的会话"""
           pass
       
       @abstractmethod
       def load_session(self, session_id: str) -> Dict:
           """加载指定会话的完整数据"""
           pass
       
       @property
       @abstractmethod
       def db_path(self) -> Path:
           """返回数据库路径"""
           pass
   ```

3. **禁止在 cli.py 写数据库逻辑**：
   - CLI 层通过 `parser.db_path` 获取路径
   - 所有 SQL 查询封装在 Parser 类内部

4. **注册新 agent 的步骤**：
   - 创建 `parsers/newagent.py` 实现 `BaseParser`
   - 在 `db.py` 的 `find_db_path()` 中添加新路径
   - 在 `cli.py` 的 `--agent` 参数 choices 中添加新选项
   - 在 `exporter.py` 中根据 `agent` 类型选择对应 Parser

### 6.2 添加新的导出格式

1. 在 `exporter.py` 中创建新的导出函数
2. 函数签名参考：`export_session_<format>(db_path, session, output_dir) -> Path`
3. 在 `cli.py` 中添加 `--format` 选项
4. 在 `exporter.py` 中根据 format 选择对应导出函数

---

## 7. 测试规范

### 7.1 测试边界约束

- **CLI 相关逻辑必须通过 mock 验证**：
  - mock `sys.argv` 测试参数解析
  - mock `questionary.checkbox` 测试交互式选择
  - mock `sys.stdin` 测试简单输入模式

- **数据库访问必须用临时 SQLite**：
  ```python
  # 正确：使用临时内存数据库
  @pytest.fixture
  def temp_db():
      conn = sqlite3.connect(":memory:")
      # 创建 schema
      yield conn
      conn.close()
  
  # 错误：不要访问真实用户目录
  # db_path = Path.home() / ".local/share/opencode/opencode.db"
  ```

- **不允许真实访问用户目录**：
  - 禁止读取 `~/.local/share/opencode/opencode.db`
  - 禁止写入真实 `~/sessions` 目录
  - 使用 `tmp_path` fixture 进行文件操作测试

### 7.2 测试命令

```bash
# 运行所有测试、查看测试覆盖率报告
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

## 8. 数据库结构（OpenCode Current Schema）

> ⚠️ **注意**：以下 schema 仅针对 **OpenCode 当前版本**。这是具体实现细节，**不是抽象接口**。未来 OpenCode 版本可能变动，不保证向后兼容。

### 8.1 Session 表

```sql
CREATE TABLE session (
    id TEXT PRIMARY KEY,
    title TEXT,
    time_created INTEGER,  -- 毫秒时间戳
    time_updated INTEGER,  -- 毫秒时间戳
    slug TEXT,
    directory TEXT,
    version INTEGER,
    summary_files TEXT
);
```

### 8.2 Message 表

```sql
CREATE TABLE message (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    time_created INTEGER,
    data TEXT  -- JSON 格式
);
```

### 8.3 Part 表

```sql
CREATE TABLE part (
    id TEXT PRIMARY KEY,
    message_id TEXT,
    time_created INTEGER,
    data TEXT  -- JSON 格式
);
```

### 8.4 注意事项

- **时间戳**：数据库存储的是毫秒时间戳，Python datetime 需要转换（除以 1000）
- **JSON 字段**：`message.data` 和 `part.data` 是 JSON 字符串，需 `json.loads()` 解析
- **Schema 变更**：如 OpenCode 更新 schema，需同步更新查询逻辑

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

# 创建选项
choices = []
for session in sessions:
    title = session["title"][:60] + ("..." if len(session["title"]) > 60 else "")
    time_str = session["created_formatted"]
    label = f"{title} ({time_str})"
    choices.append(questionary.Choice(title=label, value=session))

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
    result = select_sessions_interactive(sessions)
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
- `README.md` - 用户文档（中文）
- `justfile` - 自动化命令

---

## 附录：快速检查清单

在提交变更前，确认以下事项：

- [ ] 没有破坏 `__init__.py` 导出的公开 API
- [ ] 新增函数有对应的单元测试
- [ ] CLI 变更同步更新了 `test_cli.py`
- [ ] 数据库测试使用临时 SQLite，没有访问真实用户目录
- [ ] 代码通过 `just isok` 检查
- [ ] 如修改了本文档相关章节，同步更新 AGENTS.md
