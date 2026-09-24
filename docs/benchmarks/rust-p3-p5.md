# Rust P3～P5 性能复测

原 P0 evaluator 的 17 个场景和新增 6 个场景全部通过结果等价校验。原场景中 16 个更快、批量 JSON 导出更慢；新增 6 个场景均更快。功能与平台证据见[P3～P5 最终验收](../rust-p3-p5-completion.md)。

## 测量条件

- 实现 checkout：`b15f079f2e5e777aaf81a2d36e313863c39e5681`；三份原始报告均记录干净工作树，二进制身份由下文 SHA-256 固定。后续只修复 TTY 事件初始化和测试同步，本轮非 TTY 工作负载没有重跑；P6 将再次测量最终 release。
- Python 生产源码仍与 `dca2d97` 一致，P0 evaluator 仍与 `9c1cf61` 一致；Python、原 evaluator、`uv.lock` 和基础 fixture 的 hash 与 P2 最终报告相同。新增脚本为 `scripts/eval_rust_workflows.py`，单独记录 hash。
- macOS arm64 / Apple M1 Pro / Darwin 27.0.0；Rust 1.90.0 release，Python 3.11.15。Python/fixture SQLite 3.50.4、Rust bundled SQLite 3.53.2，结果包含引擎和并发策略差异。
- standard 基础输入：501 个 Codex、500 个 OpenCode V2 会话，503 个源文件、23,839,547 字节；普通会话 20 条消息、每条 256 字符，另含一条 8 Mi 字符大正文。
- 每场景 1 次预热、5 次正式测量，每个样本为独立 CLI 进程。本地测试与构建结束后采样；原 17 场景先 Python、后 Rust，新增 6 场景按轮交替 Python/Rust 顺序。OS 页缓存未清空。
- 数据生成与结果校验位于计时外；CLI 启动、读取、计算和实际写文件位于计时内。临时环境隔离所有 Provider、配置、缓存与导出；每轮校验源文件不变。
- 表中耗时和峰值 RSS 均为样本中位数；加速比为两者中位数之比。全部 min/max、CPU、RSS 和逐次样本保留在原始 JSON，不合成为整体应用加速倍数。

## 原 17 个场景

| 场景 | Python ms | Rust ms | Python/Rust | Python RSS MiB | Rust RSS MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| 启动 / version | 129.66 | 4.57 | 28.40× | 38.58 | 3.08 |
| 启动 / help | 127.50 | 4.46 | 28.56× | 38.59 | 3.20 |
| Codex 列表 | 224.00 | 50.31 | 4.45× | 42.25 | 6.70 |
| OpenCode V2 列表 | 130.51 | 9.84 | 13.27× | 40.56 | 10.59 |
| 跨 Provider 列表 | 232.32 | 52.17 | 4.45× | 43.95 | 12.36 |
| 跨 Provider 统计 | 245.19 | 52.85 | 4.64× | 43.77 | 10.36 |
| 大文件 head | 131.83 | 8.07 | 16.34× | 39.11 | 4.81 |
| 大正文 print | 225.34 | 50.33 | 4.48× | 123.19 | 54.30 |
| 大正文 JSON＋Markdown 导出 | 237.28 | 86.40 | 2.75× | 151.31 | 54.62 |
| 批量 JSON 导出 | 809.42 | 3643.98 | 0.22× | 143.95 | 47.72 |
| 重建空索引 | 2827.45 | 923.28 | 3.06× | 313.56 | 114.73 |
| 冷索引搜索 | 3074.35 | 1160.20 | 2.65× | 313.23 | 142.81 |
| 暖索引搜索 | 520.15 | 291.44 | 1.78× | 220.39 | 113.53 |
| 暖索引中文搜索 | 526.68 | 302.37 | 1.74× | 232.97 | 115.22 |
| 暖索引字面回退 | 399.00 | 126.41 | 3.16× | 187.31 | 80.17 |
| Collect dry-run | 1738.54 | 295.90 | 5.88× | 228.91 | 105.91 |
| Collect emit-prompt | 252.13 | 62.09 | 4.06× | 48.33 | 12.31 |

## 新增 6 个场景

