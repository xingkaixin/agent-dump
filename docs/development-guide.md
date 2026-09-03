# 开发与验证指南

本文档面向修改测试、终端交互、依赖或验证配置的贡献者和 Agent。

## 1. 测试原则

测试覆盖可观察行为、回归风险和高风险边界，不要求每个新增函数都有一一对应的测试。

- CLI 参数和模式变更覆盖 `command_plan` 归一化、顶层分发、输出或退出码。
- Provider 测试使用 `tmp_path` 创建临时 SQLite、JSONL 或目录结构，并通过环境变量或构造参数注入路径。
- 测试不得读取真实 `~/.codex`、`~/.claude`、`~/.kimi`、OpenCode、ZCode、Cursor 或 Pi 数据目录，也不得写入真实用户导出目录。
- 终端交互通过受控的 questionary 边界或 stdin/stdout 测试；只有需要隔离交互时才使用 mock。

### i18n 断言

- CLI 文案断言使用 `tests/locale_helpers.py` 的 `expect()` 或 `expect_contains()`，不要新增写死的中英文 UI 文案。
- 默认 locale 由 `conftest.py` 的 `set_language_zh` fixture 设置。
- 其他 locale 使用 `use_language` fixture；英文端到端覆盖位于 `tests/test_cli_locales.py`。
- fixture 中的中文会话内容属于测试数据，不按 UI 文案替换。

## 2. 验证命令

```bash
# 相关测试
uv run pytest -q tests/test_target.py

# 全部 Python 测试
just test

# 覆盖率与下限
just cov

# 完整本地门禁
just isok
```

pytest 配置只位于 `pyproject.toml` 的 `[tool.pytest.ini_options]`。不要新增 `pytest.ini`、`setup.cfg` 或 `tox.ini` 覆盖它。覆盖率不进入默认 addopts，避免单测筛选产生误导性的全包覆盖率报告。

`just check` 同时运行两个作用域不同的检查器：

- pyright 只检查 `src`。
- ty 检查全仓，包括 tests。

代码检查和格式化使用 Ruff，配置位于 `ruff.toml`，单行最大长度 120，字符串使用双引号。

## 3. 交互式 CLI

selector 负责展示和选择，不负责 Provider discovery 或完整内容读取：

- `select_agent_interactive(agents, session_counts)` 的计数由调用方提供。
- Session 标题、摘要和 URI 可以通过无 I/O 的 Provider 投影生成。
- questionary 的 `q`/`Q` 退出、空格选择、回车确认属于用户可见行为；修改时同步更新 selector 测试。
- `Ctrl+C` 返回取消结果。
- 非 TTY 环境回退到简单 stdin 模式。
- 第三方 Session 文本进入终端前必须经过现有安全净化入口。

实现以 `src/agent_dump/selector.py` 为准，行为测试以 `tests/test_selector.py` 为准。不要从文档复制 questionary 代码骨架。

## 4. 依赖

```bash
# 生产依赖
uv add package-name

# 开发依赖
uv add --dev package-name
```

不新增无法证明必要的第三方依赖。必要但不被代码直接 import 的依赖，应在 `pyproject.toml` 声明附近说明运行时关系；不要用泛化注释解释显而易见的依赖。
