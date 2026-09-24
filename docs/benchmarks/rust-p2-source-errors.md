# Rust P2：源缺失诊断接入后的复测

本批补齐其余七个 Provider 的源缺失诊断，修正 Kimi raw 文件身份与 OpenCode V2 消失后的错误原因，并调整共享 raw 错误传播。功能范围见[源缺失验收](../rust-source-parity.md)。复测继续使用原七个成功场景，不测源缺失诊断或 Kimi 性能。

## 测量条件

- 实现 checkout：`0d2fc2ae1e7e0fb223556bf3a637414a9f162b5f`；Python、Rust 测量时工作树均干净。
- Python 生产源码仍与 `dca2d97` 一致。源码、evaluator、fixture 和 `uv.lock` 的 hash 与[上一批](rust-p2-provider-errors.md)相同，完整 hash 保存在原始报告。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0，Rust 1.90.0，`cargo build --locked --release`。
- Python / fixture SQLite 3.50.4，Rust bundled SQLite 3.53.2；比较的是实际 CLI 实现，包含 SQLite 引擎和发现并发策略差异。
- standard fixture：501 个 Codex、500 个 OpenCode V2 会话，503 个源文件、23,839,547 字节；大会话包含一条 8 Mi 字符正文。其他八个 Provider 无可用数据。
- 全量检查及构建结束后，先测 Python，再测 Rust。每场景预热 1 次、测量 7 次，每次为新进程；未清空 OS 页缓存，不是冷磁盘测试。
- 七场景全部通过原比较器，每个样本通过结果校验，源数据 hash 不变。未修改 evaluator 或 fixture。

## 同轮结果

| 场景 | Python 中位数 ms | Rust 中位数 ms | Python/Rust |
| --- | ---: | ---: | ---: |
| 启动 / version | 134.10 | 4.34 | 30.91× |
| Codex 列表（501 个） | 228.61 | 47.10 | 4.85× |
| OpenCode V2 列表（500 个） | 132.48 | 9.39 | 14.11× |
| 跨 Provider 列表（1001 个） | 239.77 | 51.39 | 4.67× |
| 大文件 head | 136.51 | 6.76 | 20.19× |
| 大正文 print | 236.09 | 44.40 | 5.32× |
| 大正文 JSON＋Markdown 导出 | 231.07 | 77.26 | 2.99× |

| 场景 | Python 峰值 RSS 中位数 MiB | Rust 峰值 RSS 中位数 MiB |
| --- | ---: | ---: |
| 启动 / version | 38.73 | 2.66 |
| Codex 列表 | 42.19 | 5.38 |
| OpenCode V2 列表 | 40.58 | 8.22 |
| 跨 Provider 列表 | 43.86 | 9.50 |
| 大文件 head | 39.11 | 4.30 |
| 大正文 print | 123.38 | 55.59 |
| JSON＋Markdown 导出 | 151.34 | 53.77 |

release 二进制为 6,312,144 字节，比上一批 6,275,904 字节增加约 0.58%；这是未打包的可执行文件大小。跨 Provider 列表的 Rust 样本为 50.91–62.80 ms，导出为 74.36–81.44 ms。

相对上一批，Rust 七场景中位耗时变化为 −4.9% 至 +2.3%；跨 Provider 列表基本持平，导出从 78.95 降至 77.26 ms。本轮 Python 导出也从 247.53 降至 231.07 ms，因此同轮加速比从 3.14× 变为 2.99×。前后版本未做同轮交错测量，历史差值不能区分代码变化和机器状态影响。7 个样本只描述本次测量，不声称统计显著性、整体应用加速比或所有路径均无回退。

## 验证与边界

完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 单元测试 15 passed、CLI 差分与边界 706 passed，npm 74 passed、Web E2E 13 passed。固定工具链 release 构建通过后才开始测量。

P2 仍在进行。损坏记录警告、刷新/缓存、极端输入及跨平台验收待完成。搜索、Collect、Ratatui 与发布安装性能留在后续阶段，pip/npm 继续使用 Python。

## 复现与原始数据

```bash
just build-rust

uv run python scripts/benchmark_cli.py --label python-source-p2-source-errors --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --output dist/benchmarks/python-source-p2-source-errors.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-source-errors --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --baseline dist/benchmarks/python-source-p2-source-errors.json \
  --output dist/benchmarks/rust-p2-source-errors.json
```

- Python：[原始 JSON](2026-09-24-python-source-p2-source-errors-standard.json) / [明细](2026-09-24-python-source-p2-source-errors-standard.md)。
- Rust：[原始 JSON](2026-09-24-rust-p2-source-errors-standard.json) / [明细](2026-09-24-rust-p2-source-errors-standard.md)。
