# Rust P2：Provider 专属错误接入后的复测

本批补齐三个桌面 Provider 的 schema、源缺失与存储迁移错误，并调整共享错误传播。功能范围见[专属错误验收](../rust-provider-errors-parity.md)。复测仍使用原七个成功场景，不测失败诊断耗时或这三个 Provider 的性能。

## 测量条件

- 实现 checkout：`99575b92353f8810d25e8b030e0e6ff3e433c907`；Python、Rust 测量时工作树均干净。
- Python 生产源码仍与 `dca2d97` 一致。源码、evaluator、fixture 和 `uv.lock` 的 hash 与[上一批](rust-p2-uri.md)相同，完整 hash 保存在原始报告。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0，Rust 1.90.0，`cargo build --locked --release`。
- Python / fixture SQLite 3.50.4，Rust bundled SQLite 3.53.2；这是实际 CLI 实现的比较，包含引擎及发现并发策略差异。
- standard fixture：501 个 Codex、500 个 OpenCode V2 会话，503 个源文件、23,839,547 字节；大会话包含一条 8 Mi 字符正文。其他八个 Provider 无可用数据。
- 全量检查及构建结束后，先测 Python，再测 Rust。每场景预热 1 次、测量 7 次，每次为新进程；未清空 OS 页缓存，不是冷磁盘测试。
- 七场景全部通过原比较器，每个样本通过结果校验，源数据 hash 不变。未修改 evaluator 或 fixture。

## 同轮结果

| 场景 | Python 中位数 ms | Rust 中位数 ms | Python/Rust |
| --- | ---: | ---: | ---: |
| 启动 / version | 148.69 | 4.46 | 33.33× |
| Codex 列表（501 个） | 245.23 | 47.07 | 5.21× |
| OpenCode V2 列表（500 个） | 153.80 | 9.17 | 16.77× |
| 跨 Provider 列表（1001 个） | 249.61 | 51.37 | 4.86× |
| 大文件 head | 142.60 | 7.11 | 20.06× |
| 大正文 print | 244.76 | 46.26 | 5.29× |
| 大正文 JSON＋Markdown 导出 | 247.53 | 78.95 | 3.14× |

| 场景 | Python 峰值 RSS 中位数 MiB | Rust 峰值 RSS 中位数 MiB |
| --- | ---: | ---: |
| 启动 / version | 38.80 | 2.66 |
| Codex 列表 | 42.30 | 5.25 |
| OpenCode V2 列表 | 40.97 | 7.94 |
| 跨 Provider 列表 | 43.89 | 9.45 |
| 大文件 head | 39.30 | 4.28 |
| 大正文 print | 123.48 | 55.41 |
| JSON＋Markdown 导出 | 151.62 | 53.61 |

release 二进制为 6,275,904 字节，比上一批 6,236,640 字节增加约 0.63%；这是未打包的可执行文件大小。跨 Provider 列表的 Rust 样本为 50.58–57.24 ms，导出为 77.48–87.18 ms。

相对上一批，Rust version 中位耗时从 4.74 降至 4.46 ms（约 −5.9%），其他六场景变化为 −1.7% 至 +1.4%。没有对前后版本做同轮交错测量，这些历史差值不能区分代码变化和机器状态影响。7 个样本只描述本次测量，不声称统计显著性、整体应用加速比或所有路径均无回退。

## 验证与边界

完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 单元测试 5 passed、CLI 差分与边界 706 passed，npm 74 passed、Web E2E 13 passed。固定工具链 release 构建通过后才开始测量。

P2 仍在进行。其余 Provider 的专属错误、损坏记录警告、刷新/缓存及跨平台验收待完成。搜索、Collect、Ratatui 与发布安装性能留在后续阶段，pip/npm 继续使用 Python。

## 复现与原始数据

```bash
just build-rust

uv run python scripts/benchmark_cli.py --label python-source-p2-provider-errors --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --output dist/benchmarks/python-source-p2-provider-errors.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-provider-errors --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --baseline dist/benchmarks/python-source-p2-provider-errors.json \
  --output dist/benchmarks/rust-p2-provider-errors.json
```

- Python：[原始 JSON](2026-09-24-python-source-p2-provider-errors-standard.json) / [明细](2026-09-24-python-source-p2-provider-errors-standard.md)。
- Rust：[原始 JSON](2026-09-24-rust-p2-provider-errors-standard.json) / [明细](2026-09-24-rust-p2-provider-errors-standard.md)。
