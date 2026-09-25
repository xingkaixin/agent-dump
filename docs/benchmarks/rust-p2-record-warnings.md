# Rust P2：坏记录警告接入后的复测

本批通过显式诊断 sink 对齐 JSONL 坏行和旧 SQLite 坏记录的中英文警告，并修正旧表 BLOB 坏记录导致整个导出中止的问题。范围见[坏记录警告验收](../rust-record-diagnostics-parity.md)。复测使用原七个健康数据场景，不测坏记录警告、旧 SQLite 或 Kimi 的性能。

## 测量条件

- 实现 checkout：`dd9582193bb905c14d75eb02249fbe8d742cd5c5`；Python、Rust 测量时工作树均干净。
- Python 生产源码仍与 `dca2d97` 一致。源码、evaluator、fixture 和 `uv.lock` 的 hash 与[上一批](rust-p2-source-errors.md)相同，完整 hash 保存在原始报告。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0，Rust 1.90.0，`cargo build --locked --release`。
- Python / fixture SQLite 3.50.4，Rust bundled SQLite 3.53.2；比较的是实际 CLI 实现，包含引擎及发现并发策略差异。
- standard fixture：501 个 Codex、500 个 OpenCode V2 会话，503 个源文件、23,839,547 字节；大会话包含一条 8 Mi 字符正文。其他八个 Provider 无可用数据。
- 全量检查及构建结束后，先测 Python，再测 Rust。每场景预热 1 次、测量 7 次，每次为新进程；未清空 OS 页缓存，不是冷磁盘测试。
- 七场景全部通过原比较器，每个样本通过结果校验，源数据 hash 不变。未修改 evaluator 或 fixture。

## 同轮结果

| 场景 | Python 中位数 ms | Rust 中位数 ms | Python/Rust |
| --- | ---: | ---: | ---: |
| 启动 / version | 143.93 | 4.59 | 31.35× |
| Codex 列表（501 个） | 246.73 | 47.48 | 5.20× |
| OpenCode V2 列表（500 个） | 149.36 | 9.22 | 16.20× |
| 跨 Provider 列表（1001 个） | 246.92 | 53.69 | 4.60× |
| 大文件 head | 164.53 | 7.35 | 22.38× |
| 大正文 print | 257.62 | 47.09 | 5.47× |
| 大正文 JSON＋Markdown 导出 | 276.68 | 79.03 | 3.50× |

| 场景 | Python 峰值 RSS 中位数 MiB | Rust 峰值 RSS 中位数 MiB |
| --- | ---: | ---: |
| 启动 / version | 38.89 | 2.70 |
| Codex 列表 | 42.34 | 5.33 |
| OpenCode V2 列表 | 40.94 | 8.08 |
| 跨 Provider 列表 | 43.20 | 9.56 |
| 大文件 head | 39.16 | 4.31 |
| 大正文 print | 123.41 | 53.50 |
| JSON＋Markdown 导出 | 151.45 | 53.53 |

release 二进制为 6,295,936 字节，比上一批 6,312,144 字节减少约 0.26%；这是未打包的可执行文件大小。跨 Provider 列表的 Rust 样本为 52.99–64.94 ms，导出为 75.96–80.22 ms。

相对上一批，Rust 七场景中位耗时变化为 −1.8% 至 +8.7%。跨 Provider 列表从 51.39 增至 53.69 ms，导出从 77.26 增至 79.03 ms；本轮 Python 导出也从 231.07 增至 276.68 ms，因此同轮加速比从 2.99× 变为 3.50×。前后版本未做同轮交错测量，历史差值不能区分代码变化和机器状态影响。7 个样本只描述本次测量，不声称统计显著性、整体应用加速比或所有路径均无回退。

## 验证与边界

最终代码的完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 单元测试 15 passed、CLI 差分与边界 732 passed，npm 74 passed、Web E2E 13 passed。固定工具链 release 构建通过后才开始测量。

P2 仍在进行。标题缓存和消息转换错误、刷新/缓存、极端输入及跨平台验收待完成。搜索、Collect、Ratatui 与发布安装性能留在后续阶段，pip/npm 继续使用 Python。

## 复现与原始数据

```bash
just build-rust

uv run python scripts/benchmark_cli.py --label python-source-p2-record-warnings --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --output dist/benchmarks/python-source-p2-record-warnings.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-record-warnings --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --baseline dist/benchmarks/python-source-p2-record-warnings.json \
  --output dist/benchmarks/rust-p2-record-warnings.json
```

- Python：[原始 JSON](2026-09-24-python-source-p2-record-warnings-standard.json) / [明细](2026-09-24-python-source-p2-record-warnings-standard.md)。
- Rust：[原始 JSON](2026-09-24-rust-p2-record-warnings-standard.json) / [明细](2026-09-24-rust-p2-record-warnings-standard.md)。
