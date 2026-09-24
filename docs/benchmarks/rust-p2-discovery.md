# Rust P2：共享发现后的七场景复测

本批增加跨 Provider 列表、可用性与部分失败隔离。功能范围见[共享发现验收](../rust-discovery-parity.md)。性能评估沿用原六场景，并开放 P0 evaluator 已有的 `list-all`；没有修改 evaluator 或 fixture。

## 测量条件

- 实现 checkout：`92bace38fef9f3f32d91d47c720ec30bb4492cf7`，Python、Rust 测量时工作树均干净。
- Python 生产源码仍与 `dca2d97` 一致；源码、evaluator、fixture 和 `uv.lock` 的 hash 与[上一批](rust-p2-desktop.md)相同。原始报告保留全部 hash 和输出校验摘要。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0；Rust 1.90.0，`cargo build --locked --release`。
- Python / fixture SQLite 3.50.4，Rust bundled SQLite 3.53.2。这是实际 CLI 实现的端到端比较，SQLite 引擎与并发策略差异均包含在结果中。
- standard fixture：501 个 Codex、500 个 OpenCode V2 会话，503 个源文件，23,839,547 字节；大会话包含一条 8 Mi 字符正文。其他八个来源在这个 fixture 中不可用。
- 全量检查与构建结束后，先运行 Python，再运行 Rust。每场景预热 1 次、测量 7 次，每次为新进程；未清空 OS 页缓存，不是冷磁盘测试。
- 七场景全部通过原比较器，每个样本通过结果校验；源数据 hash 保持不变。

## 同轮结果

| 场景 | Python 中位数 ms | Rust 中位数 ms | Python/Rust |
| --- | ---: | ---: | ---: |
| 启动 / version | 141.08 | 4.43 | 31.82× |
| Codex 列表（501 个） | 236.45 | 47.24 | 5.01× |
| OpenCode V2 列表（500 个） | 144.93 | 9.34 | 15.51× |
| 跨 Provider 列表（1001 个） | 246.17 | 50.77 | 4.85× |
| 大文件 head | 142.84 | 6.89 | 20.73× |
| 大正文 print | 243.19 | 45.94 | 5.29× |
| 大正文 JSON＋Markdown 导出 | 248.61 | 79.39 | 3.13× |

| 场景 | Python 峰值 RSS 中位数 MiB | Rust 峰值 RSS 中位数 MiB |
| --- | ---: | ---: |
| 启动 / version | 38.83 | 2.69 |
| Codex 列表 | 42.23 | 5.27 |
| OpenCode V2 列表 | 40.84 | 8.12 |
| 跨 Provider 列表 | 43.98 | 9.41 |
| 大文件 head | 39.27 | 4.22 |
| 大正文 print | 123.64 | 54.69 |
| JSON＋Markdown 导出 | 151.67 | 53.56 |

`list-all` 样本范围为 Python 244.10–251.01 ms、Rust 50.26–51.20 ms；峰值 RSS 中位数下降约 78.6%。Rust 按注册顺序逐个发现，Python 使用线程池；没有因为 benchmark 新增并行实现。此场景只能代表固定 Codex/OpenCode 混合数据，不能代表十种来源均有大量数据时的表现。

release 二进制为 6,193,216 字节，比上一批 6,168,304 字节增加约 0.40%；这是未打包的可执行文件大小。原六场景的 Rust 中位耗时相对上一批变化在 −3.1% 至 +0.6% 之间；print 为 45.66 → 45.94 ms，导出为 79.13 → 79.39 ms。没有做前后版本同轮交错测量，这些历史差值不能区分代码与机器状态影响，也不据此宣称全部路径没有回退。

7 个样本只用于描述统计，不声称统计显著性，不汇总成应用整体加速比。完整功能对齐后的最终复测、其他 Provider 的代表性性能、配置/搜索/Collect/TUI 与发布安装体验仍待后续验收。

## 验证范围

完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 单元测试 1 passed，CLI 差分与边界 597 passed，npm 74 passed，Web E2E 13 passed。最后的数据结构归属和测试断言整理后，`just check-rust` 再次通过。固定工具链 release 构建完成后才开始测量。

P2 尚未完成。错误类型、底层文案、部分 URI 诊断及实例复用的缓存/刷新仍有待验收项，见[功能记录](../rust-discovery-parity.md)。本轮没有改变 Python 发布行为。

## 复现与原始数据

```bash
just build-rust

uv run python scripts/benchmark_cli.py --label python-source-p2-discovery --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --output dist/benchmarks/python-source-p2-discovery.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-discovery --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --baseline dist/benchmarks/python-source-p2-discovery.json \
  --output dist/benchmarks/rust-p2-discovery.json
```

- Python：[原始 JSON](2026-09-24-python-source-p2-discovery-standard.json) / [明细](2026-09-24-python-source-p2-discovery-standard.md)。
- Rust：[原始 JSON](2026-09-24-rust-p2-discovery-standard.json) / [明细](2026-09-24-rust-p2-discovery-standard.md)。
