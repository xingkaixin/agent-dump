# Rust P2：十个 Provider 接入后的六场景复测

本批接入 Cursor、DeepChat、Cherry Studio、MiniMax，并扩展标准化消息与 JSON 投影。功能证据见[本批差分验收](../rust-desktop-parity.md)。本报告重跑原有六场景，检查共享模块变化后的 Codex / OpenCode 表现；四个新增 Provider 的代表性性能尚未测量。

## 测量条件

- 实现 checkout：`a884907ffda3cb849663c67dbac859ca66ec2660`，两份报告测量时工作树均干净。
- Python 生产源码仍与 `dca2d97` 一致；源码、P0 evaluator、fixture 和 `uv.lock` 的 hash 与[上一批](rust-p2-sqlite.md)相同。没有为 Rust 修改输入、计时范围或结果摘要。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0；固定 Rust 1.90.0，`cargo build --locked --release`。
- Python / fixture SQLite 3.50.4；Rust 继续使用 bundled SQLite 3.53.2。SQLite 列表是两种实现的端到端比较，不能把差异全部归因于语言。
- standard fixture：1001 个会话、503 个源文件、23,839,547 字节；501 个 Codex 会话、500 个 OpenCode V2 会话，大会话包含一条 8 Mi 字符正文。
- 完整门禁与构建结束后，顺序运行 Python、Rust。每场景 1 次预热、7 次测量，每次为新进程；OS 页缓存不清空，不是冷磁盘测试。
- 六场景全部通过原比较器，每个样本通过结果校验，源文件 hash 保持不变。

## 同轮结果

| 场景 | Python 中位数 ms | Rust 中位数 ms | Python/Rust |
| --- | ---: | ---: | ---: |
| 启动 / version | 143.77 | 4.57 | 31.46× |
| Codex 列表（501 个） | 244.97 | 47.87 | 5.12× |
| OpenCode V2 列表（500 个） | 149.10 | 9.35 | 15.94× |
| 大文件 head | 146.28 | 7.11 | 20.56× |
| 大正文 print | 252.07 | 45.66 | 5.52× |
| 大正文 JSON＋Markdown 导出 | 267.47 | 79.13 | 3.38× |

| 场景 | Python 峰值 RSS 中位数 MiB | Rust 峰值 RSS 中位数 MiB |
| --- | ---: | ---: |
| 启动 / version | 38.91 | 2.67 |
| Codex 列表 | 42.31 | 5.42 |
| OpenCode V2 列表 | 40.89 | 7.92 |
| 大文件 head | 39.23 | 4.19 |
| 大正文 print | 123.50 | 54.67 |
| JSON＋Markdown 导出 | 151.69 | 55.34 |

SQLite 列表样本范围为 Python 145.75–155.58 ms、Rust 8.93–9.92 ms；导出为 Python 253.23–296.81 ms、Rust 76.56–80.21 ms。导出峰值 RSS 中位数低约 63.5%。release 二进制为 6,168,304 字节，相比上一批 5,882,896 字节增加 4.85%；这是未打包的可执行文件大小。

相较上一批第二轮，Rust Codex 列表为 46.19 → 47.87 ms，print 为 44.44 → 45.66 ms，导出为 74.60 → 79.13 ms，后者增加约 6.1%；导出 RSS 为 53.44 → 55.34 MiB。本批改变了 JSON 投影与消息扩展字段，但没有做前后版本在同轮的交错测量，因此这些历史差值不能区分代码和机器状态影响。保留数据供后续完整功能验收后的性能分析，不把本轮表述为各路径均无回退。

所有数字都是少量样本的描述统计，不声称统计显著性，不平均成应用整体加速比。新 Provider、缓存/索引、终端交互与安装体验仍需要对应工作负载。

## 验证范围

完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 差分与边界 554 passed，npm 74 passed，网页 E2E 13 passed；固定工具链 release 构建成功。

Rust 新增 161 个用例，其中 4 个只验证源目录导出保护。Python 当前允许这四个 Provider 向数据库所在目录导出，Rust 按仓库数据安全约束拒绝；这是[已记录的差异](../rust-desktop-parity.md#已确认差异与只读边界)，没有改写比较器来隐藏。十个 Provider 已接入不代表全部 Provider contract 完成，P2、完整工作流和跨平台发布验收仍在推进。

## 复现与原始数据

```bash
just build-rust

uv run python scripts/benchmark_cli.py --label python-source-p2-desktop --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --output dist/benchmarks/python-source-p2-desktop.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-desktop --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --baseline dist/benchmarks/python-source-p2-desktop.json \
  --output dist/benchmarks/rust-p2-desktop.json
```

- Python：[原始 JSON](2026-09-24-python-source-p2-desktop-standard.json) / [明细](2026-09-24-python-source-p2-desktop-standard.md)。
- Rust：[原始 JSON](2026-09-24-rust-p2-desktop-standard.json) / [明细](2026-09-24-rust-p2-desktop-standard.md)。
