# 更新日志

## [0.6.13] - 2026-03-31

### 新增功能

- **Agent 注册表统一管理元数据**
  - 引入 `AgentRegistration` 数据类和 `AGENT_REGISTRATIONS` 元组，作为所有 agent 名称、工厂函数、URI scheme 和帮助文本的单一数据源
  - 使用注册表 helper 函数（`create_registered_agents`、`get_uri_scheme_map` 等）替代 CLI 中分散的 agent 初始化逻辑

### 变更

- **Collect 模块拆分重构**
  - 将 LLM HTTP 调用提取为独立的 `collect_llm` 模块（OpenAI/Anthropic 请求函数）
  - 将共享数据模型与常量提取为 `collect_models` 模块
  - 将流程编排逻辑提取为 `collect_workflow` 模块，通过 `CollectWorkflowDeps` 实现显式依赖注入
- **CLI 与渲染模块分离**
  - 将会话渲染与导出逻辑提取为 `rendering` 模块
  - 将 URI 解析与会话查找逻辑提取为 `uri_support` 模块
  - `cli.py` 委托给新模块，代码大幅精简

## [0.6.12] - 2026-03-26

### 新增功能

- **Collect 诊断日志与超时配置**
  - 为 collect 运行新增 append-only JSONL 诊断日志，默认写入配置目录下的日志路径
  - 在 collect 配置中新增 `summary_timeout_seconds`，可直接调整 LLM 摘要请求超时
  - 新增 `[logging]` 配置段，支持启用/禁用 collect 诊断日志并覆盖日志文件路径

## [0.6.11] - 2026-03-23

### 新增功能

- **CLI 与扫描器支持 Cursor agent**
  - 在 CLI 流程和会话扫描中将 `cursor` 作为一等 agent 接入
  - 在 README 中补充 Cursor 的使用说明
- **支持通过 request-id 风格 URI 获取 Cursor 会话**
  - URI 流程下可按 request-id 形式标识直接加载 Cursor 会话

### 变更

- **Cursor 会话解析质量优化**
  - 改进会话标题格式化，提升可读性
  - 优化 Cursor 会话中的消息提取与排序行为
- **Web 落地页展示优化**
  - 更新页面文案、结构与样式，使产品信息表达更清晰

### 问题修复

- **Cursor 会话可用性与顺序稳定性**
  - 精简会话可用性检查逻辑，减少列表/导出链路中的误判
  - 改进消息排序一致性，提升 Cursor 会话渲染/导出稳定性

## [0.6.10] - 2026-03-23

### 新增功能

- **Codex subagent 导出支持**
  - 在统一 JSON 导出中将 `spawn_agent` 识别为 `subagent` tool，并附带返回的 `subagent_id` / `nickname`
  - 将 `<subagent_notification>...</subagent_notification>` user payload 转换为带匹配 subagent 元数据的 assistant 消息
  - 在 `--format print` 中将 Codex subagent 调用与最终结果渲染为 `Assistant (nickname)` 消息
  - 仅在 JSON 导出中过滤 Codex 的 `wait_agent` tool part，不改变 raw 解析或其他格式行为

## [0.6.9] - 2026-03-22

### 新增功能

- **Collect 按 agent deny 过滤会话**
  - `--collect` 现支持从 `config.toml` 读取 `[agent.<name>].deny`
  - 当 session 的 `cwd`/项目目录命中 deny 路径，或位于该路径下时，会在 collect 阶段直接忽略
  - 过滤范围仅限 collect，不影响普通导出、`--list`、`--interactive` 或 URI 链路

### 文档

- 补充 `[agent.claudecode].deny` 的 collect 配置示例，并明确该配置只作用于 collect

## [0.6.8] - 2026-03-16

### 新增功能

- **Collect 结构化多阶段归约管线**
  - 将 collect 摘要从简单的"逐条 summary 再合并"重写为完整的多阶段管线：`scan_sessions → plan_chunks → summarize_chunks → merge_sessions → tree_reduction → render_final → write_output`
  - 使用固定 JSON schema（10 个结构化字段：topics、decisions、key_actions 等）对每个 chunk 生成摘要
  - 通过 tree reduction（GROUP_SIZE=8）逐层聚合所有 session 摘要
  - 新增 `--save` 选项，支持指定 collect 输出路径（目录或 `.md` 文件）
  - 为 OpenAI 和 Anthropic 请求禁用 thinking/reasoning，减少不必要的 token 开销
  - stderr 显示多阶段进度事件（scan_sessions、plan_chunks、summarize_chunks 等）

### 变更

- **Collect 摘要结构调整**
  - session summary 现使用结构化 JSON（10 个字段）替代自由文本 markdown
  - 输出文件名恢复为 `agent-dump-collect-YYYYMMDD-YYYYMMDD.md`（通过 `--save` 可自定义）

