# P2：URI 共用失败诊断验收

本批对齐 URI 验证、无匹配、Provider 格式能力拒绝，以及读取/写出失败的诊断结构和输出通道。Python 源码、P0 evaluator 和 pip/npm 默认入口保持不变；P2 仍在进行中。

## 行为映射

| Python 契约 | Rust 归属 | 验证方式（`rust/tests/`） |
| --- | --- | --- |
| URI 格式、scheme 大小写、非空 ID、Codex `threads/` 与末尾换行 | `registry.rs` | `test_uri_diagnostics.py`：中英文完整退出码/stdout/stderr 差分；多行和终端控制字符输入 |
| 未找到会话是正常定位结果，不伪装成异常 | `provider.rs` 的 `Lookup`；各 Provider `find` | 十个 scheme 在来源存在/不存在时的诊断，包含原始 URI、解析结果、候选路径和下一步 |
| URI 示例由 Provider 注册信息生成 | `registry.rs`、`ProviderInfo.identifier_label` | 比较完整无效 URI 诊断，包含 Codex 前缀、Cursor requestid 和 Cherry topic 示例 |
| 查找异常先输出警告，最终报告无匹配 | `uri_workflow.rs`、`diagnostics.rs` | 损坏 OpenCode 数据库的中英文完整差分；warning 在 stderr，最终诊断在 stdout |
| 单文件查找失败后继续，保留已经发现的失败 | `file_sessions.rs`、`Lookup.failures` | 坏文件名候选后回退读取健康文件；比较结果、警告次数和本地化前缀；底层原因文本单独保留差异 |
| 文件名快速查找未命中时，全量 metadata 回退选择最新同 ID 会话 | `file_sessions.rs` | 两个文件使用同一 ID、不同创建时间，head 完整差分并确认取自新会话 |
| 验证整个格式请求后才开始读取/导出 | `diagnostics.rs`、`uri_workflow.rs` | Cursor、DeepChat、Cherry、MiniMax；别名、去重、多个不支持格式、支持能力排序；完整诊断差分且无产物 |
| head 与显式 format 冲突优先于查找和 format 解析 | `main.rs` | 合法/非法/空 format 均返回 1，完整中英文输出一致 |
| head 忽略 output，不产生目录或文件 | `main.rs`、`uri_workflow.rs` | 中英文成功输出和目录不存在性 |
| 无效格式列表是参数错误 | `main.rs`、`output_formats.rs` | 返回 2、stderr 非空、stdout 为空；不声称 Clap 与 argparse 的完整 usage 一致 |
| print 和每个文件格式分别报告读取/导出失败 | `uri_workflow.rs` | 损坏 V2 正文时四次诊断、返回 1、无文件、源 hash 不变；比较共同诊断字段和次数，保留底层原因差异 |
| 单格式失败继续其他格式，任一成功返回 0 | `uri_workflow.rs`、`export.rs` | 既有 `test_export_formats.py` 更新为 stdout 诊断断言，继续比较成功文件、原子写入清理和源 hash |

新文件包含 84 个 CLI 用例；原有 597 个继续保留，合计 681 个。差分 helper 增加期望退出码参数，以同一套完整 stdout/stderr 与源 hash 检查验证失败路径，没有把错误文案归一化后宣称一致。所有数据来自隔离的临时 fixture，不读取真实 Provider 会话。

## 实现边界

`diagnostics.rs` 保存共用诊断结构、文案和安全渲染；URI 与列表工作流共享字段标签和空来源诊断。它不扫描 Provider，也不读取配置。注册表负责 URI 示例与路径候选装配，Provider 继续拥有私有 schema。

`Lookup` 同时表达可选的会话与逐文件失败；整个操作出错仍使用 `Result::Err`。因此工作流可以区分未匹配、部分失败和整体失败，不需要根据错误字符串猜测。文件查找不再自行打印警告；返回的失败由调用方写入 stderr。无匹配诊断仍列出全部注册来源的候选路径，与 Python 一致，但不会扫描无关 Provider 的会话内容。

URI 诊断的每个动态字段分别清理终端控制字符并限制展示长度。读取/导出仍共用一次准备的数据，raw 文件复制与其他格式隔离；没有新增第三方依赖或 Python 运行时调用。

## 本轮验证

`just isok` 全部通过：Python 2596 passed / 1 skipped，Rust 单元测试 1 passed、CLI 差分与边界 681 passed，npm 74 passed，Web E2E 13 passed。固定工具链 `just build-rust` release 构建通过。Python 生产源码相对 `dca2d97`、P0 evaluator 相对 `9c1cf61` 均无改动。

实现提交：`f3af42a`。[原七场景复测](benchmarks/rust-p2-uri.md)全部通过结果比较，保留同期 Python/Rust 原始样本；这些成功场景不测失败诊断耗时。

## 仍待验收

- Provider 专属诊断的后续验证见 DeepChat / Cherry / MiniMax [专属错误验收](rust-provider-errors-parity.md)及其余七个 Provider [源缺失验收](rust-source-parity.md)；尚不涵盖所有底层错误。
- JSON、SQLite、文件系统的底层原因文本和异常类型并不全部相同。新的失败测试明确区分逐字差分和结构/行为检查，不将后者算作完整文本一致。
- JSONL 坏行、标题缓存、正文转换等旧警告路径仍需统一；不能因为文件查找已返回失败事实，就认定所有 Provider 输出均已可关闭。
- 非法导出 ID 的能力诊断、文件系统故障详情、完整 CLI usage、查询/列表参数组合仍待验收。文件导出仍要求显式 `--output`，配置默认值留在 P4。
- 复用 Provider 实例的刷新/缓存、并发失效、读取中源消失和跨平台发布验收仍未关闭。

既有 Rust 源目录导出保护继续有效；此前记录的 Python/Rust 差异见[桌面 Provider 验收](rust-desktop-parity.md)。
