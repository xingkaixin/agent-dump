# AGENTS.md

> 本文件只保存所有仓库任务都需要的稳定约束和任务路由。具体实现事实按任务读取，避免把易变化的模块清单常驻到每次 Agent 执行中。

## 1. 稳定约束

### 1.1 数据安全

- Provider 会话源只读。导出、搜索、统计和 collect 不得修改数据库、JSONL 或用户会话目录。
- 工具生成的索引、配置、日志和导出文件必须写入本项目明确拥有的路径，不得混入 Provider 数据源。
- 测试不得读取或写入真实用户会话目录；使用 `tmp_path`、临时 SQLite 或显式注入的路径。
- 临时文件使用 `tempfile` 等可清理机制，并确保异常路径也会清理。

### 1.2 兼容性

- `src/agent_dump/__init__.py` 的 `__all__` 是公开 Python API 的单一来源。不得删除或重命名已导出的符号；需要演进时保留兼容入口并明确弃用策略。
- CLI 参数、输出格式、退出码和默认路径属于可观察行为。修改时同步更新对应测试和用户文档。
- 未经明确要求不得改变既有默认行为；新增能力应保持现有调用路径兼容。

### 1.3 架构边界

- `cli.py` 只负责参数解析、依赖装配和工作流分发。业务逻辑下沉到 operation、workflow 或职责模块。
- 会话发现、读取和导出统一通过 `BaseAgent` 契约进入。实现可以位于 Provider 类、共享基类或 `agent_dump.agents` 包内 helper。
- Provider 私有 schema 只能由 `agent_dump.agents` Provider 层解释。CLI、workflow 和 selector 只依赖稳定的 Session、facts 与 Provider 契约。
- selector 不得触发 Provider 发现、扫描或完整内容读取。会话计数由调用方传入；允许调用不执行 I/O 的展示投影方法。
- 共享逻辑保持单一归属：URI、输出格式、渲染、导出和跨工作流 CLI 能力分别进入 `uri_support.py`、`output_formats.py`、`rendering.py`、`exporting.py` 和 `cli_shared.py`。
- 不得引入循环导入。依赖方向应从装配层指向工作流和领域实现。

### 1.4 代码与测试

- 生产函数的参数和返回值必须有完整类型注解；现有门禁由 `tests/test_type_annotations.py` 执行。
- 只在新增或变更可观察行为、修复回归或保护高风险边界时补测试。测试覆盖行为契约，不要求按函数一一对应。
- CLI 变更至少覆盖参数归一化、工作流分发及相关输出或退出码。仅在 Provider、终端交互或外部系统等边界需要隔离时使用 mock。
- 不随意新增第三方依赖。必要但未被代码直接 import 的依赖应在声明处说明原因。
- 正文代码默认不写注释；只为 workaround、magic value、反直觉边界等无法从代码直接理解的原因添加注释。

## 2. 按任务读取

开始修改前，只读取与任务相关的参考：

- 领域术语、Session facts 和读写边界：`CONTEXT.md`
- 架构、Provider contract、Query/Search、Collect 和扩展步骤：`docs/architecture.md`
- 测试、i18n、交互式 CLI、依赖和本地验证：`docs/development-guide.md`
- 发版、构建约束和发布控制边界：`docs/release-guide.md`
- 面向用户的 CLI 行为：`README.md`、`README_zh.md`
- Agent 使用 recipes：`skills/agent-dump/SKILL.md`、`skills/agent-dump/references/cli-recipes.md`

以下入口用于快速定位，不构成完整模块清单：

- CLI operation 归一化：`command_plan.py`
- list / interactive / query：`session_workflow.py`
- 单 URI 工作流：`uri_workflow.py`
- collect：`collect_workflow.py` 与 `collect_*.py`
- Provider 注册：`agent_registry.py`
- Provider 实现：`agents/`
- 搜索索引：`search_index.py`
- 配置：`config.py`、`config_command.py`
- 诊断：`diagnostics.py`

## 3. 验证与文档

- 开发时先运行与改动直接相关的测试。
- 提交 PR 前运行 `just isok`。覆盖率需要单独检查时运行 `just cov`。
- 修改公开 API、CLI 或用户可见能力时，同步更新 README 和相关 skill recipes。
- 只在稳定约束、职责边界或任务路由变化时更新本文件。模块增删和实现细节记录到对应按需文档或由代码、配置和测试作为来源。
- 修改架构术语或事实边界时同步更新 `CONTEXT.md`。

## 4. 提交前检查

- [ ] 未修改 Provider 会话源或在测试中访问真实用户目录
- [ ] 公开 API 和 CLI 可观察行为保持兼容，或变更已获明确要求
- [ ] 业务逻辑位于正确职责层，没有重复解释 Provider schema
- [ ] 相关行为测试和用户文档已同步
- [ ] `just isok` 通过