### 改进

- 扩展 collect 多阶段进度与 `--save` 路径解析的测试覆盖
- 改进测试类型安全，使用 typed Session 工厂替代 mock 对象

### 文档

- 更新 README/README_zh 中 `--collect` 的描述，补充多阶段管线说明与 `--save` 用法

### 依赖

- 升级 ruff 0.15.2 → 0.15.6、ty 0.0.18 → 0.0.23

### CI

- 新增 Cloudflare Pages 部署支持与 Analytics 追踪脚本（web 落地页基础设施，非 CLI 用户可见功能）

## [0.6.7] - 2026-03-10

### 变更

- **Collect 汇总链路**
  - `--collect` 现会先逐条总结每个 session，再基于这些 session summary 生成最终总结，避免单次 prompt 过长
  - 新增可配置的 `[collect].summary_concurrency`，用于控制单 session summary 的并发数
  - collect 运行期间会在 stderr 从 `0/N` 开始显示 session summary 进度，并在 AI 请求进行中持续更新加载状态
  - collect 输出文件名调整为 `agent-dump-collect-YYYYMMDD-YYYYMMDD.md`

## [0.6.6] - 2026-03-05


### 新增功能

- **Collect 汇总模式**
  - 新增 `--collect`，用于按时间范围收集会话打印内容并通过 AI 总结
  - 新增 `-since/--since` 与 `-until/--until` 日期参数（`YYYY-MM-DD` / `YYYYMMDD`）
  - 结果会输出到终端，并写入当前目录 `agent-dump-collect-YYYYMMDD.md`
- **配置管理模式**
  - 新增 `--config view|edit`，用于查看与交互式编辑 AI 配置
  - 新增跨平台配置路径解析：
    - macOS/Linux: `~/.config/agent-dump/config.toml`
    - Windows: `%APPDATA%/agent-dump/config.toml`
  - collect 执行前新增配置校验
- **URI summary 模式**
  - 新增 `--summary`，用于 URI 模式的 AI 总结
  - summary 生成要求 URI 模式且 `--format` 包含 `json`
  - 配置缺失/不完整或 AI 请求失败时降级为仅告警并继续导出

### 变更

- **AI 总结加载提示**
  - 在 `--summary` 与 `--collect` 流程中，AI 请求期间会在 stderr 显示 loading 提示

### 改进

- 扩展 collect 日期规则、collect 输出写入、config 流程和 CLI 模式分发的测试覆盖

### 文档

- 更新 `skills/agent-dump/SKILL.md` 与 recipes，补充安装入口与环境选择规则

### CI

- 在 release workflow 中增加原生二进制暂存步骤

## [0.6.5] - 2026-03-03

### 新增功能

- **官方 agent 数据路径发现**
  - 支持 `CODEX_HOME`、`CLAUDE_CONFIG_DIR` 与 `KIMI_SHARE_DIR`
  - OpenCode 现按 Unix 的 `XDG_DATA_HOME` 与 Windows 的 `LOCALAPPDATA` / `APPDATA` 发现数据目录
  - 继续保留 home 目录与本地 `data/` 开发数据的回退路径
- **npm 包装器与独立原生二进制分发**
  - 新增 `bunx @agent-dump/cli` 与 `npx @agent-dump/cli` 这类无需 Python 的运行入口
  - 为 macOS、Linux 和 Windows 发布平台特定二进制

### 变更

- **发布版本与分发流水线**
  - 将包版本元数据移动到 `src/agent_dump/__about__.py`，作为单一真源
  - 在发布构建时校验 Git tag 与包版本元数据的一致性
  - 改为统一的 GitHub release workflow，同时处理 PyPI 发布与原生二进制分发

### 改进

- 扩展路径解析、CLI 路径输出与版本一致性的回归测试覆盖
- 为打包后的二进制安装补充 smoke tests，并调整 PyInstaller 打包配置

## [0.6.4] - 2026-03-02

### 新增功能

- **Kimi 从原始会话文件提取总 token 数**
  - 从 `context.jsonl` 最后一条 `_usage.token_count` 记录导出 `stats.total_tokens`
  - 当 `context.jsonl` 不存在时，回退到 `wire.jsonl`
  - 继续保留从 wire usage 记录提取 `total_input_tokens` 与 `total_output_tokens` 的行为

## [0.6.3] - 2026-03-01

### 新增功能

- **多格式导出与 raw 原始会话输出**
  - `--format` 现已支持逗号分隔多值，例如 `json,markdown,raw`
  - 为所有 agent 增加 `raw` 导出能力
  - 保留 `md` 作为 `markdown` 的兼容别名
- **Codex plan 导出重建**
  - 将 assistant 的 `<proposed_plan>` 区块提取为结构化 `plan` part
  - 将后续 user 的批准或拒绝结果合并到 `approval_status` 与 `output`
  - 已消费的审批消息不再重复出现在导出会话中

