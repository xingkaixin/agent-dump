# Rust 迁移计划

状态：P0、P1 已完成；P2 进行中，十个 Provider 均已接入消息装配与支持格式的单 URI 导出；共享发现、URI 诊断、源缺失、JSONL/旧 SQLite 坏记录警告、Codex/Claude 标题缓存及 Codex/Claude/Pi 记录转换恢复已接入。接下来验收来源刷新和剩余极端输入/缓存边界。Python 仍是默认实现和发布来源。

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

每一行在实施阶段补充 Rust 代码、eval/测试入口及通过记录。已有 Python 测试是行为依据。P1 只覆盖参数、Codex、Session facts 和 URI/导出中的子集，尚无一整行可标记为完整迁移；当前实现见 [Rust README](../rust/README.md)，Codex 消息与导出证据见[差分验收记录](rust-codex-parity.md)，历史 P1 性能见[复测报告](benchmarks/rust-p1.md)。

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
| 配置 / shortcut | TOML 保留注释与顺序、写入权限、API key 遮蔽、坏配置处理、默认导出目录、参数展开 | `tests/test_config.py`、`tests/test_cli.py`、`tests/test_cli_shortcuts.py` |
| 交互 / i18n | Provider 单选、会话分组多选、q/Q/空格/回车/Ctrl+C、非 TTY stdin fallback、中英文、安全文本 | `tests/test_selector.py`、`tests/test_i18n.py`、`tests/test_text_safety.py` |
| 诊断 / 维护 | 部分失败独立计数、stdout/stderr 路由、stats、providers/capabilities、reindex | `tests/test_recoverable_diagnostics.py`、`tests/test_maintenance_workflow.py` |
| 分发 | pip/uv tool/uvx、npm/npx/bunx、版本一致性、校验和、安装隔离、发布顺序 | `packaging/`、`npm/`、`.github/workflows/release.yml` |

## 3. 分阶段实施

### P0：固定 Python 参考与评估工具

- [x] 创建迁移分支并固定参考 commit。
- [x] 建立可直接接受 CLI 命令的 benchmark，不 import 业务模块。
- [x] 生成确定性的 JSONL 与 SQLite 数据；在临时目录隔离所有 Provider、配置、缓存与导出。
- [x] 测量启动、列表、head/print、单会话与批量导出、冷/热索引查询、collect 本地流程。
- [x] 保存 Python 源码运行与 PyInstaller 原生制品基线及说明。
- [x] 验证评估工具确实拒绝错误结果，并运行项目门禁。

完成记录：[2026-09-24 Python 基线](benchmarks/python-baseline.md)。17 个场景，每场景 1 次预热、7 次测量；源码与 PyInstaller 制品的校验摘要一致。`just isok` 通过。

本阶段的性能数据只代表已列出的合成工作负载，不宣称覆盖所有 Provider、真实使用分布或完整功能一致性。

### P1：第一条 Rust 端到端路径

- [x] 新建独立 Rust crate、固定工具链与锁文件；Python 仍是默认实现。
- [x] 实现参数入口、轻量 Session 字段、Codex 发现/URI/head/print/JSON 导出的首条路径。
- [x] 对齐普通 text/reasoning 分组与 JSON 字段；尚未迁移的工具、计划、上下文等消息明确报错，不产出遗漏内容的导出。
- [x] 通过同一 evaluator 验证四个已实现性能场景，保存 Python 源码、PyInstaller 与 Rust release 的原始报告。
- [x] 保持单 crate 和明确模块归属，不引入插件系统、FFI、服务端或通用任务框架。
- [x] 增加 `just check-rust`、接入 `just isok` 和 Linux/macOS CI job。

实现提交：`b473f37`；相对导出路径修复：`c5053fd`。本机 `just isok` 通过：Python 2596 passed / 1 skipped，Rust/Python 差分及边界用例 53 passed，npm 74 passed，Web E2E 13 passed。路径修复新增 1 个差分用例后，`just check-rust` 再次通过，现为 54 个。未运行远端 CI，Windows 仍待验证。

[复测报告](benchmarks/rust-p1.md)：相对本次 Python 源码复测，version、Codex 列表、head、print 的耗时中位数分别改善为 33.66×、5.40×、21.98×、2.63×。这不代表全量应用或最终发布制品的性能。JSON 已做功能差分；现有导出 benchmark 同时要求 Markdown，因此未列为本阶段通过项。

P1 的明确限制：只支持显式 `provider:codex` 列表；JSON 必须传入 `--output`；配置不读取。复杂 Codex 消息、其他 Provider、完整参数组合/错误文案/部分成功行为尚待实现，详见 [Rust README](../rust/README.md)。

### P2：Provider 与导出对齐

