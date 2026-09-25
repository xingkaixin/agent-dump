# P2：Cursor / DeepChat / Cherry Studio / MiniMax 差分验收

> 历史分批记录：下文状态与计数描述该批提交。开放项的收尾证据与后续阶段归属统一见 [P2 最终验收](rust-p2-completion.md)。

本批补上四个 Provider 的显式单 Provider 列表、URI/head、正文读取和支持格式的单会话导出。十个 Provider 均已有 Rust 入口；共享 discovery 的完整性、缓存、诊断与全部工作流尚未迁移，因此 P2 仍未完成。Python 生产源码、pip/npm 默认入口与 P0 evaluator 保持不变。

## 行为映射

| Python 契约 | Rust 归属 | 差分入口（`tests/cli/`） |
| --- | --- | --- |
| Cursor global SQLite、requestId 主锚点/非主锚点、无 requestId 时 composer 回退 | `cursor.rs` | `test_cursor.py`：列表/head、字面标识符、含分隔符 composer、缺失/损坏 composer |
| Cursor 批量计数、前 20 个 bubble 的 metadata、坏 JSON 回退 | `cursor.rs` | 同上：103 个新增 composer 跨批次、晚到 requestId、损坏记录、UTF-8 BLOB 和非 UTF-8 BLOB |
| Cursor rowid 读取、消息时间稳定排序、秒/毫秒/ISO、用户回合 model 继承 | `cursor_transcript.rs` | 同上：UTC/Asia-Shanghai、带/不带 offset、备用时间、model 继承、不同正文与 token 形状 |
| Cursor 工具显式父消息挂接、独立 tool 消息、plan 审批 | `cursor_transcript.rs` | 同上：params/rawArgs、错误与状态、审批结果、结构化拒绝原因 |
| Cursor 子会话输出、重复引用、缺失、自引用和互相引用 | `cursor_transcript.rs` | 同上：model/type 回填、完成消息、循环保护；结果差分，不用 mock 限制实现结构 |
| DeepChat 草稿过滤、metadata、结构化 user/assistant 优先及 content 回退 | `deepchat.rs` | `test_deepchat.py`：缺行/缺表回退、旧会话、缺 metadata、消息按 order_seq 而非时间排序 |
| DeepChat 工具状态、流式参数、MCP 结果、plan/image、附件与链接、compaction | `deepchat.rs` | 同上：七种状态 × 两种存储来源，plan 对象 output，引用和内部事件保留 |
| Cherry topic/session 身份、当前父链、根/空叶节点/旁支过滤、workspace | `cherry.rs` | `test_cherry.py`：当前分支切换、空分支、循环/缺父节点/跨 topic/软删除损坏时保留其他会话 |
| Cherry soft-delete 字段迁移前后兼容、模型快照与旧 model_id、parts | `cherry.rs` | 同上：两种 schema、模型回退、八种工具状态、代码/翻译/错误、文件与内部事件 |
| MiniMax columnar v3、迁移状态、可见范围、title/目录/model facts | `minimax.rs` | `test_minimax.py`：待迁移旧 blob、旧版本、损坏 metadata/时间、archived/task/unknown、title fallback |
| MiniMax ID 顺序、reasoning、工具状态、usage/附件与独立内部事件 | `minimax.rs` | 同上：六种工具状态、部分参数、严格损坏正文失败、cache token、压缩和 permission response |
| 显式路径优先、缺失不回退、平台默认路径、特殊字符、迁移路径 | 各 Provider 及 `desktop.rs` | `test_desktop_paths.py`：默认/相对/缺失，MiniMax trim/优先级/home 展开，Cherry boot-config relocation |
| 格式能力、损坏 schema/head/正文、文件权限与成功输出 | `provider.rs`、`uri_workflow.rs`、`export.rs` | `test_desktop.py` 及各 Provider 套件：完整 JSON、Markdown 字节、stdout/stderr、中英文、错误时无导出文件 |
| WAL 新提交可见、持久数据不变、导出目录保护 | `sqlite.rs`、`export.rs` | `test_desktop_paths.py`：四 Provider 两次提交与新 CLI 读取；目录保护为 Rust 专属约束测试，见下文差异 |

Cursor 仅支持 JSON/print；其余三个支持 JSON/Markdown/print。请求包含任一不支持格式时整体拒绝；不先写出其他格式。head 保持 metadata 路径。错误诊断措辞尚未完全对齐；失败用例比较恢复/退出行为、是否生成文件及源数据，不把不同诊断文案规范化为一致。

## 实现边界

