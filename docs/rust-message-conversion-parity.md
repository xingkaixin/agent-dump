# P2：单条消息转换失败的恢复验收

> 历史分批记录：下文状态与计数描述该批提交。开放项的收尾证据与后续阶段归属统一见 [P2 最终验收](rust-p2-completion.md)。

本批接入 Codex、Claude Code、Pi 的记录级转换失败警告，并对齐三类可由 JSONL 数据触发的异常。健康记录继续读取，保留此前的消息装配状态。Python 生产源码、P0 evaluator 和 pip/npm 默认入口保持不变；P2 尚未完成。

## 行为与证据

| Python 契约 | Rust 归属 | 验证 |
| --- | --- | --- |
| Codex response payload 的 `type` 为数组/对象时转换失败；message content 的 part `type` 同样不能为数组/对象 | `codex_transcript.rs` | 两种错误类型 × 两个位置 × 中英文，检查完整警告和多格式导出 |
| Codex 一条 message 的 content 转换失败时不追加已收集的部分正文，也不累计该记录 usage | `content_parts`、正文读取循环 | 失败记录包含前后 text 与 usage；健康记录的 usage 保留，失败正文不导出 |
| 同一 Codex 错误若出现在 metadata 窗口内，作为会话解析失败处理 | `codex.rs` | 小文件完整扫描，response/unknown 顶层类型 × 数组/对象 × 两种语言；列表隔离失败，head/raw 无法定位并返回 1 |
| Claude assistant/user/tool_result 的显式非对象 `message` 触发逐记录警告 | `claude_transcript.rs` | null、list、bool、int、float、string；每个 fixture 含三个角色，警告三次，后续工具结果仍通过 assistant UUID 回填 |
| Claude meta/未知类型不转换；缺失 message/content 使用空字符串默认值，不重置 assistant 分组 | `Decoder::record`、`user` | 混合跳过记录与前后 assistant text，完整产物差分 |
| Pi 转换到 UTC 后超出 Python 年份 1–9999 时告警并继续 | `pi_transcript.rs` | 上下两个年份边界 × record/message timestamp × 两种语言，失败记录不累计 usage，后续无 ID 消息仍使用原始有效 JSON 对象序号 |
| 转换警告立即输出，JSONL 坏行在扫描结束后汇总；多格式复用一次读取 | JSONL 回调与 Provider 正文读取 | Codex 转换错误与坏 JSON 同一 fixture，检查完整 stderr 顺序、次数及产物 |
| head/list/JSONL raw 不执行正文转换，原本静默忽略的字段不新增警告 | 工作流与各 decoder | 三个 Provider × 中英文，完整 stdout/stderr、退出码及 raw 字节差分 |

新增 `tests/cli/test_message_conversion.py` 的 48 个 CLI 用例，全部使用完整输出差分、JSON 结构和 Markdown/raw 字节比较，并检查源 hash 与产物权限。使用临时合成目录，不读取真实会话；没有新增 mock。

Codex 的正文恢复 fixture 超过 metadata 全扫阈值，将坏 payload 放在首部窗口外，并用健康尾记录结束。Pi 的 record timestamp 溢出 fixture 同理，message 内部 timestamp 不影响 metadata。另有小文件用例验证 Codex 的 metadata 失败，不把正文恢复规则套到发现阶段。

## 实现边界

JSONL scanner 将已有诊断 sink 传给逐记录回调，Provider 决定哪些转换错误可恢复，工作流继续负责语言与输出通道。打开/扫描 I/O 失败及诊断输出失败仍向上返回；不把它们改成坏消息跳过。没有全局状态、额外诊断缓冲或重复扫描。

恢复保持当前 decoder 状态，不重建整个会话。Codex 仅在 content 全部转换成功后追加该消息；Claude 缺失字段与显式 null 分开处理。`value.rs` 的 JSON 类型名用于已验证的 Python 原因文本，也复用于已有 Claude 标题类型错误。Pi 在正文转换中检查 UTC 年份溢出，使用现有 Jiff，不增加日期依赖。

## 仍待完成

- 其他极端字段、超出 Rust 整数范围的累计 token/cost，以及全部 JSON、UTF-8、文件系统底层原因文字；本批不是任意畸形 JSON 的全量一致性证明。
- Pi metadata 阶段的日期极值及其他来源的极端标题/时间字段，仍需单独验收。
- 固定配置下六个 Provider 的[来源选择与重试](rust-source-selection-parity.md)在后续补齐；运行时配置路径变化和其他 Provider 的选择规则见[后续验收](rust-runtime-sources-parity.md)。正文缓存、lease/LRU、并发读取合并与失效仍待验收。
- 完整 CLI usage、全部参数组合和跨平台发布。搜索、配置、Collect、Ratatui 及 pip/npm Rust 发布保持在后续阶段。

## 本轮验证

转换恢复专项 48 passed。2026-09-24，macOS arm64，固定 Rust 1.90.0：完整 `just isok` 通过，Python 2596 passed / 1 skipped、Rust 单元测试 17 passed、CLI 差分与边界 832 passed、npm 74 passed、Web E2E 13 passed。`just build-rust` release 构建通过。

Python 生产源码与 `dca2d97` 相同，P0 evaluator 四个脚本相对 `9c1cf61` 无改动，没有新增依赖。

实现提交：`fa39040`。[原七场景复测](benchmarks/rust-p2-message-conversion.md)在干净 checkout 上通过结果比较与源 hash 校验；健康 Codex/OpenCode V2 场景不测 Claude、Pi 或坏记录恢复性能。
