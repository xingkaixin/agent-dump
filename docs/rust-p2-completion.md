# P2 最终验收

状态：进行中。本文集中跟踪 P2 收尾，不把历史分批报告中的开放项自动视为完成。

Python 参考仍为 `dca2d97`，P0 evaluator 为 `9c1cf61`。所有来源均为临时合成数据，Python 生产入口保持不变。

## 收尾清单

- [x] 正文缓存：LRU、lease、并发读取合并、消费隔离、失败重试、source/title/time/WAL 失效、Cursor 当前配置和旧 Session 的关系。
- [x] 大整数与非标准 JSON 数值、Unicode 表示、日期边界、非字符串 cwd/version，见 [极端值验收](rust-extreme-values-parity.md)。
- [x] 剩余结构/错误输入：SQLite BLOB 与 Provider 错误原因，见[存储验收](rust-storage-lifecycle-parity.md)。
- [x] 诊断：支持的 Provider/URI/导出路径的底层原因、异常类别、非法导出 ID 和文件系统失败，见[错误原因验收](rust-error-reasons-parity.md)。
- [x] 来源生命周期：操作间变化、boot-config 编辑/损坏/恢复，读取事务与 WAL/checkpoint 行为。
- [ ] 跨平台：macOS、Linux、Windows 上运行 P2 差分和边界用例，记录真实结果。
- [ ] 行为映射与历史开放项复核；明确 P3–P6 的原定范围。
- [ ] 完整 `just isok`、release 构建、干净版本原七场景配对 benchmark。
- [ ] 更新迁移计划和 Rust README，合理拆分提交并提交最终状态报告。

P3 查询/索引/维护，P4 配置/shortcut/Collect/summary，P5 Ratatui，P6 完整安装/分发/发布切换，保持原计划边界。P2 的跨平台运行验证不代替 P6 的各平台安装与制品验收。

## Provider 行为矩阵

下列行均覆盖发现、URI 查找、head、正文、支持格式与部分失败。证据为实际 Python/Rust CLI 差分；同实例与并发契约由 Rust 单元测试和独立 Python 参考核验补足。

| Provider | 存储与版本 | 支持的导出 | 主要证据 |
| --- | --- | --- | --- |
| Codex | session JSONL、全局标题索引 | print / JSON / Markdown / raw | `test_cli_parity.py`、`test_codex_transcript.py`、`test_codex_patch.py` |
| Claude Code | 项目 JSONL、项目标题索引 | print / JSON / Markdown / raw | `test_claude.py`、`test_title_cache.py` |
| Kimi | context、旧 wire、metadata 与目录映射 | print / JSON / Markdown / raw | `test_kimi.py` |
| Pi | header、树节点、custom/compaction | print / JSON / Markdown / raw | `test_pi.py` |
| OpenCode | 旧表与 V2，V2 优先 | print / JSON / Markdown / raw JSON | `test_sqlite_legacy.py`、`test_opencode_v2.py` |
| ZCode | macOS/Windows 旧表；Linux 无默认来源 | print / JSON / Markdown / raw JSON | `test_sqlite_legacy.py`、`test_sqlite_paths.py` |
| Cursor | global KV、requestId/composer、子会话 | print / JSON | `test_cursor.py`、`test_source_boundaries.py` |
| DeepChat | 未加密 SQLite、结构化与 content 回退 | print / JSON / Markdown | `test_deepchat.py`、`test_desktop.py` |
| Cherry Studio | topic 当前父链、Agent 会话、软删除迁移前后 | print / JSON / Markdown | `test_cherry.py`、`test_desktop_paths.py` |
| MiniMax Code | columnar v3、完成展示迁移的消息行 | print / JSON / Markdown | `test_minimax.py` |

不支持的格式整体拒绝；不是悄悄生成不完整文件。未知 Provider schema 继续遵循 Python 的拒绝或跳过规则，不执行数据迁移。JSON 排版不作为契约，JSON 字段值及嵌套字符串、Markdown、JSONL raw、退出码和输出流属于契约。

## 历史开放项复核

| 历史报告中的开放项 | 收尾证据与结论 |
| --- | --- |
| discovery facts、跨来源部分失败和 i18n | [共享发现](rust-discovery-parity.md)、[URI](rust-uri-parity.md)、Provider/record diagnostics 套件 |
| 标题索引刷新、发现重试、固定与动态来源选择 | [标题缓存](rust-title-cache-parity.md)、[来源选择](rust-source-selection-parity.md)、[运行中配置](rust-runtime-sources-parity.md)及 boot-config 生命周期 |
| 正文 LRU/lease、并发读取、消费隔离、失效 | [缓存验收](rust-session-cache-parity.md)，真实 WAL 与 checkpoint，旧 Session/Cursor 当前配置区别保留 |
| 超大 token/cost、非有限数、Unicode、非字符串 cwd、年份边界 | [极端值验收](rust-extreme-values-parity.md)的 101 个差分用例 |
| 底层原因、异常类别、无效 ID、输出目录失败 | [错误原因](rust-error-reasons-parity.md)、[存储输入](rust-storage-lifecycle-parity.md)，只规范化随机临时文件名 |
| 历史存储、BLOB、迁移或来源消失、锁竞争 | 各 Provider 的旧/新 schema 与 capability 拒绝、已定位源变化单元测试、BLOB 矩阵、真实独占锁超时与恢复 |
| 超长子会话链 | Cursor 128 层引用链差分、已有自引用/互引用/重复引用测试 |
| 单次操作内配置/文件改写的所有竞争 | 已验收定位后移走/替换、加载中信号变更、事务快照；Python 不承诺的跨文件原子快照不新增为迁移功能，详见[生命周期边界](rust-storage-lifecycle-parity.md) |
| 完整 Query/usage/参数组合、保存的默认目录语言、批量交互等 | 依赖尚未迁移的命令，按原计划在 P3/P4/P5 与 P6 整体 CLI 验收；P2 文件导出继续显式 `--output` |
| 更多 Provider 性能场景、索引 WAL/旧请求竞争 | P3 扩展 evaluator；保留 P0 原工作负载以便历史比较 |
| Windows/Linux 执行与平台安装制品 | 本次三平台 Rust CI 验证执行；wheel/npm、libc 与全部发布架构仍按原计划 P6 |

“完成”按上述功能与证据矩阵判定，不等同穷举任意畸形字节、任意版本 schema 和所有线程调度。既有差异仍明确保留：Rust 拒绝导出到四个桌面 Provider 的源目录，满足仓库源只读约束；SQLite SHM 可能作为原生协调文件变化，数据库/WAL 持久数据必须不变。
