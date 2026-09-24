# Rust P2：SQLite Provider 接入后的六场景复测

本批接入 OpenCode 旧表 / V2 和 ZCode，功能证据见 [SQLite 差分验收](../rust-sqlite-parity.md)。性能评估保留原五个 Codex 场景，增加 P0 已有的 `list-sqlite`；没有修改 evaluator、fixture 或结果摘要。

## 测量条件

- 实现 checkout：`aec8b471ca9e4dc0a686ae0b0616145361621757`，四份报告测量时工作树均干净，使用同一个 Rust release 二进制。
- Python 生产源码仍与 `dca2d97` 一致；Python 源码、evaluator、fixture 和 `uv.lock` 的 hash 与[上一批报告](rust-p2-jsonl.md)相同。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0；固定 Rust 1.90.0，`cargo build --locked --release`。
- Python / fixture 的 SQLite 为 3.50.4，Rust 的 rusqlite 0.40.2 使用 bundled SQLite 3.53.2。这是两种实现的端到端比较，SQLite 场景的差异不能全部归因于语言。
- standard fixture：1001 个会话、503 个源文件、23,839,547 字节；列表分别选择 501 个 Codex 和 500 个 OpenCode V2 会话，大会话包含一条 8 Mi 字符正文。
- 每场景 1 次预热、7 次测量，每次启动新进程。构建与测试结束后依次运行 Python、Rust，再运行 Python、Rust。OS 页缓存未清空，不是冷磁盘测试。
- 两轮的六个场景均通过原比较器的输出等价性检查，每份报告均通过源文件 hash 不变检查。

## 两轮结果

首轮 Python 的启动样本为 188.63–425.92 ms，print 为 384.84–547.03 ms；Rust 导出样本为 76.84–161.55 ms。由于波动较大，保留该轮后重新配对测量。下表并列展示全部中位数，不合并样本或只保留较大的加速比。

| 场景 | 首轮 Python ms | 首轮 Rust ms | 首轮 Python/Rust | 第二轮 Python ms | 第二轮 Rust ms | 第二轮 Python/Rust |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 启动 / version | 218.65 | 4.73 | 46.19× | 161.35 | 4.67 | 34.57× |
| Codex 列表（501 个） | 387.34 | 47.82 | 8.10× | 242.49 | 46.19 | 5.25× |
| OpenCode V2 列表（500 个） | 249.30 | 9.61 | 25.94× | 148.94 | 9.15 | 16.28× |
| 大文件 head | 240.93 | 8.06 | 29.89× | 148.36 | 7.01 | 21.16× |
| 大正文 print | 474.70 | 45.73 | 10.38× | 244.65 | 44.44 | 5.51× |
| 大正文 JSON＋Markdown 导出 | 270.67 | 79.54 | 3.40× | 248.94 | 74.60 | 3.34× |

第二轮 SQLite 列表样本为 Python 147.33–152.60 ms、Rust 8.49–9.64 ms；Codex 导出为 Python 245.77–253.13 ms、Rust 73.93–75.88 ms。部分场景仍存在波动，例如 Python 列表为 229.75–310.23 ms。这里只报告描述统计，不声称统计显著性或应用整体加速比。

第二轮峰值 RSS 中位数如下；首轮各样本同样保留在原始报告中。

| 场景 | Python MiB | Rust MiB |
| --- | ---: | ---: |
| 启动 / version | 38.95 | 2.62 |
| Codex 列表 | 42.23 | 5.06 |
| OpenCode V2 列表 | 40.75 | 7.80 |
| 大文件 head | 39.19 | 4.08 |
| 大正文 print | 123.52 | 53.36 |
| JSON＋Markdown 导出 | 151.64 | 53.44 |

第二轮导出峰值 RSS 中位数低约 64.8%。二进制为 5,882,896 字节，相比上一批 3,945,168 字节增加 49.1%；本批引入了 bundled SQLite 与两个 Provider 的实现。这是未打包的 release 可执行文件大小，不能等同于安装包或下载体积。

与上一批相比，Rust Codex 列表中位数为 46.57 → 46.19 ms，print 为 43.63 → 44.44 ms，导出为 74.89 → 74.60 ms。没有据此认定优化或回退；轮次间噪声未被消除。

## 验证范围

完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 差分与边界 393 passed，npm 74 passed，网页 E2E 13 passed；固定工具链 release 构建成功。

新增性能场景仅代表 OpenCode V2 列表。旧表、ZCode、SQLite 正文导出和并发 WAL 性能尚未测量；WAL 的功能用例与原生 SQLite 协调文件边界记录在[差分验收](../rust-sqlite-parity.md)。其他 JSONL Provider 也没有新增性能工作负载。功能矩阵及跨平台验收仍未完成，pip/npm 继续发布 Python 实现。

## 复现与原始数据

```bash
just build-rust

uv run python scripts/benchmark_cli.py --label python-source-p2-sqlite --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --output dist/benchmarks/python-source-p2-sqlite.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p2-sqlite --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite \
  --case head-large-jsonl --case print-large-jsonl --case export-large-json-md \
  --baseline dist/benchmarks/python-source-p2-sqlite.json \
  --output dist/benchmarks/rust-p2-sqlite.json
```

第二轮保持参数与二进制不变，使用带 `-repeat` 的 label 和输出文件名，Rust 的 baseline 指向对应第二轮 Python 报告。

- 首轮 Python：[原始 JSON](2026-09-24-python-source-p2-sqlite-standard.json) / [明细](2026-09-24-python-source-p2-sqlite-standard.md)。
- 首轮 Rust：[原始 JSON](2026-09-24-rust-p2-sqlite-standard.json) / [明细](2026-09-24-rust-p2-sqlite-standard.md)。
- 第二轮 Python：[原始 JSON](2026-09-24-python-source-p2-sqlite-repeat-standard.json) / [明细](2026-09-24-python-source-p2-sqlite-repeat-standard.md)。
- 第二轮 Rust：[原始 JSON](2026-09-24-rust-p2-sqlite-repeat-standard.json) / [明细](2026-09-24-rust-p2-sqlite-repeat-standard.md)。
