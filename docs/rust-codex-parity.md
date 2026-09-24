# P2：Codex 消息与导出验收

本批迁移 Codex 正文消息装配与单 URI 的 Markdown/raw/混合导出。Python 参考实现保持不变；本记录不代表所有 Provider 或整个 Codex 契约已经完成。

## 差分方式

`just check-rust` 构建 Rust 后运行 `rust/tests/`。每个行为用例在隔离的临时目录创建合成 Provider 源，分别调用 Python 和 Rust 的真实命令行入口。成功路径比较退出码、完整 stdout/stderr、JSON 对象和 Markdown/raw 字节，并验证所有源文件 hash 不变。文件权限和符号链接边界使用独立断言。

异常诊断尚未统一。损坏行用例比较恢复后的内容和警告存在性；文件导出失败用例比较退出码、成功文件内容、清理结果和源数据不变性，不把诊断文案或输出通道算作已对齐。

2026-09-24，macOS arm64 本机 `just isok` 通过：Python 2596 passed / 1 skipped，Rust/Python 差分及边界用例 172 passed，npm 74 passed，网页 E2E 13 passed；Ruff、类型检查、Rust fmt 和 Clippy 通过。`just build-rust` 使用固定的 Rust 1.90.0 构建 release 成功。

## 行为映射

| 现有 Python 契约 | Rust 实现 | 差分入口（`rust/tests/`） |
| --- | --- | --- |
| `test_codex.py` 的 message/reasoning 分组、工具调用回填、事件去重 | `codex_transcript.rs` | `test_codex_transcript.py`：正常/孤立/交错/重复输出、user 边界、独立时间戳、未知与非文本事件 |
| 工具参数与 function/custom 输出归一化 | `codex_transcript.rs`、`value.rs` | 同上：JSON 字符串、非 JSON 字符串、null、标量、嵌套对象、key 顺序、浮点指数格式 |
| 计划批准、拒绝、替换、未完成；上下文不消费审批 | `codex_transcript.rs` | 同上：`test_plan_*`、multipart plan |
| 完整上下文块分类；保留普通提及、代码块、缩进示例和混合输入 | `codex_enrichment.rs` | 同上：`test_injected_context_and_ordinary_mentions`、混合非文本用例 |
| subagent prompt、昵称映射及通知；坏通知保留原文 | `codex_enrichment.rs`、`render.rs` | 同上：单/多 subagent、昵称更新、不同参数形态与坏通知 |
| JSON 专用 skill 转换、稳定 call ID、wait_agent 过滤；其他投影不变 | `codex_enrichment.rs` | 同上：JSON 首先/最后、格式别名与去重后的混合导出 |
| `test_codex_patch.py` 与 Codex custom apply_patch | `codex_patch.rs` | `test_codex_patch.py`：add/delete/update/move、多 hunk、CRLF、坏 patch 与中英文错误；只解析，不执行 patch |
| `test_codex.py`、`test_uri_workflow.py`、`test_exporting.py` 的单会话文件输出与部分成功 | `uri_workflow.rs`、`export.rs` | `test_export_formats.py`：raw 精确保留坏行/非 UTF-8 字节/未完成尾行；部分/全部失败；无遗留临时文件；源目录拒写 |
| P1 的发现、URI、head、print/JSON、文件身份与权限 | `codex.rs`、`jsonl.rs`、`session.rs`、`export.rs` | `test_cli_parity.py`：继续保留 P1 正向契约；原先拒绝复杂消息的临时测试替换为本批正向差分 |

JSON 文件的空白排版不作为契约；工具输出和 subagent prompt 内嵌的 JSON **字符串**逐字符比较，因此保留对象 key 顺序及 Python 数值文本格式。

## 仍需验收

- 完整参数组合、配置默认目录/语言、错误文案及 stdout/stderr 通道。当前必须显式指定文件导出的 `--output`，列表要求 `-q provider:codex`。
- 重复发现时的标题索引刷新、缓存 lease/LRU、并发读取和变化源失效。这些要随交互、Query/Search 工作流进入 Rust，当前子进程差分不能证明长生命周期缓存契约。
- 源文件并发变化或读取中消失；完整损坏记录诊断，以及所有 Provider 共用的部分失败行为。
- 非标准 JSON 数值、超大整数/超出 i64 的 token 总和、极端 Unicode 标量转字符串等边界。当前 token 溢出返回错误，不能声称与 Python 任意精度整数等价。
- Linux/macOS CI 与 Windows/正式分发平台的实际运行；本批只记录 macOS arm64 本机结果。

后续合并完整迁移矩阵时逐项关闭这些边界，不以本批用例数量代替完成率。
