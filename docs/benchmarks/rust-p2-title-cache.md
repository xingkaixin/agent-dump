# Rust P2：标题缓存恢复后的复测

本批对齐 Codex/Claude 标题索引失败恢复、本地化警告、坏条目汇总与同实例刷新，范围见[标题缓存验收](../rust-title-cache-parity.md)。复测仍使用原七个健康数据场景，不测 Claude、损坏索引或长生命周期缓存刷新性能。

## 测量条件

- 实现 checkout：`768e4baeb2c57a55f6961309a6a5b39990eb6aa6`；Python、Rust 测量时工作树均干净。
- Python 生产源码仍与 `dca2d97` 一致。源码、evaluator、fixture 和 `uv.lock` 的 hash 与[上一批](rust-p2-record-warnings.md)相同，完整 hash 保存在原始报告。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0，固定 Rust 1.90.0，`cargo build --locked --release`。
- Python / fixture SQLite 3.50.4，Rust bundled SQLite 3.53.2；比较的是实际 CLI 实现，包含数据库引擎与发现并发策略差异。
- standard fixture：501 个 Codex、500 个 OpenCode V2 会话，503 个源文件、23,839,547 字节；大会话包含一条 8 Mi 字符正文。其他八个 Provider 无可用数据。
- 全量检查和构建结束后，先测 Python，再测 Rust。每场景预热 1 次、测量 7 次，每次为新进程；没有清空 OS 页缓存，不是冷磁盘测试。
- 七场景通过原比较器，每个样本通过结果校验，源数据 hash 不变。报告中的二进制 SHA 与实际 release 产物相同，未修改 evaluator 或 fixture。

## 同轮结果

| 场景 | Python 中位数 ms | Rust 中位数 ms | Python/Rust |
| --- | ---: | ---: | ---: |
| 启动 / version | 142.38 | 4.43 | 32.17× |
| Codex 列表（501 个） | 243.39 | 47.23 | 5.15× |
| OpenCode V2 列表（500 个） | 148.86 | 9.44 | 15.77× |
| 跨 Provider 列表（1001 个） | 253.62 | 51.02 | 4.97× |
| 大文件 head | 144.72 | 7.11 | 20.36× |
| 大正文 print | 245.07 | 45.79 | 5.35× |
| 大正文 JSON＋Markdown 导出 | 248.25 | 81.68 | 3.04× |

| 场景 | Python 峰值 RSS 中位数 MiB | Rust 峰值 RSS 中位数 MiB |
| --- | ---: | ---: |
| 启动 / version | 38.89 | 2.62 |
| Codex 列表 | 42.33 | 5.33 |
| OpenCode V2 列表 | 40.88 | 8.03 |
| 跨 Provider 列表 | 43.91 | 9.48 |
| 大文件 head | 39.25 | 4.23 |
| 大正文 print | 123.58 | 53.97 |
| JSON＋Markdown 导出 | 151.62 | 54.86 |

release 二进制为 6,314,352 字节，比上一批 6,295,936 字节增加约 0.29%；这是未打包的可执行文件大小。跨 Provider 列表的 Rust 样本为 50.21–51.83 ms，导出为 76.93–86.86 ms。

相对上一批，Rust 七场景中位耗时变化为 −5.0% 至 +3.4%。跨 Provider 列表从 53.69 降至 51.02 ms，导出从 79.03 增至 81.68 ms；本轮 Python 导出从 276.68 降至 248.25 ms，同轮加速比从 3.50× 变为 3.04×。前后版本没有做同轮交错测量，历史差值不能区分代码变化与机器状态影响。7 个样本仅描述本次测量，不表示统计显著性、整体应用加速比或全部路径均无回退。

## 验证与边界

最终代码的完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 单元测试 17 passed、CLI 差分与边界 784 passed，npm 74 passed、Web E2E 13 passed。固定工具链 release 构建通过后才开始测量。

P2 仍在进行。消息转换错误、其他刷新/缓存边界、极端输入与跨平台验收待完成。部分底层错误原因文字仍有差异。搜索、Collect、Ratatui 和发布安装性能留在后续阶段，pip/npm 继续使用 Python。

## 复现与原始数据

```bash
just build-rust

uv run python scripts/benchmark_cli.py --label python-source-p2-title-cache --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --output dist/benchmarks/python-source-p2-title-cache.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-title-cache --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --baseline dist/benchmarks/python-source-p2-title-cache.json \
  --output dist/benchmarks/rust-p2-title-cache.json
```

- Python：[原始 JSON](2026-09-24-python-source-p2-title-cache-standard.json) / [明细](2026-09-24-python-source-p2-title-cache-standard.md)。
- Rust：[原始 JSON](2026-09-24-rust-p2-title-cache-standard.json) / [明细](2026-09-24-rust-p2-title-cache-standard.md)。
