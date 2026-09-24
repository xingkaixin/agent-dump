# Rust P2：来源选择与缺失重试后的复测

本批对齐固定配置下六个 Provider 的来源选择、缺失重试和已选路径保持，范围见[来源选择验收](../rust-source-selection-parity.md)。复测沿用原七个健康数据场景，每个样本都是独立进程，不测同实例刷新、来源消失或恢复性能，也不测 Claude、Kimi、Pi、ZCode。

## 测量条件

- 实现 checkout：`3e599a98efc7460dbf4c6aff547a70c10a5a9853`；Python、Rust 测量时工作树均干净。
- Python 生产源码仍与 `dca2d97` 一致。源码、evaluator、fixture 和 `uv.lock` 的 hash 与[上一批](rust-p2-message-conversion.md)相同，完整 hash 保存在原始报告。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0，固定 Rust 1.90.0，`cargo build --locked --release`。
- Python / fixture SQLite 3.50.4，Rust bundled SQLite 3.53.2；比较的是实际 CLI 实现，包含数据库引擎与发现并发策略差异。
- standard fixture：501 个 Codex、500 个 OpenCode V2 会话，503 个源文件、23,839,547 字节；大会话包含一条 8 Mi 字符正文。其他八个 Provider 无可用数据。
- 全量检查和构建结束后，先测 Python，再测 Rust。每场景预热 1 次、测量 7 次，每次为新进程；没有清空 OS 页缓存，不是冷磁盘测试。
- 七场景通过原比较器，每个样本通过结果校验，源数据 hash 不变。报告中的二进制 SHA 与实际 release 产物相同；未修改 evaluator 或 fixture。

## 同轮结果

| 场景 | Python 中位数 ms | Rust 中位数 ms | Python/Rust |
| --- | ---: | ---: | ---: |
| 启动 / version | 149.91 | 4.61 | 32.52× |
| Codex 列表（501 个） | 247.47 | 47.40 | 5.22× |
| OpenCode V2 列表（500 个） | 153.16 | 9.13 | 16.77× |
| 跨 Provider 列表（1001 个） | 255.18 | 50.79 | 5.02× |
| 大文件 head | 148.30 | 6.78 | 21.88× |
| 大正文 print | 250.67 | 46.79 | 5.36× |
| 大正文 JSON＋Markdown 导出 | 253.58 | 78.13 | 3.25× |

| 场景 | Python 峰值 RSS 中位数 MiB | Rust 峰值 RSS 中位数 MiB |
| --- | ---: | ---: |
| 启动 / version | 38.81 | 2.73 |
| Codex 列表 | 42.22 | 5.20 |
| OpenCode V2 列表 | 40.98 | 7.72 |
| 跨 Provider 列表 | 43.89 | 9.25 |
| 大文件 head | 39.28 | 4.17 |
| 大正文 print | 123.52 | 55.50 |
| JSON＋Markdown 导出 | 151.59 | 53.69 |

release 二进制为 6,331,632 字节，比上一批增加 320 字节；这是未打包的可执行文件大小。跨 Provider 列表的 Rust 样本为 49.96–51.31 ms，导出为 77.15–86.96 ms，启动为 4.31–5.14 ms。

相对上一批，Rust 七场景中位耗时变化为 −7.6% 至 +2.5%。跨 Provider 列表从 51.71 降至 50.79 ms，导出从 82.58 降至 78.13 ms，print 从 45.62 增至 46.79 ms。Python 源码未变，启动、Codex 列表、OpenCode V2 列表却分别从 194.30 / 376.84 / 203.58 ms 降至 149.91 / 247.47 / 153.16 ms；对应加速比变化不能归因于本批 Rust 修改。

前后版本没有做同轮交错测量，历史差值不能区分代码变化与机器状态影响。7 个样本仅描述本次测量，不表示统计显著性、整体应用加速比或全部路径均无回退；原始样本一并保留。

## 验证与边界

最终代码的完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 单元测试 22 passed、CLI 差分与边界 834 passed，npm 74 passed、Web E2E 13 passed。固定工具链 release 构建通过后才开始测量。

P2 仍在进行。运行中配置路径变化、其余 Provider 的长生命周期来源选择、正文缓存、极端输入与跨平台验收待完成，底层错误原因文字也未全部对齐。搜索、Collect、Ratatui 与发布安装性能留在后续阶段，pip/npm 继续使用 Python。

## 复现与原始数据

```bash
just build-rust

uv run python scripts/benchmark_cli.py --label python-source-p2-source-selection --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --output dist/benchmarks/python-source-p2-source-selection.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-source-selection --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --baseline dist/benchmarks/python-source-p2-source-selection.json \
  --output dist/benchmarks/rust-p2-source-selection.json
```

- Python：[原始 JSON](2026-09-24-python-source-p2-source-selection-standard.json) / [明细](2026-09-24-python-source-p2-source-selection-standard.md)。
- Rust：[原始 JSON](2026-09-24-rust-p2-source-selection-standard.json) / [明细](2026-09-24-rust-p2-source-selection-standard.md)。