### 变更

- **按模式区分格式行为**
  - URI 模式可组合 `print` 与文件导出，例如 `print,json`
  - 交互模式支持 `json`、`markdown`、`raw`，但拒绝 `print`
- **Codex skill 包装消息导出行为**
  - 在 JSON 导出中，将 `<skill><name>...</name></skill>` 形式的 user 包装消息转换为 assistant `tool=skill`
  - 非 JSON 的会话数据保持原样，文本渲染继续保留原始 payload

### 改进

- 扩展 Codex 关于 plan 审批处理与 skill 导出转换的回归测试覆盖

## [0.6.2] - 2026-02-28

### 问题修复

- **Codex 响应导出去重**
  - assistant 可见的 `reasoning` 与 `text` 只从 `response_item` 提取
  - 避免 `event_msg` 镜像记录导致的 thinking/commentary 重复导出

### 变更

- **Codex `apply_patch` 工具导出结构**
  - 将 `custom_tool_call(name=apply_patch)` 统一归一化为 `tool=patch`
  - 将 patch input 重建为 `state.arguments.content` 下按文件和操作组织的块列表
  - 文件编辑输出为 diff 文本，新增文件输出为最终文件内容，删除和纯移动输出为空内容
  - 保留原始 patch 文本用于兜底与调试，并继续按 `call_id` 回填工具输出

## [0.6.1] - 2026-02-28

### 新增功能

- **Kimi 解析器支持 `context.jsonl` 会话**
  - 支持 Kimi 较新的会话存储格式
  - 统一工具标题映射，并跳过噪音较大的 `SetTodoList` 工具记录

### 问题修复

- **Codex 导出重建逻辑**
  - 修正重建消息与工具调用时导出的时间戳
  - 改进 assistant/tool 分组逻辑，避免将工具调用挂到仅含 reasoning 的消息上
- **Claude Code 工具轨迹导出**
  - 清理导出会话中的工具轨迹内容
  - 在重建 assistant 状态时回填缺失的工具输出

### 改进

- 扩展 Kimi、Codex 和 Claude Code 会话解析的回归测试覆盖
- 将 `.uv-cache/` 添加到 `.gitignore`

## [0.6.0] - 2026-02-26

### 破坏性变更

- **筛选与分页参数的 CLI 语法调整**
  - `--days` -> `-days`（短别名 `-d`）
  - `--query` -> `-query`（短别名 `-q`）
  - `--page-size` -> `-page-size`（短别名 `-p`）
  - `--list`、`--interactive`、`--output` 仍保持双短横线风格

### 新增功能

- **国际化支持（英文/中文）**
  - 新增 `--lang {en,zh}` 参数，可强制指定 CLI 语言
  - 新增统一的翻译模块，用于管理用户可见文案
- **通过 `--format` 选择导出格式**
  - 支持 `json`、`md`、`print`
  - 新增会话 Markdown 导出能力

### 变更

- **不同模式的默认导出格式**
  - URI 模式默认 `print`
  - 交互/导出流程默认 `json`
- **Python 兼容性基线**
  - 调整代码以支持 Python `>=3.10`

### 改进

- **CI 自动化**
  - 新增 GitHub Actions 工作流，执行 lint、类型检查与测试
  - 扩展 CI Python 版本矩阵覆盖（3.10-3.14）

### 文档

- 更新 README/README_zh 中的 CLI 参数语法与格式用法示例
- 在 `skills/agent-dump/` 下新增 Skills 集成文档与 CLI recipes

## [0.5.0] - 2026-02-24

### 新增功能

- **跨 Agent 关键词查询 (`--query`)**
  - 支持 `keyword` 与 `agent1,agent2:keyword` 两种格式
  - 支持 agent 别名 `claude` -> `claudecode`
  - 支持按会话标题与内容进行关键词匹配，提升定位效率
- **支持 Codex URI 变体**：`codex://threads/<session_id>`
  - `codex://threads/<id>` 与 `codex://<id>` 现在等价

### 变更

- **列表模式输出行为** (`--list`)
  - 现在一次性输出全部匹配会话（不再出现分页提示）
  - `--page-size` 为兼容旧参数仍可传入，但在列表模式下会被忽略

### 问题修复

- **导出与 URI 文本渲染中的消息过滤**
  - 过滤 `developer` 角色消息
  - 过滤注入的上下文型 user 消息（如 AGENTS/instructions/environment 区块）
  - 降低导出结果中的提示词与上下文噪音

### 改进

- **测试覆盖**
  - 新增更完整的 CLI 测试（URI 解析、列表行为、消息过滤）
  - 新增 query 过滤与 Codex 导出过滤的针对性测试

