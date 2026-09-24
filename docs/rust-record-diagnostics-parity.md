# P2：损坏记录可恢复警告验收

本批对齐完整正文读取中的 JSONL 坏行和旧 SQLite 消息/part 坏记录警告，覆盖文案、语言、输出通道、次数和继续读取行为。Python 生产源码、P0 evaluator 及 pip/npm 默认入口保持不变；本批之后的标题缓存恢复见[标题缓存验收](rust-title-cache-parity.md)，消息转换异常仍未完成。

## 行为与证据

`rust/tests/test_record_diagnostics.py` 通过真实 CLI 子进程比较 Python 与 Rust 的完整退出码、stdout/stderr、JSON 结构和 Markdown/raw 字节，并核对源数据 hash 与输出文件权限。不对警告内容做归一化后再比较。

| Python 契约 | Rust 归属 | 验证 |
| --- | --- | --- |
| 完整坏行包括非法 JSON、非法 UTF-8 和非对象 JSON；保留前后健康记录 | `jsonl.rs`、各 JSONL 正文读取器 | Codex、Claude、Pi、Kimi context/wire × 中英文，多格式导出和 print 完整差分 |
| 每次扫描按文件汇总坏行数量，最多展示前五个一基行号；空白行不算坏行，未终止的坏尾行不告警 | `jsonl.rs` | 七条坏行、空白行、后续健康消息及未完成尾行组成同一 fixture，校验计数和行号 |
| 警告次数取决于读取过程，多个输出格式复用一次完整读取 | `kimi.rs`、`uri_workflow.rs` | Codex/Claude/Pi 各一次；Kimi context 无 wire 时两次，wire-only 三次，与 Python 当前行为一致，不自行去重 |
| head、列表和 JSONL raw 不输出正文坏行警告 | metadata 读取、工作流 | 五种文件来源 × 中英文，完整输出差分；raw 保留原始坏字节 |
| Codex 标题索引中的坏行静默跳过，仍使用后续有效标题 | `codex.rs` | 两种语言的 head；只验收这一条索引扫描规则，不表示标题缓存错误已全部关闭 |
| OpenCode 旧表、ZCode 的坏消息/part 告警后继续，SQLite raw 同样需要读取并告警 | `sqlite_legacy.rs` | 非法 JSON、非对象、非法 UTF-8 BLOB、包含合法 JSON 的 BLOB、NULL、数值；raw-only 与全部格式的中英文完整差分 |
| 警告中的动态字段清理终端控制字符 | `diagnostics.rs` | SQLite 记录 ID 含换行、ESC 和双向控制字符，结果与 Python 完整 stderr 一致 |

新增 30 个 CLI 用例，替代 4 个只比较恢复内容或警告存在性的旧用例，净增 26 个，CLI 套件合计 732 个。Rust 单元测试保持 15 个。测试使用隔离的临时文件和 SQLite，不读取真实用户数据。

## 实现边界

`Provider::read` 显式接收诊断 sink。JSONL 扫描和旧 SQLite 读取器发送结构化 `RecoverableDiagnostic`，不直接打印。工作流负责本地化并写入传入的警告流；静默 metadata 扫描使用空 sink。没有全局可变诊断状态，也不缓存完整警告列表。

旧 SQLite 的 `data` 列只有 TEXT 才可进入 JSON 对象解析；其他类型按 Python 契约视为坏记录。读取 SQL 将这些单元投影为 NULL，使 BLOB 不会在通用行解码阶段终止整批读取。共享 SQLite 解码器及其他 Provider 的 BLOB 处理没有改变。

## 仍待完成

- Codex/Claude 标题索引打开、解析、条目跳过及同实例刷新已在后续验证，见[标题缓存验收](rust-title-cache-parity.md)；底层错误全文与其他极端标题字段仍待对齐。
- Codex/Claude/Pi 单条消息转换失败时的继续读取与本地化原因；底层错误全文和异常类型尚未全部一致。
- 长生命周期发现刷新、缓存、lease/LRU、并发失效，以及极端输入与跨平台验证。

P2 仍未完成。搜索、配置、Collect、Ratatui 与 pip/npm Rust 发布切换保持在后续阶段。

## 本轮验证

新增用例及相关旧 SQLite/JSONL 回归共 60 passed；随后移除被替代的 4 个旧用例。全部数据来自临时合成 fixture。

2026-09-24，macOS arm64，固定 Rust 1.90.0：最终代码的完整 `just isok` 通过，Python 2596 passed / 1 skipped、Rust 单元测试 15 passed、CLI 差分与边界 732 passed、npm 74 passed、Web E2E 13 passed。`just build-rust` release 构建通过。

Python 生产源码与 `dca2d97` 相同，P0 evaluator 四个脚本相对 `9c1cf61` 无改动；没有新增依赖。

实现提交：`dd95821`。[原七场景复测](benchmarks/rust-p2-record-warnings.md)在干净 checkout 上通过结果比较与源 hash 校验；这些健康数据场景不测坏记录警告的性能。
