# Rust 迁移计划

状态：进行中，当前为 P0（Python 基线与验收准备）。

- 工作分支：`feat/rust-rewrite`
- Python 参考版本：`v0.15.9`，commit `dca2d97`
- 决策：核心逐步迁移到 Rust；保留 `agent-dump` 命令、PyPI 与 npm 安装渠道；PyPI 最终只承诺 CLI，不再承诺 Python import API。
- 交互方向：Ratatui + Crossterm。先保持现有选择、配置、取消和非 TTY 行为；正文预览等新增功能另行安排，不混入功能对齐验收。

## 1. 完成的定义

“100% 实现”指下面的功能清单全部完成，并有对应验收证据；不以代码行数、测试覆盖率或几个 benchmark 通过代替功能完整性。

切换默认实现之前：

1. 功能矩阵没有未实现项；有意差异逐项列出并确认，不把遗漏改写为差异。
2. 使用同一组合成输入运行 Python 参考实现和 Rust，实现外部行为差分验收。包括退出码、stdout/stderr、JSON/Markdown/raw 文件、配置和源数据不变性。
3. 现有行为测试的契约均映射到 Rust 测试或语言无关的 CLI eval；依赖 Python 内部结构的 mock 测试按行为重写。
4. macOS arm64/x64、Linux x64、Windows x64 的制品通过安装及运行验证；Linux wheel 明确 libc 和最低系统版本。额外架构单独增加，不默认为已覆盖。
5. 在同一台机器、相同数据与缓存条件下重跑性能评估，保留各场景原始样本、结果等价性及快慢变化，不只展示加速场景。

Python 库 API 的退场是已经选定的产品边界变化。迁移期间保留现有 API 与发布路径；切换时更新版本策略、README、skill recipes 和发布说明，明确旧版本仍提供 Python API。`python -m agent_dump` 等 Python 专属入口的去留也在切换清单中明确记录。

## 2. 功能验收矩阵

每一行在实施阶段补充 Rust 代码、eval/测试入口及通过记录。以下初始状态均为待迁移；已有 Python 测试是行为依据。

| 范围 | 必须对齐的契约 | 现有依据 |
| --- | --- | --- |
| 参数与分发 | 参数别名、默认值、组合校验、帮助、版本、优先级、忽略选项告警、退出码 | `command_plan.py`、`cli.py`、`tests/test_command_plan.py`、`tests/test_cli.py` |
| 发现与路径 | 各平台路径、环境变量覆盖、local fallback、日期窗口、Provider 顺序、部分失败 | `agents/`、`scanner.py`、`tests/test_scanner.py`、`tests/test_paths.py` |
| Codex | JSONL、索引标题、工具与消息装配、直接 URI 定位、bounded head | `tests/test_agents/test_codex*.py`、`tests/test_agents/test_jsonl_scan.py` |
| Claude Code / Kimi / Pi | 各自 transcript、标题、时间、模型、内部事件 | 对应 `tests/test_agents/` Provider 测试 |
| OpenCode / ZCode | 旧 SQLite 与 OpenCode V2、新旧共存、seq 排序、缺字段兼容 | `tests/test_agents/test_opencode*.py`、`test_zcode.py`、`test_sqlite_sessions.py` |
| Cursor | requestId、存储发现、消息拼接、可用导出能力 | `tests/test_agents/test_cursor.py` |
| DeepChat | 结构化消息与 content fallback、只读事务、WAL、raw 拒绝 | `tests/test_agents/test_deepchat.py`、`tests/test_cli_deepchat.py` |
| Cherry Studio | 普通聊天分支、Agent 会话、软删除 schema 兼容、未知计数 | `tests/test_agents/test_cherry.py`、`tests/test_cli_cherry.py` |
| MiniMax Code | columnar v3、展示行、内部事件、显式路径不回退 | `tests/test_agents/test_minimax.py`、`tests/test_cli_minimax.py` |
| Session facts / 缓存 | 已知/未知计数、工作目录与 Provider Project 分离、change sources、LRU、lease、并发读取合并 | `CONTEXT.md`、`tests/test_session_data.py`、`tests/test_agents/test_contracts.py` |
| URI / 导出 | URI 别名与路径前缀、head、print、JSON、Markdown、raw、文件名/目录、部分成功、源缺失 | `tests/test_uri_workflow.py`、`tests/test_exporting.py`、`tests/test_cli_export.py` |
| Query / Search | 字面短语与 AND terms 区别、角色/路径/Provider/limit、Unicode、snippet、全局相关度 | `tests/test_query_semantics.py`、`tests/test_query_filter.py`、`tests/test_cli_query.py` |
| 索引 | FTS5 等价加速、不可表达语义时 fallback、增量更新/删除、WAL 失效、旧请求竞态、重建 | `tests/test_search_index*.py`、`tests/test_bounded_concurrency.py` |
| Collect 本地处理 | 日期、排除规则、可见 user/assistant、chunk、归并边界、PM/INSIGHT、缺口报告、dry-run、emit-prompt | `tests/test_collect*.py`、`tests/test_cli_collect*.py` |
| LLM 请求与摘要 | OpenAI/Anthropic、结构校验、重试、并发上限、超时、输入上限、重定向凭据边界、URI summary | `tests/test_collect_llm.py`、`tests/test_collect_requests.py`、`tests/test_collect_reduction.py` |
| 配置 / shortcut | TOML 保留注释与顺序、写入权限、API key 遮蔽、坏配置处理、默认导出目录、参数展开 | `tests/test_config.py`、`tests/test_config_command.py`、`tests/test_cli_shortcuts.py` |
| 交互 / i18n | Provider 单选、会话分组多选、q/Q/空格/回车/Ctrl+C、非 TTY stdin fallback、中英文、安全文本 | `tests/test_selector.py`、`tests/test_i18n.py`、`tests/test_text_safety.py` |
| 诊断 / 维护 | 部分失败独立计数、stdout/stderr 路由、stats、providers/capabilities、reindex | `tests/test_recoverable_diagnostics.py`、`tests/test_maintenance_workflow.py` |
| 分发 | pip/uv tool/uvx、npm/npx/bunx、版本一致性、校验和、安装隔离、发布顺序 | `packaging/`、`npm/`、`.github/workflows/release.yml` |