- `sqlite.rs` 继续拥有 SQLite 原生只读连接和事务。Cursor 的 KV JSON 读取单独接受 UTF-8 TEXT/BLOB；其他 Provider 沿用现有行转换，不读取附件实体或消息中的 URL。
- `desktop.rs` 只装配 DeepChat、Cherry、MiniMax 的连接、发现/读取入口、共同格式限制及 JSON 导出形状。schema 与语义保留在各 Provider 模块；没有新增第三方依赖。
- Cursor 的计数和正常 metadata 查询按 100 个 composer 分批，后者对每个 composer 只投影前 20 个 bubble。坏 JSON 使计数失败时，沿 Python 契约回退到逐 composer 扫描。正文展开在同一个只读事务中完成，循环集合与 memo 仅在本次读取中存活。
- `SessionData`、Message、Stats 的扩展字段保留现有 JSON 中的 model、parent、status、附件和 context usage；共享 renderer 只消费标准化消息。Provider 私有事件保留为带 data 的 part，不投影成对话文本。
- JSON 投影由 Provider 返回可序列化 payload；文件写入仍由同一个原子私有写入实现完成。Cursor 保留 context usage 统计；MiniMax 的 JSON stats 只输出现有 Python 的 message_count。

## 已确认差异与只读边界

本批测试发现：Python 当前允许 Cursor、DeepChat、Cherry、MiniMax 把 JSON 写进源数据库所在目录下的 Provider 子目录；Rust 的共享导出保护会拒绝。按照根 `AGENTS.md` 的稳定约束“不得混入 Provider 数据源”，保留 Rust 的拒绝行为；Python 参考源码不在本批修改。`test_provider_source_directory_cannot_be_export_destination` 只验证 Rust 的源目录保护，不计作跨语言等价证据。这项差异需要保留到默认实现切换审查，不能靠忽略输出或修改比较器隐藏。

SQLite 数据库与 `-wal` 的持久字节在读取中保持不变。原生只读 SQLite 仍可维护 `-shm` 协调文件或空 sidecar，本批 WAL 用例沿用[上一批的边界](rust-sqlite-parity.md)：比较数据库/WAL 内容与文件集合，不声称 Provider 目录内所有字节都不变。完全禁止协调文件写入的读取方式仍未实现。

## 本机验证

2026-09-24，macOS arm64，Rust 1.90.0：完整 `just isok` 通过，Python 2596 passed / 1 skipped，Rust CLI 差分与边界 554 passed，npm 74 passed，网页 E2E 13 passed；固定工具链 release 构建成功。Rust 比上一批增加 161 个用例，其中源目录拒写的 4 个用例只验证 Rust 约束。

实现提交：`a884907`。[六场景复测](benchmarks/rust-p2-desktop.md)全部通过原比较器；Codex 大正文 JSON＋Markdown 导出为 Python 267.47 ms / Rust 79.13 ms（3.38×）。报告保留相对上批约 6.1% 的 Rust 导出耗时增加、样本范围及新增 Provider 尚未测量的边界。

## 仍需验收

后续共享发现、URI 诊断及本批三个桌面来源的 schema/迁移/源消失错误已分别补齐，最新范围见[共享发现](rust-discovery-parity.md)、[URI](rust-uri-parity.md)和[Provider 专属错误](rust-provider-errors-parity.md)。下列清单保留本批接入时的边界，未由后续记录明确关闭的项目仍待验收。

- 完整 discovery 的可用性/完整性、部分失败计数与诊断 i18n；当前只隔离 Cherry/MiniMax 单会话发现错误并告警。
- 长生命周期缓存、lease/LRU、并发读取合并、同一 Session 重复读取和索引的 WAL 失效；当前用例验证每次新 CLI 能看到提交。
- 跨 Provider 列表、复杂 Query/Search、批量导出、全部 URI 参数组合、默认配置和非 TTY/TUI 入口。
- 超长子会话链、数据库在发现与读取之间迁移/消失、checkpoint/锁竞争、各 Provider 的全部历史 schema 与异常字段类型。
- 非标准 JSON 数值、超出 i64 的时间/token、Cherry 非整数/nullable 源时间等极端输入仍不保证与 Python 任意精度/动态类型行为相同。Cursor 支持文本 BLOB 不代表其他 Provider 的 BLOB 列已完成验收。
- Windows/Linux 的实际运行和所有发布制品；本机结果仅代表 macOS arm64。
- 四个新增 Provider 的代表性性能工作负载。本批重跑原有六场景仅检查共享模块与已覆盖 Codex/OpenCode 路径，不代表新增 Provider 的性能。

所有测试仅使用临时合成数据，Python 原有测试 fixture 按路径注入复用；没有访问真实用户会话目录。Ratatui 和 pip/npm 切换仍分别留在 P5、P6。
