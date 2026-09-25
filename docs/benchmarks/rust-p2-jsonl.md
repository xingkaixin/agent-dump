# Rust P2：JSONL Provider 接入后的 Codex 复测

本批接入 Claude Code、Kimi 和 Pi，并抽出共享 Provider、发现及消息装配逻辑。功能证据见 [JSONL Provider 差分验收](../rust-jsonl-parity.md)。这里重跑原有五个 Codex 性能场景，检查公共模块变化后的表现；尚未测量三个新 Provider 的代表性性能。

## 测量条件

- 实现 checkout：`366954255f7cdb38841f3dbd2950121a418e69e3`，两份报告测量时工作树均干净。
- Python 生产源码仍与 `dca2d97` 一致；P0 evaluator、fixture v1 与锁文件均未改动，且与上一批报告的 hash 相同。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0；固定 Rust 1.90.0，`cargo build --locked --release`。
- standard fixture：1001 个会话、503 个源文件、23,839,547 字节；列表选择 501 个 Codex 会话，大会话包含一条 8 Mi 字符正文。
- 每场景 1 次预热、7 次测量，每次启动新进程。构建与测试结束后，先运行 Python 源码，再运行 Rust。OS 页缓存未清空，不是冷磁盘测试。
- 五场景全部通过原比较器的输出等价性检查，每个样本的源文件 hash 不变。未改写输入、计时范围或结果摘要来适配 Rust。

## 同轮结果

| 场景 | Python 中位数 ms | Rust 中位数 ms | Python/Rust |
| --- | ---: | ---: | ---: |
| 启动 / version | 138.57 | 3.97 | 34.87× |
| Codex 列表（501 个） | 238.69 | 46.57 | 5.13× |
| 大文件 head | 142.34 | 6.43 | 22.15× |
| 大正文 print | 238.43 | 43.63 | 5.47× |
| 大正文 JSON＋Markdown 导出 | 241.28 | 74.89 | 3.22× |

| 场景 | Python 峰值 RSS 中位数 MiB | Rust 峰值 RSS 中位数 MiB |
| --- | ---: | ---: |
| 启动 / version | 38.81 | 2.59 |
| Codex 列表 | 42.20 | 4.95 |
| 大文件 head | 39.19 | 4.05 |
| 大正文 print | 123.52 | 53.31 |
| JSON＋Markdown 导出 | 151.69 | 53.38 |

导出样本范围为 Python 237.29–253.31 ms、Rust 73.51–76.22 ms，Rust 峰值 RSS 中位数低约 64.8%。二进制为 3,945,168 字节，比上一批 3,705,520 字节增加 6.47%；新增 Provider 带来了体积增长。

相较[上一批 Rust 结果](rust-p2-codex.md)，列表为 46.51 → 46.57 ms，print 为 43.92 → 43.63 ms，导出为 84.51 → 74.89 ms。本轮没有观察到明显耗时回退；这些是少量样本的描述统计，不将轮次间波动归因于某一项代码调整，也不平均为应用整体加速比。

## 验证范围

本批完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 差分与边界 313 passed，npm 74 passed，网页 E2E 13 passed；固定工具链 release 构建成功。

三个新增 Provider 由 CLI 差分用例验证。它们不在本次性能 fixture 中，因此本表仅能说明已列出的 Codex 合成工作负载；不能证明完整功能迁移或新 Provider 的性能。剩余缓存、诊断、跨平台和其他 Provider 验收仍按[迁移计划](../rust-migration-plan.md)推进。

## 复现与原始数据

```bash
just build-rust

uv run python scripts/benchmark_cli.py --label python-source-p2-jsonl --profile standard \
  --case startup-version --case list-jsonl \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --output dist/benchmarks/python-source-p2-jsonl.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-jsonl --profile standard \
  --case startup-version --case list-jsonl \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --baseline dist/benchmarks/python-source-p2-jsonl.json \
  --output dist/benchmarks/rust-p2-jsonl.json
```

- Python：[原始 JSON](2026-09-24-python-source-p2-jsonl-standard.json) / [明细](2026-09-24-python-source-p2-jsonl-standard.md)。
- Rust：[原始 JSON](2026-09-24-rust-p2-jsonl-standard.json) / [明细](2026-09-24-rust-p2-jsonl-standard.md)。