## [0.4.0] - 2026-02-23

### 新增功能

- **URI 模式** - 通过 Agent Session URI 直接导出会话文本
  - 新命令: `agent-dump <uri>` (如 `opencode://session-id`)
  - 支持的 URI 协议: `opencode://`, `codex://`, `kimi://`, `claude://`
  - 直接将格式化的会话文本渲染到终端
  - 适用于快速查看会话内容，无需导出到文件
- **Agent Session URI 显示** - 在 CLI 列表和交互式选择器中显示 URI
  - 每个会话现在显示其唯一的 URI，便于引用
  - 支持复制粘贴格式，方便在 URI 模式中使用
- **开发命令** - 新增 `just isok` 命令，一键运行 lint、check 和 test

### 问题修复

- **会话列表中断处理** - 正确处理退出和中断信号
  - `display_sessions_list` 返回布尔值指示用户是否退出
  - 将 `EOFError` 和 `KeyboardInterrupt` 作为退出信号处理

## [0.3.0] - 2026-02-23

### 破坏性变更

- **CLI 默认行为变更**：直接运行 `agent-dump` 现在显示帮助信息，而不是进入交互模式
  - 使用 `--interactive` 参数进入交互式选择模式
  - 仅使用 `--days N` 时自动启用列表模式

### 新增功能

- **列表模式支持分页** (`--list`)
  - 新增 `--page-size` 参数控制每页显示数量（默认：20）
  - 交互式分页，按 Enter 查看更多，输入 'q' 退出
- **交互模式时间分组**
  - 会话按时间分组：今天、昨天、本周、本月、更早
  - 时间组之间显示视觉分隔符，便于导航
- **大量会话警告**：当发现超过 100 个会话时显示警告，建议使用 `--days` 缩小范围

### 问题修复

- **`--days` 过滤在 `--list` 模式下现在正常工作**
  - 之前显示所有扫描的会话，忽略时间过滤
  - 现在根据指定的时间范围正确过滤会话
- **时区兼容性**：修复 naive 和 aware datetime 之间的比较错误
  - Claude Code 和 Codex 使用 UTC 时区感知的 datetime
  - OpenCode 和 Kimi 使用无时区的 datetime
  - 所有比较现在统一归一化为 UTC

### 改进

- 交互式 Agent 选择现在根据 `--days` 参数显示过滤后的会话数量
- 更好的用户体验，提供清晰的提示和导航说明

## [0.2.0] - 2026-02-22

### 新增功能

- 多 Agent 支持的扩展架构
  - 新增 `BaseAgent` 抽象类和 `Session` 数据模型
  - 实现 OpenCode、Codex、Kimi 和 Claude Code 的 Agent
  - 新增 `AgentScanner` 用于发现可用 Agent 和会话
  - 重构 CLI 以支持 Agent 选择和统一导出格式
- Claude Code 和 Codex 的智能会话标题提取
  - Claude Code: 优先使用 `sessions-index.json` 元数据中的标题
  - Codex: 优先使用全局状态 `thread-titles` 缓存中的标题
  - 两者: 当元数据不存在时回退到消息提取

### 变更

- 交互式选择库从 `inquirer` 更换为 `questionary`
- 使用 `agents/` 目录重新组织项目结构
- 移除旧的 `db.py` 和 `exporter.py` 模块，采用基于 Agent 的新架构
- 更新测试以适配新架构

### 改进

- 所有 Agent 的错误处理，添加 try-catch 块和描述性错误消息
- 标准化导入，统一使用 UTC 时区处理
- 修复 selector 模块中的键绑定安全检查
- 改进 Claude Code 内容列表格式的标题提取
- 所有 Agent 使用一致的文件打开模式

## [0.1.0] - 2025-02-21

### 新增功能

- 首次发布 agent-dump
- 支持 OpenCode 会话导出
- 使用 questionary 提供交互式会话选择
- 导出会话为 JSON 格式
- 具有多个选项的命令行界面
  - `--days` - 按最近天数过滤会话
  - `--agent` - 指定 AI 工具名称
  - `--output` - 自定义输出目录
  - `--list` - 仅列出会话而不导出
  - `--export` - 导出指定会话 ID
- 完整的会话数据导出，包括消息、工具调用和元数据
- 支持 `uv tool install` 和 `uvx` 运行

[0.6.13]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.13
[0.6.12]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.12
[0.6.10]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.10
[0.6.11]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.11
[0.6.8]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.8
[0.6.9]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.9
[0.6.7]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.7
[0.6.6]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.6
[0.6.5]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.5
[0.6.4]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.4
[0.6.3]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.3
[0.6.2]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.2
[0.6.1]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.1
[0.6.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.0
[0.5.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.5.0
[0.4.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.4.0
[0.3.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.3.0
[0.2.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.2.0
[0.1.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.1.0
