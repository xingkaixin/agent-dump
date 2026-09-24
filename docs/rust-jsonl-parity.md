# P2：Claude Code、Kimi、Pi 差分验收

本批在 `feat/rust-rewrite` 上接入三个 JSONL Provider，实现提交 `3669542`，复用 Codex 批次的单 URI 工作流和导出模块。Python 参考实现、pip/npm 发布入口与 P0 benchmark evaluator 均保持不变。这里记录已验证的行为，不代表三个 Provider 的完整契约或 P2 已全部完成。

## 验收方式

`rust/tests/` 在临时目录生成合成会话，分别调用 Python 和 Rust CLI。成功路径比较退出码、完整 stdout/stderr、JSON 结构和 Markdown/raw 文件字节；检查源文件 hash 不变及导出权限。损坏行和单文件读取失败单独检查恢复后的内容、警告与源数据，不宣称诊断文案已对齐。

2026-09-24，macOS arm64 本机完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust/Python 差分及边界用例 313 passed（本批新增 141 个），npm 74 passed，网页 E2E 13 passed；Ruff、类型检查、Rust fmt 与 Clippy 通过。固定 Rust 1.90.0 的 `just build-rust` release 构建通过。未运行远端 CI 或 Windows 验证。

## 行为映射

| Python 契约 | Rust 实现 | 差分入口（`rust/tests/`） |
| --- | --- | --- |
| Claude 项目文件、sessions-index 标题、mtime 回退、最后记录时间、bounded head | `claude.rs`、`file_sessions.rs`、`jsonl.rs` | `test_claude.py`：标题优先级、缺失字段、扫描层级、fallback、大文件 head、日期窗口 |
| Claude assistant 分组、thinking/text、工具结果回填、TodoWrite/meta 过滤、UUID 关联、usage | `claude_transcript.rs`、`message_assembly.rs` | 同上：交错/重复/孤立输出、工具状态、首条 usage、消息边界、两种语言与四种输出 |
| Kimi metadata、work_dirs MD5、context 优先、wire_mtime 不受旧文件 mtime 裁剪 | `kimi.rs` | `test_kimi.py`：存储优先级、工作目录/标题/ID 回退、大小决定已知/未知计数、fallback、日期窗口 |
| Kimi context、wire 流、分段参数、tool result、SetTodoList、usage/token_count | `kimi_transcript.rs`、`kimi_wire.rs` | 同上：工具别名、JSON/null/标量参数、混合输出、assistant 归属、内部事件、未完成参数、时间/token 转换 |
| Pi header、文件后缀定位与 ID 回退、最新 session_info、最大更新时间、轻量扫描计数 | `pi.rs` | `test_pi.py`：列表/head、标题优先级、数值/ISO 时间、全文与 head 标题差异、无效 header、fallback |
| Pi 分支消息、compaction/custom、bashExecution/toolResult、图片、usage/cost | `pi_transcript.rs` | 同上：保留全部分支、独立工具结果、entry/parent 字段、content 形态、空消息统计、原始版本值、中英文输出 |
| 字面环境变量路径、文件失败隔离、源数据只读、损坏行恢复 | `file_sessions.rs`、`jsonl.rs`、`export.rs` | `test_pi.py` 的相对/空/空格/字面 `~` 路径，`test_kimi.py` 的坏 metadata，`test_jsonl_sources.py` 的损坏 JSON/UTF-8/非对象/未完成尾行和 raw 原字节保留，各 Provider 的源目录拒写 |

已有 Codex 差分测试继续覆盖共享装配、Session 字段、列表、head 和导出，防止公共模块抽取改变既有行为。

## 实现边界

工作流仅依赖 `Provider`、`Session` 与 `SessionData`；Provider 私有 schema 留在对应模块。静态注册表只负责名字、展示名、URI scheme 和构造函数。新增 MD5 依赖只用于对齐 Kimi 的存储目录命名，不引入插件系统、FFI 或 Python 运行时调用。

目前仅支持显式单 Provider 列表和单 URI 工作流。文件导出必须指定 `--output`，分别写入 `codex/`、`claudecode/`、`kimi/`、`pi/` 子目录。Kimi raw 选择 context，缺失时才使用 wire。Pi 保留全部树节点，未改为仅导出当前分支。

## 仍需验收

- 完整 Query/URI 参数、配置默认值、全 Provider 部分失败计数、可用性与完整性 facts、诊断 i18n 及 stdout/stderr 通道；目录遍历本身失败仍可能终止当前 Provider。
- 长生命周期标题/正文缓存、lease/LRU、变化源失效与并发读取；当前 CLI 每次创建实例，不能证明这些缓存契约。
- 源在发现与读取之间变更或消失、权限变化、读取期间写入；更多旧 schema 与畸形 metadata 字段组合（例如非字符串 cwd）。
- Python 任意精度整数、非标准 JSON 数值、极端 Unicode 字符串表示及日期边界。Rust token 总和超出 i64 时明确失败，尚未等价于 Python。
- Windows 与全部发布平台的实际验证；本批本机结果仅代表 macOS arm64。

原有五场景 benchmark 仍只覆盖 Codex 合成文本，不据此推断 Claude Code、Kimi、Pi 性能；新 Provider 的代表性性能 fixture 后续独立扩展，不修改 P0 的历史工作负载。

本批[五场景复测](benchmarks/rust-p2-jsonl.md)全部通过，保留同期 Python/Rust 的原始样本、环境与二进制 hash。
