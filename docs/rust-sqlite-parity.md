# P2：OpenCode / ZCode 差分验收

> 历史分批记录：下文状态与计数描述该批提交。开放项的收尾证据与后续阶段归属统一见 [P2 最终验收](rust-p2-completion.md)。

本批在 `feat/rust-rewrite` 接入 OpenCode 旧表、V2 及 ZCode 旧表，继续保持 Python 发布实现和 P0 evaluator 不变。范围为显式单 Provider 列表、URI/head/print/JSON/Markdown/raw；不代表查询、索引、缓存及全部 Provider contract 已完成。

## 行为映射

| Python 契约 | Rust 实现 | 差分入口（`rust/tests/`） |
| --- | --- | --- |
| OpenCode 显式数据库、相对路径、XDG/default/fallback，显式缺失不回退，`:memory:` 不可用 | `sqlite_provider.rs` | `test_sqlite_paths.py`：绝对/相对/特殊字符、缺失源、不创建数据库、绑定标识符 |
| ZCode macOS/Windows 路径和旧表契约 | `sqlite_provider.rs`、`sqlite_legacy.rs` | `test_sqlite_legacy.py`：中英文列表/head/四种输出；不支持的平台显式跳过 ZCode 用例 |
| 旧表 metadata、最新模型、未知计数、subtargets、消息/part 排序、500 ID 分批读取 | `sqlite_provider.rs`、`sqlite_legacy.rs` | 同上：缺表 head、nullable metadata、长 subtargets、1003 条新增消息跨批次完整导出 |
| 旧表 text/reasoning/tool/step、未知 part、token/cost、损坏记录跳过 | `sqlite_legacy.rs` | 同上及 `test_sqlite_paths.py`：类型变体、时间/费用转换、坏 JSON/NULL/非对象继续读取健康消息 |
| OpenCode V2、新旧共存、同 ID 优先级先于日期窗口 | `sqlite_provider.rs` | `test_opencode_v2.py`：共存、旧表独有会话、跨窗口同 ID、缺投影表 head 与读取失败 |
| V2 的 seq、11 种消息、未知类型、附件/状态/工具/元数据、会话累计统计 | `opencode_v2.rs` | 同上：seq 与时间不同序、工具生命周期、分段参数、文件引用、unmapped content、费用/token 两种口径不相加 |
| V2 损坏正文必须失败，不能回退旧副本或导出伪空内容 | `opencode_v2.rs`、`uri_workflow.rs` | 同上：正文/工具类型错误导致全部格式失败且无输出文件；head 仍可投影计数 |
| SQLite raw 为标准化单会话 JSON，普通 JSON 保留 developer | `provider.rs`、`uri_workflow.rs`、`export.rs` | 两个 SQLite 套件的混合导出；Pi developer 回归用例保护共享默认投影，Codex 保留专属 JSON 转换 |
| 数据库只读、WAL 更新可见、导出源目录保护 | `sqlite.rs`、`export.rs` | `test_sqlite_legacy.py`：DELETE/WAL 两次提交、新 CLI 读取当前正文、持久字节不变、源目录拒写 |

成功路径比较退出码、完整 stdout/stderr、JSON 对象、Markdown 字节及文件权限。JSONL raw 比较原字节；SQLite `.raw.json` 比较 JSON 对象，空白排版与对象键顺序不作为契约。错误诊断文案仍未完全对齐，异常测试比较失败/恢复行为、文件内容和持久源数据。旧表坏消息/part 的后续完整中英文差分见[坏记录警告验收](rust-record-diagnostics-parity.md)。

## SQLite 读取与共享模块

使用 rusqlite 0.40.2 的 bundled SQLite 3.53.2，关闭未使用的默认 cache/WASM 特性。连接显式使用 `SQLITE_OPEN_READ_ONLY`，不使用 CREATE；启用 `query_only` 并在读事务中查询，所有外部 ID 与时间条件通过参数绑定。源码依据：[rusqlite OpenFlags](https://docs.rs/rusqlite/0.40.2/rusqlite/struct.OpenFlags.html)。

正文连接使用 `Session.source_path`。V2 重新读取当前会话行与消息；已发现为 V2 的会话消失时失败，不读取同 ID 旧副本。旧表消息和 part 各自按源时间排序；V2 按 seq 排序。Provider 的发现快照存放在 `source_metadata`，工作流和 renderer 不解释其中的 schema。

文件 raw 与 SQLite raw 由 `RawExport` 表达。URI 工作流按需准备一次标准化正文，JSON、Markdown、SQLite raw 共用结果；JSONL raw 仍可在正文解码失败时成功。SQLite raw 不复制整个数据库，也不访问消息内引用的附件或 URL。

WAL 验证明确区分数据库/`-wal` 持久会话数据和 SQLite `-shm` 协调文件。Python 与 Rust 都通过 SQLite 原生只读连接读取；SQLite 仍可创建或维护 WAL 共享内存和空 sidecar。测试核对持久内容不变，不把它描述为“会话目录内所有字节均不变”。这符合当前 Python 的 SQLite 路径；完全禁止 SQLite 协调文件写入的离线读取方式尚未实现。[SQLite WAL 说明](https://www.sqlite.org/wal.html#read_only_databases)

## 本机验证

2026-09-24，macOS arm64，固定 Rust 1.90.0：完整 `just isok` 通过，Python 2596 passed / 1 skipped，Rust CLI 差分与边界 393 passed，npm 74 passed，网页 E2E 13 passed。`cargo build --locked --release` 成功。

新增 79 个 SQLite 用例和 1 个 Pi developer 回归用例。测试只使用临时合成数据，没有访问真实用户会话目录。Python 生产源码与 `dca2d97` 相同；原 P0 evaluator 与 fixture 未修改。

实现提交：`aec8b47`。[六场景性能报告](benchmarks/rust-p2-sqlite.md)保留两轮配对测量与全部原始样本；新增的 OpenCode V2 列表通过原比较器，第二轮为 Python 148.94 ms / Rust 9.15 ms。两种实现使用不同 SQLite 版本，不能把差异全部归因于语言。

## 仍需验收

- 完整 CLI 参数、跨 Provider 可用性/部分失败计数、诊断 i18n、查询/统计/索引/配置/交互。
- 长生命周期缓存、lease/LRU、数据库与 WAL 变化失效、并发读取合并；本批验证的是每次新 CLI 读取当前提交。
- 数据库在发现与正文读取间迁移或消失、并发 checkpoint 和锁竞争的全面验收；当前代码使用独立读取事务，尚无长期会话 API。
- BLOB 列、非标准 JSON 数值、超出 i64 的时间/token 数值与 Python 任意精度整数，仍不保证等价。
- Windows 的实际路径与制品、Linux 的实际运行；本机结果仅代表 macOS arm64。ZCode 按 Python 当前行为不在 Linux 发现会话。
- SQLite 正文导出的代表性性能工作负载。原 evaluator 的 `list-sqlite` 可复测 V2 列表；它不能代表 ZCode 或所有 SQLite 操作。

Python API、pip/npm 默认入口、发布流程不在本批切换。P2 整体仍未完成。
