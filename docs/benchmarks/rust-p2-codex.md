# Rust P2：Codex 消息与导出复测

本批增加 Codex 工具调用、patch、计划审批、skill/subagent、上下文识别，以及 Markdown/raw/混合导出。功能证据见 [Codex 差分验收](../rust-codex-parity.md)。性能评估继续使用 P0 的 evaluator 和 fixture，增加已有的 `export-large-json-md` 场景，共比较五个场景；其他 Provider、搜索、Collect、Ratatui 与发布切换尚未完成。

## 测量条件

- 初次测量 checkout：`ca4b1db3f9b3b9efc9d2d00e05ef7833644634c8`；缓冲优化后：`1c037d3a1024460c75a7be6132330835893fb107`。四份报告测量时工作树均干净。
- Python 生产源码仍与 `dca2d97` 一致；benchmark 脚本没有修改。四份报告的五场景输出摘要全部通过同一比较器的等价性检查。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0；Rust 1.90.0，`cargo build --locked --release`。
- standard fixture：1001 个会话、503 个源文件、23,839,547 字节；列表只选择其中 501 个 Codex 会话。大会话包含一条 8 Mi 字符正文。
- 每场景一次预热、七次测量，每次启动新进程。每轮先 Python 源码、后 Rust，构建和测试已结束；OS 页缓存未清空，不是冷磁盘测试。
- 每个样本均校验完整工作负载结果，所有源文件 hash 不变。复杂工具消息由功能差分验证，本次性能 fixture 仍是 P0 的文本会话。

## 最终同轮结果

| 场景 | Python 源码中位数 ms | Rust 中位数 ms | Python/Rust |
| --- | ---: | ---: | ---: |
| 启动 / version | 138.94 | 4.24 | 32.76× |
| Codex 列表（501 个） | 244.11 | 46.51 | 5.25× |
| 大文件 head | 143.14 | 6.65 | 21.54× |
| 大正文 print | 238.71 | 43.92 | 5.43× |
| 大正文 JSON＋Markdown 导出 | 243.20 | 84.51 | 2.88× |

| 场景 | Python 峰值 RSS 中位数 MiB | Rust 峰值 RSS 中位数 MiB |
| --- | ---: | ---: |
| 启动 / version | 38.86 | 2.52 |
| Codex 列表 | 42.33 | 4.56 |
| 大文件 head | 39.23 | 3.80 |
| 大正文 print | 123.52 | 54.22 |
| JSON＋Markdown 导出 | 151.61 | 53.08 |

导出场景的 Rust 样本为 77.13–108.72 ms，Python 为 240.54–250.61 ms；峰值 RSS 中位数下降约 65%。release 二进制为 3,705,520 字节，仍只包含当前已迁移能力，不是最终等价制品的体积结论。

七个样本只提供描述统计。启动开销占部分场景的大部分耗时；不将这些倍数平均为应用整体加速比，也不据此宣称功能迁移完成。

## 首次测量发现的退步

`ca4b1db` 的 JSON＋Markdown 导出中位数为 **771.32 ms**，同轮 Python 为 **363.59 ms**，Rust 更慢。JSON 序列化直接写入 `File`，转义和排版会产生大量小写入。`1c037d3` 增加 `BufWriter`，序列化后显式 flush，再由原有流程 sync 和原子替换。没有改变输出内容或成功判定。

优化后的 Rust 导出实测为 **84.51 ms**。其他 Rust 场景两轮接近，例如 print 为 43.78 / 43.92 ms。两轮 Python 的时延差异明显，version 中位数为 269.57 / 138.94 ms，因此最终表只使用后一轮同期 Python 和 Rust；不跨轮拼接加速比，也不隐藏前一轮数据。

## 验证与后续

- 优化后完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust/Python 差分与边界 172 passed，npm 74 passed，网页 E2E 13 passed；格式、类型检查和 Clippy 通过。
- 完整错误文案/输出通道、发现刷新/缓存、极端输入、其他 Provider 和跨平台验收仍在[待办边界](../rust-codex-parity.md)中。未宣称远端 CI 或 Windows 已通过。
- 下一批进入 Claude Code / Kimi / Pi；完整功能矩阵通过后，再运行全量性能场景和正式分发制品。

## 复现与原始数据

先运行 `just build-rust`，然后使用相同场景测量两种实现：

```bash
uv run python scripts/benchmark_cli.py --profile standard \
  --case startup-version --case list-jsonl \
  --case head-large-jsonl --case print-large-jsonl \
  --case export-large-json-md \
  --output dist/benchmarks/p2-python-source.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-codex --profile standard \
  --case startup-version --case list-jsonl \
  --case head-large-jsonl --case print-large-jsonl \
  --case export-large-json-md \
  --baseline dist/benchmarks/p2-python-source.json \
  --output dist/benchmarks/p2-rust.json
```

- 最终 Python：[原始 JSON](2026-09-24-python-source-p2-codex-standard.json) / [明细](2026-09-24-python-source-p2-codex-standard.md)。
- 最终 Rust：[原始 JSON](2026-09-24-rust-p2-codex-standard.json) / [明细](2026-09-24-rust-p2-codex-standard.md)。
- 优化前同期 Python：[原始 JSON](2026-09-24-python-source-p2-codex-before-buffer.json) / [明细](2026-09-24-python-source-p2-codex-before-buffer.md)。
- 优化前 Rust：[原始 JSON](2026-09-24-rust-p2-codex-before-buffer.json) / [明细](2026-09-24-rust-p2-codex-before-buffer.md)。
