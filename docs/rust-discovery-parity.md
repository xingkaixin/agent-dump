# P2：共享发现与跨 Provider 列表验收

Rust 现在支持不带查询的 `--list`，以及 `-q provider:codex,opencode`。Provider 过滤先于发现执行；分组按 Python 注册顺序展示。Python 源码和 P0 evaluator 保持不变，pip/npm 仍使用 Python。

## 行为映射

| Python 契约 | Rust 实现 | 验证 |
| --- | --- | --- |
| `ProviderDiscovery` 在一次发现中返回可用性、会话与完整性 | `provider.rs` 的 `Discovery`；`failures` 非空表示部分发现失败，不依赖是否打印警告 | `file_sessions.rs` 单元用例：文件消失后保留其他会话和失败事实；全失败与无候选不同 |
| 文件源有候选即可用，日期过滤后可以没有会话 | `file_sessions.rs`；不存在和空目录不可用，有空文件或旧文件仍可用 | `test_discovery.py`：不存在、空目录、空候选、旧会话 |
| SQLite 源存在且读取成功即可用，空表仍可用 | `sqlite_provider.rs`、`desktop.rs`、`cursor.rs` | 空数据库、空日期窗口；原有各 Provider 套件继续验证 schema |
| Provider 过滤先于扫描；分组保持注册顺序 | `registry.rs`、`list_workflow.rs` | 大小写、去重、`claude` 别名、十个 Provider 同时存在；Linux 按既有行为不包含 ZCode |
| 单个 Provider 初始化/读取失败不阻止其他 Provider | `list_workflow.rs` 捕获每个 Provider 的失败并继续 | 坏 SQLite、坏 Cherry boot-config；显式范围不扫描未选中的坏来源 |
| 单文件或单会话失败保留其余结果 | 文件发现、Cherry、MiniMax 返回逐源失败 | 坏 Codex header、Cherry 分支和 MiniMax 待迁移记录；比较恢复后的完整 stdout，检查警告和源 hash |
| 无来源时的退出码与诊断输出 | `render.rs` 的列表诊断及 Provider 所属路径候选 | 中英文完整 stdout/stderr 差分；无过滤返回 1，显式范围无可用来源返回 0；全部来源失败返回 1 |
| 中英文列表、摘要开关与时间窗口 | 共享分组 renderer | 全部 Provider 的输出、`--no-metadata-summary`、旧日期窗口；源文件 hash 不变 |
| 不支持的查询不能静默扩大扫描范围 | 仅接受当前支持的 Provider 查询子集 | 空查询、关键词、角色组合明确报错；完整查询仍属 P3 |

本批新增 44 个 CLI 用例，移除旧的“`--list` 尚不支持”拒绝用例；CLI 差分和边界套件现为 597 个。另有 1 个 Rust 单元用例保护不打印警告时的失败事实。`just check-rust` 已加入 `cargo test --locked`，本地与 Linux/macOS CI 使用同一入口。

实现提交：`92bace3`。性能证据见[七场景复测](benchmarks/rust-p2-discovery.md)。

本机 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 单元测试 1 passed，CLI 差分与边界 597 passed，npm 74 passed，Web E2E 13 passed。固定工具链 release 构建通过。本批未运行远端 CI，也没有关闭 Windows 验收项。

## 实现边界

发现结果保存失败源与原始错误，列表工作流负责本地化和 stderr 输出。会话结果不重新扫描；空结果诊断会重新装配 Provider 的路径候选，但不读取会话内容。Codex 标题索引读取已从构造阶段移至发现/定位操作，生成路径诊断时不会读标题索引。

各 Provider 继续拥有自己的路径、schema 和消息解释。列表 renderer 只接收稳定的 Provider 信息和 Session。没有新增依赖、并发框架或运行时 Python 调用；当前 Rust 按注册顺序逐个发现，Python 使用线程池。后续性能结论比较这两种实际实现。

`Discovery.failures` 对应 Python `complete=False` 的事实；不增加与失败集合重复的布尔状态。未来 Collect/维护工作流必须消费整体错误及这个集合，不能把不完整发现当作无匹配。本批只迁移列表路径，没有声称完成这些后续工作流。

## 仍待对齐

- SQLite/JSON/文件系统错误的类型名、底层文案和部分能力诊断尚未与 Python 完全一致。失败用例保留此差异，不把 stderr 规范化后声称完全一致；无来源诊断与正常输出直接全量比较。
- 后续已迁移 [URI 共用诊断](rust-uri-parity.md)与逐文件查找警告；JSONL 坏行、Claude 标题索引等仍未全部接入可选择的诊断输出。
- Provider 实例复用时的源路径刷新、标题与正文缓存、并发读取合并和变更失效仍需逐项验收。本批 CLI 每次运行创建新实例，不以进程间复测代替实例复用测试。
- 完整 Query/Search、列表忽略选项提示、维护命令、Collect、配置、TUI 与跨平台发布验收仍待后续阶段。

P2 仍在进行中。十个来源可共同列出，不代表完整功能矩阵已经关闭。