- [x] Codex 工具调用/输出、patch、计划审批、skill/subagent、注入上下文；非文本和未知事件按 Python 当前规则忽略，移除 P1 的临时拒绝分支。
- [x] Codex Markdown/raw/混合导出、JSON 专用转换隔离、逐格式部分成功与源数据保护；使用实际 CLI 做差分验收。
- [ ] Codex 发现刷新/缓存、完整诊断、极端输入和跨平台验收，见[剩余边界](rust-codex-parity.md)。
- [x] Claude Code、Kimi（context / wire）、Pi 的发现、head、消息装配和 print/JSON/Markdown/raw 导出；共享 Provider 入口与只读文件发现，见[行为映射与剩余边界](rust-jsonl-parity.md)。
- [x] OpenCode 旧表 / V2 与 ZCode 的发现、head 和单 URI 四种导出，见[SQLite 差分记录与剩余边界](rust-sqlite-parity.md)。
- [x] Cursor / DeepChat / Cherry Studio / MiniMax 的发现、head、消息读取与支持格式导出，见[本批差分记录](rust-desktop-parity.md)。
- [x] 统一 discovery 的可用性与逐源失败事实、跨 Provider 列表/隔离、中英文无数据诊断，见[共享发现验收记录](rust-discovery-parity.md)。
- [x] URI 格式/无匹配/Provider 格式能力拒绝的中英文诊断，读取/导出失败的输出通道及 head 参数组合，见[URI 验收记录](rust-uri-parity.md)。
- [x] DeepChat / Cherry / MiniMax 的 schema、不可读来源和迁移诊断，定位后源消失/变化的读取边界，见[专属错误验收](rust-provider-errors-parity.md)。
- [x] 其余七个 Provider 的源缺失诊断、Kimi raw 快照文件身份和 OpenCode V2 消失后的错误原因，见[源缺失验收](rust-source-parity.md)。
- [x] JSONL 坏行与旧 SQLite 坏消息/part 的可恢复警告，中英文完整输出及 raw 行为，见[坏记录警告验收](rust-record-diagnostics-parity.md)。
- [x] Codex/Claude 标题索引失败回退、坏条目汇总、本地化警告及同实例标题缓存刷新，见[标题缓存验收](rust-title-cache-parity.md)。
- [x] Codex/Claude/Pi 记录转换失败的恢复与本地化警告，覆盖消息类型、Claude 非对象 message、Pi UTC 日期溢出和状态保留，见[转换恢复验收](rust-message-conversion-parity.md)。
- [ ] Provider 专属错误、底层错误文案、复用实例的发现刷新/缓存与所有 Provider 剩余边界；十个入口接通不代表 P2 完整验收。
- 按 JSONL Provider、SQLite Provider、桌面聊天 Provider 分批迁移。
- 每批增加合成 fixture 与差分验收，覆盖 malformed/缺字段/旧 schema/部分失败。
- 对齐 metadata、消息装配、raw/JSON/Markdown 和数据源只读契约。

Codex 本批实现：`ca4b1db`；benchmark 发现并修复 JSON 小写入瓶颈：`1c037d3`。优化后 `just isok` 通过，Rust 差分与边界用例现为 172 个。[五场景复测](benchmarks/rust-p2-codex.md)中，JSON＋Markdown 导出相对同期 Python 源码为 2.88×，峰值 RSS 中位数下降约 65%；原始慢路径数据同样保留。P2 整体仍未完成。

Claude Code / Kimi / Pi 实现：`3669542`，新增 141 个差分及边界用例，合计 313 个；本机完整 `just isok` 与 release 构建通过。已验证具体行为与未关闭边界见[JSONL Provider 验收记录](rust-jsonl-parity.md)。[原五场景复测](benchmarks/rust-p2-jsonl.md)全部通过，Codex JSON＋Markdown 导出为 Python 241.28 ms / Rust 74.89 ms（3.22×）；未测量三个新 Provider 的性能，不将接入或 benchmark 通过计作完整功能迁移完成。

OpenCode / ZCode 实现：`aec8b47`，新增 79 个 SQLite 用例和 1 个 Pi 回归用例，合计 393 个；本机完整 `just isok` 与 release 构建通过。[六场景复测](benchmarks/rust-p2-sqlite.md)增加原有 OpenCode V2 列表，两轮均通过比较器；第二轮列表为 Python 148.94 ms / Rust 9.15 ms（16.28×）。两轮原始数据、引擎版本差异、体积增长及波动说明均已保留。具体范围与剩余边界见[SQLite 验收记录](rust-sqlite-parity.md)。

Cursor / DeepChat / Cherry Studio / MiniMax 实现：`a884907`，新增 161 个差分及边界用例，合计 554 个；本机完整 `just isok` 与 release 构建通过。四个源目录拒写用例只验证 Rust 约束，与 Python 的差异单独记在[本批验收记录](rust-desktop-parity.md)。[原六场景复测](benchmarks/rust-p2-desktop.md)全部通过，Codex JSON＋Markdown 导出为 Python 267.47 ms / Rust 79.13 ms（3.38×）；相对上一批 Rust 导出耗时增加约 6.1%，保留这一历史变化，不将其归因于单一代码修改。十个 Provider 已接入不代表 P2 完整验收。

共享发现实现：`92bace3`，新增 44 个 CLI 用例、移除旧拒绝用例后，CLI 差分与边界套件为 597 个，另有 1 个 Rust 单元用例。完整 `just isok`、最终 Rust 门禁及 release 构建通过。[七场景复测](benchmarks/rust-p2-discovery.md)增加原有 `list-all`：1001 个会话的列表为 Python 246.17 ms / Rust 50.77 ms（4.85×），峰值 RSS 中位数为 43.98 / 9.41 MiB。剩余诊断、缓存/刷新和跨平台缺口见[验收记录](rust-discovery-parity.md)。

