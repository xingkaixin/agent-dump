# P3～P5 实施与验收跟踪

P3～P5 实现与本地验收完成，`b15f079` 的三平台 CI 为 22/22 通过；后续终端竞态修复的最终门禁见 [PR 当前检查](https://github.com/xingkaixin/agent-dump/pull/396/checks)。完整证据统一见 [P3～P5 最终验收](rust-p3-p5-completion.md)，性能见 [23 场景复测](benchmarks/rust-p3-p5.md)。

| 阶段 | 交付范围 | 证据 |
| --- | --- | --- |
| P3 | Query/Search、SQLite 索引与回退、增量/删除/WAL/竞态、stats/providers/reindex | 233 项查询差分、4 项索引边界单元测试、4 个扩展工作负载 |
| P4 | 配置/shortcut、模式分发、Collect/URI summary、两类 HTTP 协议、缺口与日志 | 配置、分发、Collect/reduction/transport 差分；0 ms/20 ms 本机 HTTP 评估 |
| P5 | Ratatui 选择与配置输入、非 TTY、批量导出、取消和终端恢复 | 56 项交互差分、7 项 POSIX PTY、三平台 TestBackend |

本地 `just isok` 完整通过，CLI 套件共 1,539 项，Rust 单元测试 44 项。Windows 换行与路径修复随后通过 179 项相关 CLI 回归，最终三平台完整契约通过：macOS 1,539、Linux 1,533、Windows 1,523 项；条件跳过项见最终报告。

CI 重跑发现的首帧 resize 竞态已通过提前注册事件处理器修复；并发测试改用显式同步。7 项 PTY＋6 项并发/归并连续 5 轮，共 65 项通过。

原 17 场景及新增 6 场景全部通过结果校验；22 个场景更快，批量 JSON 导出存在明确回退，保留样本并列入 P6。Python 参考实现、P0 原评估器及 pip/npm 默认入口未改动。

P6 的完整安装制品矩阵、最终兼容性审查、性能回退处理和默认发布切换仍待开展。
