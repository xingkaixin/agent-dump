# P2：源缺失诊断与 Kimi raw 文件身份验收

本批补齐 Codex、Claude Code、Pi、Kimi、Cursor、OpenCode、ZCode 在定位后源消失时的读取诊断，并修正 Kimi raw 文件选择和 OpenCode V2 消失后的错误原因。Python 生产源码、P0 evaluator 和 pip/npm 默认入口保持不变；P2 仍在进行中。

## 行为与证据

| Python 行为 | Rust 实现 | 验证入口 |
| --- | --- | --- |
| Codex、Claude Code、Pi 已定位文件消失时，报告缺失路径、候选来源和本地化建议 | 各 Provider 的 `read`、`provider_error.rs` | 每个 Provider 使用临时文件先定位再删除；检查中英文诊断字段，确认不会创建源文件 |
| 三个单文件 Provider 的 raw 源消失时使用 raw 专属原因；源变为目录时报告能力限制 | `provider.rs` 的默认 `raw_export` | 同一已定位 Session 的缺失文件和目录替换检查 |
| Cursor 已定位数据库消失时，保留 Cursor 专属原因及恢复建议 | `cursor.rs` | 临时 KV 数据库先定位再删除，检查路径、候选来源及两种语言 |
| OpenCode、ZCode 完整读取使用 Session 记录的数据库；文件消失时不得切换到另一数据库 | `sqlite_provider.rs` | 两个 Provider 分别定位后删除数据库并设置另一个当前数据库，确认报告原路径且不读取或修改替代文件 |
| OpenCode V2 会话行消失与 V2 表消失分别报告 `OpenCode session is missing: ID`、`OpenCode V2 session source is missing: ID` | `sqlite_provider.rs` | V2 与旧表含相同 ID，分别删除 V2 行或表；不得读取旧表副本，数据库持久字节保持不变 |
| Kimi 正文优先读取当前 context，缺失时使用 wire；二者均缺失时报告 wire 路径及两个候选文件 | `kimi.rs` | 删除 context 后仍能读取 wire，继续删除 wire 后检查专属读取诊断 |
| Kimi raw 使用定位时记录的 context/wire 文件身份 | `kimi.rs` 的 `source_metadata`、`raw_export` | context 消失时旧 Session 的 raw 报错，重新定位后可选择 wire；定位后新增 context 不改变旧 Session 的 raw wire；没有快照文件证据时不猜测来源 |
| raw 失败保留原始 Provider 诊断，多格式导出继续独立处理 | `uri_workflow.rs`、`diagnostics.rs` | 现有导出部分成功、读取失败、raw 独立复制及 Kimi CLI 回归 |

新增 10 个 Rust 单元用例，连同原有用例共 15 个；CLI 差分与边界套件仍为 706 个。新增用例保护 Provider 的读取和 raw 来源边界，未用进程竞争时序伪造 CLI 差分。Cursor 用例使用同一 Provider 与同一数据库，不代表跨实例任意 Session 的来源行为已经验收。

独立使用临时合成数据核对 Python 参考实现：七个 Provider × 两种语言的读取源缺失，以及六个支持 raw 的 Provider × 两种语言的 raw 源缺失，共 26 项；另核对 Kimi 的两种文件切换和 OpenCode V2 的两种消失情形，共 4 项。Rust 使用的 21 组中英文建议与 Python 翻译目录逐字核对。上述为本轮参考核验，不计入自动测试总数，也不声称全部诊断全文已经自动差分。

## 实现边界

`ProviderError::Diagnostic` 保存 Provider 的下一步建议，展示层按语言渲染。`raw_export` 返回 `Result`，因此来源选择失败无需降级为普通字符串。文件缺失判断和私有快照解释仍由 Provider 层拥有；工作流只决定格式、输出通道和部分成功状态。

Kimi 的正文选择与 raw 选择遵循不同的已有契约：正文检查当前目录，raw 使用发现时记录的路径。读取成功不代表同一个旧 Session 的 raw 一定成功。OpenCode/ZCode 的 raw 是标准化 JSON，仍通过完整读取获得数据。

## 仍待完成

- Codex/Claude/Pi [记录转换恢复](rust-message-conversion-parity.md)已在后续验证，其他极端消息字段仍待验收；JSONL/旧 SQLite [坏记录警告](rust-record-diagnostics-parity.md)及 Codex/Claude [标题缓存恢复](rust-title-cache-parity.md)已在后续补齐，底层错误全文仍有差异。
- 文件存在性检查与打开之间的竞争、权限等底层错误全文及异常类别、无效导出 ID 和完整 CLI usage。
- 长生命周期来源选择和 Cursor 当前配置下的旧 Session 读取已在后续补齐，见[运行中来源配置验收](rust-runtime-sources-parity.md)；缓存、lease/LRU、并发读取合并与失效仍待验收。
- 极端输入、历史 schema 与跨平台发布。配置、搜索、Collect、Ratatui 和 pip/npm Rust 发布切换保持在后续阶段。

## 本轮验证

2026-09-24，macOS arm64，固定 Rust 1.90.0：相关 CLI 回归 198 passed；完整 `just isok` 通过，Python 2596 passed / 1 skipped、Rust 单元测试 15 passed、CLI 差分与边界 706 passed、npm 74 passed、Web E2E 13 passed。`just build-rust` release 构建通过。所有 fixture 使用临时目录或临时 SQLite，不访问真实用户会话。

Python 生产源码与 `dca2d97` 相同；P0 evaluator 四个脚本相对 `9c1cf61` 无改动。没有新增第三方依赖。

实现提交：`0d2fc2a`。[原七场景复测](benchmarks/rust-p2-source-errors.md)在干净 checkout 上通过结果比较和源 hash 检查；不作为 Kimi 或失败路径的性能证据。
