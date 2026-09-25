# P2：桌面 Provider 专属错误验收

> 历史分批记录：下文状态与计数描述该批提交。开放项的收尾证据与后续阶段归属统一见 [P2 最终验收](rust-p2-completion.md)。

本批补齐 DeepChat、Cherry Studio、MiniMax Code 的 schema、不可读来源与存储迁移诊断。Python 生产源码、默认 pip/npm 入口和 P0 evaluator 保持不变；不将三个 Provider 的错误路径完成计作 P2 全部完成。

## 行为与证据

| Python 行为 | Rust 实现 | 验证入口 |
| --- | --- | --- |
| DeepChat 缺少当前会话表时拒绝；非 SQLite 数据提示加密或不可读 | `deepchat.rs`、`desktop.rs` | `test_desktop.py`、`test_provider_diagnostics.py`：中英文 URI、单来源列表、混合列表完整退出码/stdout/stderr 差分 |
| Cherry 缺少当前 2.x 必需表时拒绝 | `cherry.rs` | 同上；保留其他 Provider，源 hash 不变，无导出文件 |
| MiniMax 逐表验证必需字段，拒绝不支持的 schema | `minimax.rs` | 四个必需表分别覆盖缺字段或缺表，比较完整本地化警告及输出 |
| 路径存在但不是文件，报告 Provider 源缺失 | `desktop.rs` | 三个 Provider × 两种语言的 CLI 差分；不会把目录当作空数据库或创建来源 |
| 列表操作警告包含 Python 异常类别，URI 查找警告仅包含原因 | `provider_error.rs`、工作流 | 上述差分覆盖能力错误、源缺失，以及非 SQLite 数据的 `DatabaseError`；不声称覆盖所有底层异常类别 |
| MiniMax 旧 columnar 版本、待迁移旧 blob、非对象 metadata 或无效时间不进入列表 | `minimax.rs` | `test_minimax.py`：两种语言，URI 失败；列表跳过坏会话、保留同来源健康会话并告警，源 hash 不变 |
| 定位后文件或会话行消失，完整读取报告源缺失 | `desktop.rs`、各正文读取器 | `desktop/tests.rs`：真实临时数据库先定位，再删除文件/行，调用同一 Provider 读取；缺失文件的中英文完整诊断、缺失行证据和不写源检查 |
| 定位后源变为非 SQLite、schema 缺失，保留能力诊断；MiniMax 变为待迁移时使用通用读取失败加本地化原因 | `desktop.rs`、`diagnostics.rs` | Rust 读取边界测试；分别核对路径、表名、能力字段、诊断类别与源字节 |
| 多格式导出共用读取结果时保留原始错误类型 | `uri_workflow.rs` | 现有 URI 逐格式失败、部分成功和 raw 独立路径回归测试；不将读取边界测试宣称为 CLI 竞争时序差分 |

CLI 套件净增 25 个用例，合计 706 个；新增 4 个读取边界单元用例，连同原有用例共 5 个。CLI 差分比较原始 stdout/stderr，没有改写错误文案后再比较。全部数据来自临时合成 fixture；DeepChat 不可读 fixture 只是非 SQLite 字节，未验证真实 SQLCipher 数据库或解密能力。

## 实现边界

`provider_error.rs` 保存可本地化的错误原因和结构化证据，Provider 拥有 schema 判断及对应文案，展示层选择语言和输出通道。逐文件/会话失败保留错误对象，避免在发现阶段转成字符串后丢失类别和中文原因。

`diagnostics.rs` 优先保留 Provider 的结构化证据；普通失败仍使用共用读取诊断。URI 的多个文件格式直接复用原始读取错误，不再转为字符串重新包装。JSONL raw 仍独立复制源文件。

`desktop.rs` 统一检查当前文件及只读连接；DeepChat 根据 SQLite 的 `NotADatabase` 错误码报告不可读来源，不根据任意错误字符串猜测。Cherry、MiniMax 的 schema 仍在所属模块验证。没有新增依赖、修改源数据或运行上游迁移。

## 仍待完成

- Codex/Claude/Pi [记录转换恢复](rust-message-conversion-parity.md)已在后续验证，其他极端消息字段仍待验收。其余七个 Provider 的[源缺失路径](rust-source-parity.md)、JSONL/旧 SQLite [坏记录警告](rust-record-diagnostics-parity.md)及 Codex/Claude [标题缓存恢复](rust-title-cache-parity.md)已在后续补齐；底层原因文本仍待完整对齐。
- 全部 JSON/SQLite/文件系统底层原因文本和异常类别、无效导出 ID、完整 CLI usage；本批只映射已验证的错误类型。
- 长生命周期发现刷新、正文缓存/lease/LRU、并发读取合并与失效；读取同一已定位 Session 的故障测试不等于完整缓存验收。
- 更多 schema 历史版本、真实锁竞争与平台发布。现有源目录导出保护差异和 SQLite SHM 边界继续见[桌面 Provider 验收](rust-desktop-parity.md)。

配置、搜索、Collect、Ratatui 和 pip/npm 的 Rust 发布切换仍留在后续阶段。

## 本轮验证

2026-09-24，macOS arm64，固定 Rust 1.90.0：完整 `just isok` 通过，Python 2596 passed / 1 skipped、Rust 单元测试 5 passed、CLI 差分与边界 706 passed、npm 74 passed、Web E2E 13 passed。`just build-rust` release 构建通过。

Python 生产源码与 `dca2d97` 相同；P0 evaluator 四个脚本相对 `9c1cf61` 无改动。没有新增第三方依赖。

实现提交：`99575b9`。[原七场景复测](benchmarks/rust-p2-provider-errors.md)通过比较器和源 hash 校验；原始报告记录干净 checkout。这些成功场景不作为桌面 Provider 或失败诊断的性能证据。