| 场景 | Python ms | Rust ms | Python/Rust | Python RSS MiB | Rust RSS MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| JSONL 增量更新后搜索 | 421.13 | 136.98 | 3.07× | 188.05 | 80.80 |
| 删除后搜索 | 478.96 | 283.37 | 1.69× | 219.36 | 110.50 |
| SQLite WAL 更新后搜索 | 1454.28 | 460.48 | 3.16× | 55.27 | 20.94 |
| 四 Provider 搜索 | 708.07 | 359.20 | 1.97× | 224.53 | 116.64 |
| Collect 本机 HTTP / 0 ms | 259.85 | 73.14 | 3.55× | 43.62 | 12.69 |
| Collect 本机 HTTP / 20 ms | 554.38 | 339.73 | 1.63× | 43.61 | 12.92 |

- 增量：预建索引后修改 32 个 JSONL 会话，返回 32 个命中；删除：移除 32 个匹配会话后返回 19 个；WAL：持有写连接、关闭自动 checkpoint，主数据库字节不变而 32 条消息更新进入 WAL。准备索引和修改 fixture 均不计时，随后的 CLI 更新/搜索计时。
- 四 Provider：在基础数据上增加 500 个 Claude 和 500 个 Pi，会话总数 2,001，搜索结果 1,101 个。新增两类来源的消息较短，不能把此行视作四种 Provider 的独立性能比较。
- Collect：选取 16 个 Codex 会话，每轮产生 33 个请求；请求数、提示词 hash、报告 hash 在两种实现之间一致。0 ms 和每请求 20 ms 使用相同本机确定性服务，包含完整客户端处理和等待。33 次请求并非全程串行，不能直接用请求数乘延迟推算总耗时。
- 模拟延迟把 Collect 加速比从 3.55× 缩小到 1.63×。真实模型推理、网络分布和输出质量未测量；此结果不代表线上端到端响应时间。

## 回退、内存与体积

批量 JSON 导出是本轮明确的性能回退：Python 809.42 ms，Rust 3,643.98 ms，耗时为 Python 的 4.50 倍。Rust 五个样本范围为 3,195.08–3,846.14 ms，Python 为 793.05–834.47 ms；不能按单次噪声忽略。功能、文件数量与内容仍通过原比较器。

该场景的 Rust 用户 CPU 中位数为 254.76 ms，系统 CPU 为 633.23 ms；Python 为 542.91 / 306.23 ms。本文记录回退，不对尚未剖析的等待与写入成本作确定归因；批量导出性能列为 P6 复测和优化项。

原 17 个场景的 Rust RSS 中位数均低于 Python，下降 48.5%～92.0%。这只是同一合成输入的进程峰值，不等同整机总内存或常驻服务指标。

release 可执行文件为 10,988,832 字节（10.48 MiB），较 P2 的 6,541,232 字节增加 68.0%。此值为未打包二进制，不能与 Python 解释器文件大小直接比较包体积。SHA-256：`a22f478faf0e5b2a4cbc249b8925f97923012986f35db91349812a1131362135`。

5 次样本只提供本轮描述统计，不声称统计显著性。基础 17 场景按实现分块采样，存在时序偏差；新增场景交替顺序，但也不能消除全部系统噪声。本轮不测 Ratatui 响应、实际安装耗时、真实模型，以及其余六个 Provider 的独立性能。

## 复现

```bash
just build-rust
uv run python scripts/benchmark_cli.py --profile standard --repeats 5 --warmups 1 \
  --label python-p3-p5-reference --output dist/benchmarks/python-p3-p5-standard.json
uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --profile standard --repeats 5 --warmups 1 --label rust-p3-p5 \
  --baseline dist/benchmarks/python-p3-p5-standard.json \
  --output dist/benchmarks/rust-p3-p5-standard.json
uv run python scripts/eval_rust_workflows.py --rust-command "$PWD/rust/target/release/agent-dump" \
  --profile standard --repeats 5 --warmups 1 \
  --output dist/benchmarks/rust-p3-p5-workflows.json
```

- Python 原 17 场景：[JSON](2026-09-25-python-p3-p5-standard.json) / [明细](2026-09-25-python-p3-p5-standard.md)。
- Rust 原 17 场景：[JSON](2026-09-25-rust-p3-p5-standard.json) / [明细](2026-09-25-rust-p3-p5-standard.md)。
- 新增 6 场景配对：[JSON](2026-09-25-rust-p3-p5-workflows.json) / [明细](2026-09-25-rust-p3-p5-workflows.md)。