## 3. 分阶段实施

### P0：固定 Python 参考与评估工具

- [x] 创建迁移分支并固定参考 commit。
- [ ] 建立可直接接受 CLI 命令的 benchmark，不 import 业务模块。
- [ ] 生成确定性的 JSONL 与 SQLite 数据；在临时目录隔离所有 Provider、配置、缓存与导出。
- [ ] 测量启动、列表、head/print、单会话与批量导出、冷/热索引查询、collect 本地流程。
- [ ] 保存 Python 源码运行与 PyInstaller 原生制品基线及说明。
- [ ] 验证评估工具确实拒绝错误结果，并运行项目门禁。

本阶段的性能数据只代表已列出的合成工作负载，不宣称覆盖所有 Provider、真实使用分布或完整功能一致性。

### P1：第一条 Rust 端到端路径

- 新建独立 Rust crate 与锁文件；Python 暂时仍是默认实现。
- 先实现参数入口、Session facts、Codex 发现/URI/head/print/JSON 导出。
- 同一 eval 命令测两种实现；只报告已实现子集，不使用部分结果声称迁移完成。
- 优先一个 crate 内的清晰模块；不预建插件系统、FFI、服务端或通用任务框架。

### P2：Provider 与导出对齐

- 按 JSONL Provider、SQLite Provider、桌面聊天 Provider 分批迁移。
- 每批增加合成 fixture 与差分验收，覆盖 malformed/缺字段/旧 schema/部分失败。
- 对齐 metadata、消息装配、raw/JSON/Markdown 和数据源只读契约。

### P3：查询、索引、维护命令

- 对齐 Query/Search 语义，然后实现 SQLite FTS5 与 fallback。
- 对齐缓存边界、增量索引、并发与旧请求竞态、stats/providers/reindex。
- benchmark 增加增量更新、删除、WAL 和更多 Provider 的代表性工作负载。

### P4：Collect、配置与完整自动化入口

- 对齐配置、shortcut、collect planning/reduction、URI summary、emit-prompt。
- 用本地确定性 HTTP 服务验收请求/重试/部分失败，不访问真实模型。
- 分开报告本地处理与模拟网络延迟；真实模型响应时间不计入语言加速结论。

### P5：Ratatui 交互

- 实现现有交互契约、输入与取消，保持非交互 CLI 独立。
- UI 接收 workflow 投影，不解释 Provider schema，不在绘制阶段发现或读取正文。
- 验收窄窗口、resize、中英文、粘贴、密码遮蔽与退出恢复；使用少量真实 PTY 测试覆盖终端边界。
- 首版不加无需求的动画、后台常驻服务或全屏配置中心。

### P6：完整验收、性能复测与发布切换

- 功能矩阵全部关闭后，使用 release 二进制重跑全部差分 eval 和性能场景。
- 同机交错运行 Python 与 Rust，检查差异和噪声；首份历史基线只作为参考。
- 使用 Maturin `bin` wheel 与现有 npm 平台包模式分发 Rust；不为 CLI 引入 PyO3。
- 验证所有当前发布平台、Linux libc 基线、wheel 与 npm 安装体验，记录制品大小。
- 更新 README、recipes、架构文档、版本来源和 CI；同步清理退场的 Python 构建路径。
- 用户审查后决定合并和发版；本计划不自动触发发布。

## 4. 评估规则

- **功能先于速度**：退出码正确还不够；同时检查会话集合、消息正文、文件数量与内容。差分只规范化临时路径、可执行入口等允许变化的字段。
- **语言无关**：基准通过子进程调用 CLI，Rust 必须接受同一组参数和 fixture；不通过 Rust 专用快路径绕过工作。
- **测量边界一致**：fixture 创建、校验、输出摘要在计时外；启动、读取、计算与实际文件写入在计时内。stdout/stderr 重定向到临时文件，不把终端绘制速度混入数据处理。
- **缓存可说明**：每次新进程；冷索引每次删除项目缓存，热索引预先构建。操作系统页缓存不清空，不能称为冷磁盘测试。
- **保留证据**：数据版本/hash、命令、参考 commit、环境、重复次数、原始 wall/CPU/RSS 样本、median/min/max、输出校验摘要。
- **逐场景比较**：耗时加速比为 Python/Rust；内存和体积变化单列。不将不同工作负载随意平均成一个总加速倍数。
- **覆盖缺口显式记录**：性能场景通过不代表功能矩阵通过；真实 LLM、交互响应、安装耗时和未生成的 Provider 数据需要各自验收。

## 5. 提交与后续任务

按可独立验证的阶段拆分提交：迁移计划、基准工具与测试、基线报告、Rust 首条功能路径、后续 Provider/工作流、分发切换。

每次结束更新阶段状态和下一项工作，保留 Python 参考实现。提交 PR 前运行 `just isok`；引入 Rust 后增加 `cargo fmt --check`、Clippy 和 Rust 测试门禁。发布切换之前，不把部分完成的 Rust 二进制发布为正式 `agent-dump`。

当前下一项：完成 P0，运行并归档可复现的 Python 基线。
