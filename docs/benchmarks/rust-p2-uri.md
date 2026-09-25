# Rust P2：URI 诊断对齐后的七场景复测

本批对齐 URI 共用失败诊断、输出通道和参数组合，功能证据见 [URI 验收记录](../rust-uri-parity.md)。性能复测沿用上一批的七个成功场景；它检查共享工作流修改后的表现，不测错误路径耗时。

## 测量条件

- 实现 checkout：`f3af42a497ebdce43eb72b96c3198d4df390f532`；Python、Rust 测量时工作树均干净。
- Python 生产源码仍与 `dca2d97` 一致；源码、evaluator、fixture 和 `uv.lock` 的 hash 与[上一批](rust-p2-discovery.md)相同。两份原始报告保留全部 hash 和结果校验摘要。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0；Rust 1.90.0，`cargo build --locked --release`。
- Python / fixture SQLite 3.50.4，Rust bundled SQLite 3.53.2；此处比较实际 CLI 实现，包含 SQLite 引擎与发现并发策略的差异。
- standard fixture：501 个 Codex、500 个 OpenCode V2 会话，503 个源文件，23,839,547 字节；大会话包含一条 8 Mi 字符正文。其他八个来源在此 fixture 中不可用。
- 全量检查与构建完成后，先测 Python，再测 Rust；每场景预热 1 次、测量 7 次，每次为新进程。未清空 OS 页缓存，不是冷磁盘测试。
- 七场景全部通过原比较器，每个样本通过校验；源数据 hash 保持不变。未修改 evaluator 或 fixture。

## 同轮结果

| 场景 | Python 中位数 ms | Rust 中位数 ms | Python/Rust |
| --- | ---: | ---: | ---: |
| 启动 / version | 145.76 | 4.74 | 30.76× |
| Codex 列表（501 个） | 249.42 | 47.36 | 5.27× |
| OpenCode V2 列表（500 个） | 153.18 | 9.33 | 16.42× |
| 跨 Provider 列表（1001 个） | 257.45 | 50.94 | 5.05× |
| 大文件 head | 148.51 | 7.01 | 21.18× |
| 大正文 print | 249.41 | 46.15 | 5.40× |
| 大正文 JSON＋Markdown 导出 | 253.94 | 78.26 | 3.24× |

| 场景 | Python 峰值 RSS 中位数 MiB | Rust 峰值 RSS 中位数 MiB |
| --- | ---: | ---: |
| 启动 / version | 38.88 | 2.64 |
| Codex 列表 | 42.34 | 5.17 |
| OpenCode V2 列表 | 40.94 | 8.09 |
| 跨 Provider 列表 | 44.05 | 9.58 |
| 大文件 head | 39.30 | 4.25 |
| 大正文 print | 123.53 | 55.52 |
| JSON＋Markdown 导出 | 151.58 | 55.62 |

release 二进制为 6,236,640 字节，比上一批 6,193,216 字节增加约 0.70%；这是未打包的可执行文件大小。跨 Provider 列表的 Rust 样本为 50.63–51.13 ms，导出为 77.18–89.08 ms。

相对上一批，Rust version 中位耗时从 4.43 增至 4.74 ms（约 +6.9%）；其他六个场景变化为 −1.4% 至 +1.8%。这些历史差值没有经过前后版本同轮交错测量，不能区分代码和机器状态的影响，也不据此宣称全部路径没有回退。

7 个样本只报告描述统计，不声称统计显著性或应用整体加速比。此 fixture 只有 Codex/OpenCode，且不触发失败诊断；其余 Provider、错误路径、搜索、Collect、TUI 与安装发布性能仍需后续验收。

## 验证范围

完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 单元测试 1 passed、CLI 差分与边界 681 passed，npm 74 passed，Web E2E 13 passed。固定工具链 release 构建通过后才开始测量。

P2 仍未完成。Provider 专属错误、部分底层原因文本、损坏行警告、缓存/刷新与跨平台边界见 [URI 功能记录](../rust-uri-parity.md)。本轮没有改变 Python 源码及 pip/npm 发布行为。

## 复现与原始数据

```bash
just build-rust

uv run python scripts/benchmark_cli.py --label python-source-p2-uri --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --output dist/benchmarks/python-source-p2-uri.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-uri --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --baseline dist/benchmarks/python-source-p2-uri.json \
  --output dist/benchmarks/rust-p2-uri.json
```

- Python：[原始 JSON](2026-09-24-python-source-p2-uri-standard.json) / [明细](2026-09-24-python-source-p2-uri-standard.md)。
- Rust：[原始 JSON](2026-09-24-rust-p2-uri-standard.json) / [明细](2026-09-24-rust-p2-uri-standard.md)。