URI 共用诊断实现：`f3af42a`，新增 84 个 CLI 用例，合计 681 个；完整 `just isok` 与 release 构建通过。[原七场景复测](benchmarks/rust-p2-uri.md)全部通过，跨 Provider 列表为 Python 257.45 ms / Rust 50.94 ms（5.05×），JSON＋Markdown 导出为 253.94 / 78.26 ms（3.24×）。这些成功场景不测错误诊断耗时；Provider 专属错误和底层文案等剩余项见 [URI 验收记录](rust-uri-parity.md)。

桌面 Provider 专属错误实现：`99575b9`，CLI 套件净增 25 个用例至 706 个，新增 4 个读取边界单元用例至 5 个；完整 `just isok` 与 release 构建通过。源消失/schema 变化的读取验证与 CLI 差分分别记录在[验收清单](rust-provider-errors-parity.md)。[原七场景复测](benchmarks/rust-p2-provider-errors.md)全部通过：跨 Provider 列表为 Python 249.61 ms / Rust 51.37 ms（4.86×），JSON＋Markdown 导出为 247.53 / 78.95 ms（3.14×）；未测量三个桌面 Provider 或错误路径的性能。

其余七个 Provider 的源缺失与 Kimi raw 文件身份实现：`0d2fc2a`，新增 10 个 Rust 单元用例至 15 个，CLI 套件保持 706 个；完整 `just isok` 与 release 构建通过。OpenCode V2 行/表消失时保留不同原因且不读取旧表副本；具体读取边界和 Python 参考核验见[验收记录](rust-source-parity.md)。[原七场景复测](benchmarks/rust-p2-source-errors.md)全部通过：跨 Provider 列表为 Python 239.77 ms / Rust 51.39 ms（4.67×），JSON＋Markdown 导出为 231.07 / 77.26 ms（2.99×）；未测量 Kimi 或失败路径性能。

JSONL 坏行与旧 SQLite 坏消息/part 警告实现：`dd95821`，通过显式诊断 sink 接入 URI 工作流，并修正 BLOB 坏记录使旧表导出整体中止的问题。新增 30 个完整 CLI 差分用例，替代 4 个旧用例，净增 26 个至 732 个；完整 `just isok` 与 release 构建通过。中英文文案、次数、静默扫描与源数据验证见[坏记录警告验收](rust-record-diagnostics-parity.md)。[原七场景复测](benchmarks/rust-p2-record-warnings.md)全部通过：跨 Provider 列表为 Python 246.92 ms / Rust 53.69 ms（4.60×），JSON＋Markdown 导出为 276.68 / 79.03 ms（3.50×）；不测坏记录警告或旧 SQLite 性能。

Codex/Claude 标题缓存恢复实现：`768e4ba`。索引不可读不再中止 Codex 发现，Claude 缺少 `entries` 按空索引处理，坏条目汇总告警，非空非字符串 summary 保留对应会话解析失败。新增 52 个 CLI 用例及 2 个同实例刷新用例，完整 `just isok` 与 release 构建通过，CLI 套件共 784 个、Rust 单元测试 17 个。底层原因文本的部分比较范围见[本批验收](rust-title-cache-parity.md)。[原七场景复测](benchmarks/rust-p2-title-cache.md)全部通过：跨 Provider 列表为 Python 253.62 ms / Rust 51.02 ms（4.97×），JSON＋Markdown 导出为 248.25 / 81.68 ms（3.04×）；不测 Claude、损坏索引或缓存刷新性能。

Codex/Claude/Pi 记录转换恢复实现：`fa39040`。新增 48 个 CLI 完整差分用例，覆盖失败后继续读取、工具关联与统计、警告顺序和静默 metadata/raw 路径，并单独保留 Codex metadata 阶段的会话失败语义。完整 `just isok` 与 release 构建通过，CLI 套件共 832 个、Rust 单元测试 17 个。已验证的错误类型与剩余数值/日期边界见[本批验收](rust-message-conversion-parity.md)。[原七场景复测](benchmarks/rust-p2-message-conversion.md)全部通过：跨 Provider 列表为 Python 256.68 ms / Rust 51.71 ms（4.96×），JSON＋Markdown 导出为 252.59 / 82.58 ms（3.06×）；报告保留本轮 Python 前三个场景的明显波动，不测 Claude、Pi 或坏记录恢复性能。

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

当前下一项：验收复用 Provider 实例的源目录刷新，再逐项关闭正文缓存和极端标题/消息/数值输入边界。记录转换恢复与已验证的警告类型已接入，不代表任意畸形输入全部对齐。Codex/Claude 标题索引的同实例刷新已验证，未进入生产 CLI 的私有标题提取包装不作为新增迁移入口。已接入 Provider 的剩余边界持续保留在验收清单；Ratatui 保持在 P5，pip/npm 发布切换保持在 P6。
