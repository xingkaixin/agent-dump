# Rust P2：运行中来源配置对齐后的复测

本批对齐十个 Provider 的运行中候选配置与来源选择规则，包含 Codex 标题索引和 Cursor 旧 Session 读取，范围见[来源配置验收](../rust-runtime-sources-parity.md)。复测沿用原七个健康 Codex/OpenCode V2 场景，每个样本都是独立进程，不测同实例切换配置、来源恢复或其余八个 Provider 的性能。

## 测量条件

- 实现 checkout：`a42bbc6712ec8d0f53bbfa63c90782af20ef60c7`；Python、Rust 测量时工作树均干净。
- Python 生产源码仍与 `dca2d97` 一致。源码、evaluator、fixture 和 `uv.lock` 的 hash 与[上一批](rust-p2-source-selection.md)相同，完整 hash 保存在原始报告。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0，固定 Rust 1.90.0，`cargo build --locked --release`。
- Python / fixture SQLite 3.50.4，Rust bundled SQLite 3.53.2；比较的是实际 CLI 实现，包含数据库引擎与发现并发策略差异。
- standard fixture：501 个 Codex、500 个 OpenCode V2 会话，503 个源文件、23,839,547 字节；大会话包含一条 8 Mi 字符正文。其他八个 Provider 无可用数据。
- 全量检查和构建结束后，先测 Python，再测 Rust。每场景预热 1 次、测量 7 次，每次为新进程；没有清空 OS 页缓存，不是冷磁盘测试。
- 七场景通过原比较器，每个样本通过结果校验，源数据 hash 不变。报告中的二进制 SHA 与实际 release 产物相同；未修改 evaluator 或 fixture。

## 同轮结果

| 场景 | Python 中位数 ms | Rust 中位数 ms | Python/Rust |
| --- | ---: | ---: | ---: |
| 启动 / version | 141.64 | 4.66 | 30.39× |
| Codex 列表（501 个） | 237.99 | 47.73 | 4.99× |
| OpenCode V2 列表（500 个） | 147.53 | 9.11 | 16.20× |
| 跨 Provider 列表（1001 个） | 247.15 | 50.94 | 4.85× |
| 大文件 head | 143.62 | 7.02 | 20.46× |
| 大正文 print | 244.52 | 45.42 | 5.38× |
| 大正文 JSON＋Markdown 导出 | 246.52 | 77.79 | 3.17× |

| 场景 | Python 峰值 RSS 中位数 MiB | Rust 峰值 RSS 中位数 MiB |
| --- | ---: | ---: |
| 启动 / version | 38.75 | 2.69 |
| Codex 列表 | 42.27 | 5.30 |
| OpenCode V2 列表 | 40.94 | 8.03 |
| 跨 Provider 列表 | 43.91 | 9.42 |
| 大文件 head | 39.28 | 4.17 |
| 大正文 print | 123.45 | 54.83 |
| JSON＋Markdown 导出 | 151.69 | 53.67 |

release 二进制为 6,352,752 字节，比上一批 6,331,632 字节增加约 0.33%；这是未打包的可执行文件大小。跨 Provider 列表的 Rust 样本为 50.75–53.86 ms，导出为 75.51–77.95 ms，启动为 4.27–5.03 ms。

相对上一批，Rust 七场景中位耗时变化为 −2.9% 至 +3.6%。跨 Provider 列表从 50.79 增至 50.94 ms，head 从 6.78 增至 7.02 ms，print 从 46.79 降至 45.42 ms，导出从 78.13 降至 77.79 ms。Python 源码未变，本轮跨 Provider 列表与导出仍分别从 255.18 / 253.58 ms 降至 247.15 / 246.52 ms；同轮加速比变化不能归因于单一 Rust 修改。

前后版本没有做同轮交错测量，历史差值不能区分代码变化与机器状态影响。7 个样本仅描述本次测量，不表示统计显著性、整体应用加速比或全部路径均无回退；原始样本一并保留。

## 验证与边界

最终代码的完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 单元测试 27 passed、CLI 差分与边界 834 passed，npm 74 passed、Web E2E 13 passed。固定工具链 release 构建通过后才开始测量。

P2 仍在进行。正文缓存、lease/LRU、并发失效、单次操作内的配置竞争、极端输入与跨平台验收待完成。搜索、Collect、Ratatui 与发布安装性能留在后续阶段，pip/npm 继续使用 Python。

## 复现与原始数据

```bash
just build-rust

uv run python scripts/benchmark_cli.py --label python-source-p2-runtime-sources --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --output dist/benchmarks/python-source-p2-runtime-sources.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-runtime-sources --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --baseline dist/benchmarks/python-source-p2-runtime-sources.json \
  --output dist/benchmarks/rust-p2-runtime-sources.json
```

- Python：[原始 JSON](2026-09-24-python-source-p2-runtime-sources-standard.json) / [明细](2026-09-24-python-source-p2-runtime-sources-standard.md)。
- Rust：[原始 JSON](2026-09-24-rust-p2-runtime-sources-standard.json) / [明细](2026-09-24-rust-p2-runtime-sources-standard.md)。
