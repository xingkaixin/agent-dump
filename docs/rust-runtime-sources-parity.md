# P2：运行中来源配置变化验收

> 历史分批记录：下文状态与计数描述该批提交。开放项的收尾证据与后续阶段归属统一见 [P2 最终验收](rust-p2-completion.md)。

本批延续[固定配置下的来源选择验收](rust-source-selection-parity.md)，对齐同一 Provider 实例在候选配置变化后的发现、查找和诊断路径。Python 生产源码、P0 evaluator 和 pip/npm 默认入口保持不变；P2 尚未完成。

## 行为与证据

| Python 行为 | Rust 实现 | 验证 |
| --- | --- | --- |
| Codex、Claude、Kimi、Pi 在尚未选中来源时读取当前配置；选中后保持原路径 | `SourceRoots` 持有根路径解析函数，只有 base 为空时重新选择 | 扩展四个来源选择用例：构造后改配置、首次缺失后改配置、选中后改配置；发现和查找仍保留原来源与导出保护根 |
| OpenCode、ZCode 在数据库未选中时读取当前候选；选中后不改选 | `SqliteProvider::ensure_database` 调用当前候选解析函数 | 空候选后恢复；改配置后发现/查找继续使用已选数据库，移走原数据库后报错，不创建或读取新数据库 |
| Codex 会话根固定，但全局标题索引跟随当前 `CODEX_HOME` | 标题缓存首次加载时从当前配置取 `session_index.jsonl` | 同一源文件先得到 First 标题，改配置后得到 Second 标题；删除新索引后重新发现使用回退标题 |
| DeepChat、Cherry、MiniMax 每次发现/查找重新选择第一个存在的候选 | `Desktop::select_database` 在每次操作读取候选 | fallback 可用后新增 primary 会切换；移走 primary 后回退；全缺失后改配置可恢复，保护根跟随实际选择 |
| 三个桌面 Provider 读取旧 Session 仍使用 Session 记录的数据库 | `Desktop::read` 继续使用 `session.source_path` | 切换候选并移走旧数据库后，旧 Session 读取失败，不读取新库中的同 ID 会话 |
| Cursor 每次发现、查找和正文读取都计算当前数据库路径 | `Cursor` 的路径解析函数进入三个读取入口 | 切换两个临时 KV 数据库，检查发现、查找和候选路径；旧 Session 读取当前库正文，当前库缺失时报告当前路径 |
| 候选路径诊断反映当前配置，不必等于已选会话来源 | `Provider::search_roots` 返回当前解析结果 | 配置切换后同时检查候选路径、实际 Session 来源和导出保护根 |

Cursor 与其余 SQLite Provider 的旧 Session 规则不同。其 Python transcript decoder 使用当前 `CursorStore`；Rust 本批按此读取正文，但不修改旧 Session 的 `source_path` 等发现事实。当前配置指向不存在的库时不会读回旧库。该行为已经通过独立 Python 参考实例核对，不将所有 Provider 统一成同一来源策略。

## 实现与测试边界

路径解释仍归各 Provider 所有，原环境变量、默认路径及 Cherry boot-config 规则复用原函数。Provider 保存解析函数，操作入口决定何时调用；不增加后台刷新、全局可变配置、第三方依赖或新的 CLI 参数。

候选解析可能失败，因此 `search_roots` 返回 `Result`。发现/查找传播配置错误；为已有失败补充候选路径的展示入口在解析失败时省略候选列表，保留原失败诊断。文件来源选中时同时保存导出保护根，避免后来改配置使保护目录脱离实际来源。

新增 5 个 Rust 单元用例，并扩展原有四个文件 Provider 用例。运行时配置断言覆盖 45 组序列：四个文件 Provider 各 8 组，OpenCode/ZCode 共 4 组，三个桌面 Provider 共 6 组，Codex 标题、Cursor 发现/查找、Cursor 旧 Session 读取各 1 组。Rust 单元测试共 27 个；CLI 套件保持 834 个。

Rust 用例在路径解析边界注入可切换的临时路径，不在并行测试中修改全局环境变量。既有 CLI 差分继续保护真实环境变量到路径的映射。本轮另在隔离的 Python 进程内切换真实环境变量，核对 20 组序列，覆盖十个 Provider 和 Cursor 旧 Session 读取；HOME、工作目录和所有来源都位于临时目录。这是本轮参考核验，不计入自动 CLI 差分总数。

## 仍待完成

- 正文缓存、lease/LRU、并发读取合并与失效；尤其需要单独核对 Cursor 当前配置与旧 Session facts 的缓存关系。
- 单次操作期间环境变量、工作目录或符号链接发生变化的竞争；Cherry boot-config 文件编辑、损坏和恢复的完整生命周期组合。当前测试保护候选配置变化，不代表全部配置文件竞争时序。
- 全部底层错误原因/异常类别、极端标题/消息/数值输入、历史 schema 与跨平台发布。
- 完整 CLI usage、全部参数组合及后续搜索、配置、Collect、Ratatui、pip/npm Rust 发布。

## 本轮验证

相关 CLI 回归 133 passed；Python 参考核验 20 组通过。最终完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 单元测试 27 passed、CLI 差分与边界 834 passed，npm 74 passed、Web E2E 13 passed；格式、Clippy 和类型检查通过。

固定 Rust 1.90.0 的 `cargo build --locked --release` 通过。Python 生产源码与 `dca2d97`、四个 evaluator 文件与 P0 `9c1cf61` 一致。全部测试及参考核验使用临时合成来源。

实现提交：`a42bbc6`。[原七场景复测](benchmarks/rust-p2-runtime-sources.md)全部通过，两轮测量均为同一干净 checkout，源码、evaluator、fixture 与上一批 hash 一致。跨 Provider 列表为 4.85×、JSON＋Markdown 导出为 3.17×；仅描述本轮健康数据上的独立进程，不测同实例配置切换和其余八个 Provider 的性能。
