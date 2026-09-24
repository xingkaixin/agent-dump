# Rust P2：记录转换恢复后的复测

本批接入 Codex/Claude/Pi 的逐记录转换恢复与本地化警告，保留已有消息和工具关联，范围见[转换恢复验收](../rust-message-conversion-parity.md)。复测沿用原七个健康数据场景，不测 Claude、Pi 或损坏记录的恢复性能。

## 测量条件

- 实现 checkout：`fa39040f15a4fa8ca064e161e15305cb9fd9df17`；Python、Rust 测量时工作树均干净。
- Python 生产源码仍与 `dca2d97` 一致。源码、evaluator、fixture 和 `uv.lock` 的 hash 与[上一批](rust-p2-title-cache.md)相同，完整 hash 保存在原始报告。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0，固定 Rust 1.90.0，`cargo build --locked --release`。
- Python / fixture SQLite 3.50.4，Rust bundled SQLite 3.53.2；比较的是实际 CLI 实现，包含数据库引擎与发现并发策略差异。
- standard fixture：501 个 Codex、500 个 OpenCode V2 会话，503 个源文件、23,839,547 字节；大会话包含一条 8 Mi 字符正文。其他八个 Provider 无可用数据。
- 全量检查和构建结束后，先测 Python，再测 Rust。每场景预热 1 次、测量 7 次，每次为新进程；没有清空 OS 页缓存，不是冷磁盘测试。
- 七场景通过原比较器，每个样本通过结果校验，源数据 hash 不变。报告中的二进制 SHA 与实际 release 产物相同；未修改 evaluator 或 fixture。

## 同轮结果

| 场景 | Python 中位数 ms | Rust 中位数 ms | Python/Rust |
| --- | ---: | ---: | ---: |
| 启动 / version | 194.30 | 4.99 | 38.93× |
| Codex 列表（501 个） | 376.84 | 48.58 | 7.76× |
| OpenCode V2 列表（500 个） | 203.58 | 9.55 | 21.32× |
| 跨 Provider 列表（1001 个） | 256.68 | 51.71 | 4.96× |
| 大文件 head | 145.37 | 7.09 | 20.49× |
| 大正文 print | 245.96 | 45.62 | 5.39× |
| 大正文 JSON＋Markdown 导出 | 252.59 | 82.58 | 3.06× |

| 场景 | Python 峰值 RSS 中位数 MiB | Rust 峰值 RSS 中位数 MiB |
| --- | ---: | ---: |
| 启动 / version | 38.98 | 2.70 |
| Codex 列表 | 42.33 | 5.23 |
| OpenCode V2 列表 | 40.86 | 7.97 |
| 跨 Provider 列表 | 44.09 | 9.45 |
| 大文件 head | 39.19 | 4.22 |
| 大正文 print | 123.44 | 54.75 |
| JSON＋Markdown 导出 | 151.59 | 55.53 |

release 二进制为 6,331,312 字节，比上一批 6,314,352 字节增加约 0.27%；这是未打包的可执行文件大小。跨 Provider 列表的 Rust 样本为 51.15–57.74 ms，导出为 77.08–103.60 ms，启动为 4.36–10.60 ms。

相对上一批，Rust 七场景中位耗时变化为 −0.4% 至 +12.8%。跨 Provider 列表从 51.02 增至 51.71 ms，导出从 81.68 增至 82.58 ms。Python 源码未变，但本轮启动、Codex 列表、OpenCode V2 列表分别从 142.38 / 243.39 / 148.86 ms 增至 194.30 / 376.84 / 203.58 ms；这些场景较高的同轮加速比不能归因于 Rust 本批修改。

前后版本没有做同轮交错测量，历史差值不能区分代码变化与机器状态影响。7 个样本仅描述本次测量，不表示统计显著性、整体应用加速比或全部路径均无回退；原始慢样本一并保留。

## 验证与边界

最终代码的完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 单元测试 17 passed、CLI 差分与边界 832 passed，npm 74 passed、Web E2E 13 passed。固定工具链 release 构建通过后才开始测量。

P2 仍在进行。其他极端消息/数值字段、源目录刷新、正文缓存和跨平台验收待完成，底层错误原因文字也未全部对齐。搜索、Collect、Ratatui 与发布安装性能留在后续阶段，pip/npm 继续使用 Python。

## 复现与原始数据

```bash
just build-rust

uv run python scripts/benchmark_cli.py --label python-source-p2-message-conversion --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --output dist/benchmarks/python-source-p2-message-conversion.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-message-conversion --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --baseline dist/benchmarks/python-source-p2-message-conversion.json \
  --output dist/benchmarks/rust-p2-message-conversion.json
```

- Python：[原始 JSON](2026-09-24-python-source-p2-message-conversion-standard.json) / [明细](2026-09-24-python-source-p2-message-conversion-standard.md)。
- Rust：[原始 JSON](2026-09-24-rust-p2-message-conversion-standard.json) / [明细](2026-09-24-rust-p2-message-conversion-standard.md)。
