# Rust P2 最终性能复测

P2 功能与三平台验证见[最终验收](../rust-p2-completion.md)。本报告沿用 P0 原 evaluator 的七个已实现场景，与同一机器上的 Python 参考实现配对测量。

## 测量条件

- 实现 checkout：`d074c63213dc6849f19e661121ad9b3f3f7cbf6d`；两次测量时工作树均干净。
- Python 生产源码仍与 `dca2d97` 一致；evaluator 仍与 `9c1cf61` 一致。源码、evaluator、fixture 与 `uv.lock` 的 SHA-256 与上一批完全相同，完整值在原始 JSON 中。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0，Rust 1.90.0，`cargo build --locked --release`。Python 3.11.15，Python/fixture SQLite 3.50.4，Rust bundled SQLite 3.53.2；结果包含数据库引擎与并发发现策略差异。
- standard fixture：501 个 Codex、500 个 OpenCode V2 会话；503 个源文件，共 23,839,547 字节。大会话包含一条 8 Mi 字符正文，其余八个 Provider 无可用数据。
- 本地完整检查和构建结束后，先测 Python，再测 Rust；每场景预热 1 次、测量 7 次，每个样本为新进程。OS 页缓存未清空，不能视为冷磁盘测试。
- 七场景均通过原比较器，每个样本通过结果校验，源数据 hash 不变；release 二进制 SHA-256 与原始报告一致。

## 同轮结果

| 场景 | Python 中位数 ms | Rust 中位数 ms | Python/Rust |
| --- | ---: | ---: | ---: |
| 启动 / version | 154.90 | 5.07 | 30.55× |
| Codex 列表（501 个） | 253.03 | 52.43 | 4.83× |
| OpenCode V2 列表（500 个） | 158.69 | 10.00 | 15.87× |
| 跨 Provider 列表（1001 个） | 269.32 | 56.90 | 4.73× |
| 大文件 head | 154.62 | 7.61 | 20.33× |
| 大正文 print | 260.05 | 52.12 | 4.99× |
| 大正文 JSON＋Markdown 导出 | 267.14 | 85.93 | 3.11× |

| 场景 | Python 峰值 RSS 中位数 MiB | Rust 峰值 RSS 中位数 MiB | 变化 |
| --- | ---: | ---: | ---: |
| 启动 / version | 38.83 | 2.66 | -93.2% |
| Codex 列表（501 个） | 42.34 | 5.61 | -86.8% |
| OpenCode V2 列表（500 个） | 40.94 | 8.14 | -80.1% |
| 跨 Provider 列表（1001 个） | 44.03 | 9.83 | -77.7% |
| 大文件 head | 39.23 | 4.33 | -89.0% |
| 大正文 print | 123.62 | 55.45 | -55.1% |
| 大正文 JSON＋Markdown 导出 | 151.59 | 55.59 | -63.3% |

release 可执行文件为 6,541,232 字节；上一批为 6,352,752 字节，变化 +2.97%。此值是未打包二进制大小，不与 Python 解释器大小作包体积比较。

## 样本范围与历史变化

| 场景 | Rust min–max ms | Rust 中位数相对上一批 |
| --- | ---: | ---: |
| 启动 / version | 4.58–5.43 | +8.8% |
| Codex 列表（501 个） | 51.30–53.41 | +9.9% |
| OpenCode V2 列表（500 个） | 9.88–13.24 | +9.8% |
| 跨 Provider 列表（1001 个） | 56.14–58.55 | +11.7% |
| 大文件 head | 7.08–8.16 | +8.4% |
| 大正文 print | 51.59–67.40 | +14.7% |
| 大正文 JSON＋Markdown 导出 | 84.35–97.88 | +10.5% |

历史版本没有同轮交错测量，前后差值不能单独归因于代码变化。7 个样本描述本次运行，不表示统计显著性，也不合成为整体应用加速倍数。

本轮只测健康 Codex/OpenCode V2 的独立进程工作负载，不测缓存命中、同实例生命周期、其余八个 Provider、Query/Search、Collect、Ratatui 或安装耗时。其余功能和发布制品仍按迁移计划后续阶段验收。

## 复现与原始数据

```bash
just build-rust

uv run python scripts/benchmark_cli.py --label python-source-p2-final --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --output dist/benchmarks/python-source-p2-final.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-final --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --baseline dist/benchmarks/python-source-p2-final.json \
  --output dist/benchmarks/rust-p2-final.json
```

- Python：[原始 JSON](2026-09-24-python-source-p2-final-standard.json) / [明细](2026-09-24-python-source-p2-final-standard.md)。
- Rust：[原始 JSON](2026-09-24-rust-p2-final-standard.json) / [明细](2026-09-24-rust-p2-final-standard.md)。
