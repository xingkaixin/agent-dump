# Rust P6 最终性能与制品报告

23 个场景全部通过结果等价和源数据不变性校验，本轮 Rust 耗时中位数全部低于 Python。P3～P5 的批量 JSON 导出回退已修复：最终配对测量为 Python 905.94 ms、Rust 367.69 ms，提速 2.46 倍。功能与安装验收见 [P6 最终验收](../rust-p6-completion.md)。

## 测量条件

- 干净 checkout：`a4fee7ba755762aaf6fc7719dc4b181646f145c0`。Python 生产源码仍与 `dca2d97` 一致，原 P0 evaluator 仍与 `9c1cf61` 一致。完整源码、evaluator、编排脚本、锁文件和二进制 hash 保存在原始报告中。
- 被测 Rust 文件直接取自本机构建的 Maturin wheel，已 strip，与本机 npm 安装测试使用的原生文件相同；不是 debug 构建。文件 9,456,112 字节，SHA-256 为 `2ac96ad6e4492b3d4ff48154f8c44c4f049193f37d41277a1bad15432c5faf8b`。
- Apple M1 Pro，10 个逻辑 CPU，macOS arm64 / Darwin 27.0.0；Rust 1.90.0，Python 3.11.15。Python/fixture SQLite 3.50.4，Rust bundled SQLite 3.53.2。结果包含引擎、库和并发策略差异。
- standard 基础输入：501 个 Codex、500 个 OpenCode V2 会话，503 个源文件、23,839,547 字节；普通会话 20 条消息，每条 256 字符，另含一条 8 Mi 字符大正文。
- 每场景 1 次预热、5 次正式测量。原 17 场景由 `scripts/eval_rust_release.py` 调用冻结的生成器、计时器与校验器，按轮交替 Python/Rust 顺序；扩展 6 场景也交替顺序。两个候选使用独立、相同的 fixture 与索引。
- 采样时本地构建与测试已经结束。每次启动独立 CLI 进程；数据生成、预建热索引、输出清理和结果验证不计时，CLI 读取、计算和实际写文件计时。OS 页缓存不清空，不能解释为冷磁盘性能。
- 下表 wall time 与 RSS 为中位数，加速比为 Python/Rust。原始 JSON 保留每次样本及 min/max、CPU、RSS。RSS 是 OS 报告的子进程峰值，不是整个进程树同时驻留内存之和。

## 原 17 个场景

| 场景 | Python ms | Rust ms | Python/Rust | Python RSS MiB | Rust RSS MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| 启动 / version | 141.53 | 5.09 | 27.79× | 38.73 | 3.41 |
| 启动 / help | 142.81 | 5.32 | 26.84× | 38.84 | 3.58 |
| Codex 列表 | 249.17 | 53.72 | 4.64× | 42.23 | 6.83 |
| OpenCode V2 列表 | 152.69 | 11.16 | 13.68× | 40.81 | 10.52 |
| 跨 Provider 列表 | 260.06 | 56.83 | 4.58× | 44.00 | 12.55 |
| 跨 Provider 统计 | 257.62 | 54.06 | 4.77× | 43.91 | 10.56 |
| 大文件 head | 146.52 | 7.92 | 18.51× | 39.27 | 4.98 |
| 大正文 print | 248.15 | 51.99 | 4.77× | 123.45 | 56.44 |
| 大正文 JSON＋Markdown 导出 | 261.99 | 76.51 | 3.42× | 151.55 | 56.02 |
| 批量 JSON 导出 | 905.94 | 367.69 | 2.46× | 143.98 | 48.77 |
| 重建空索引 | 2966.14 | 1061.51 | 2.79× | 313.55 | 115.27 |
| 冷索引搜索 | 3283.86 | 1271.93 | 2.58× | 313.81 | 144.06 |
| 暖索引搜索 | 545.76 | 306.96 | 1.78× | 221.19 | 113.97 |
| 暖索引中文搜索 | 553.03 | 316.97 | 1.74× | 232.50 | 116.61 |
| 暖索引字面回退 | 422.62 | 137.14 | 3.08× | 186.28 | 80.45 |
| Collect dry-run | 1890.63 | 313.19 | 6.04× | 229.00 | 106.03 |
| Collect emit-prompt | 271.88 | 66.02 | 4.12× | 48.58 | 12.64 |

## 扩展 6 个场景

| 场景 | Python ms | Rust ms | Python/Rust | Python RSS MiB | Rust RSS MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| JSONL 增量更新后搜索 | 459.77 | 141.09 | 3.26× | 186.41 | 80.83 |
| 删除后搜索 | 518.90 | 298.92 | 1.74× | 218.25 | 111.14 |
| SQLite WAL 更新后搜索 | 1524.07 | 481.97 | 3.16× | 55.25 | 21.27 |
| 四 Provider 搜索 | 742.61 | 381.31 | 1.95× | 223.31 | 117.80 |
| Collect 本机 HTTP / 0 ms | 284.60 | 68.72 | 4.14× | 43.78 | 13.14 |
| Collect 本机 HTTP / 20 ms | 514.95 | 289.20 | 1.78× | 43.66 | 13.22 |

增量用例修改 32 个 JSONL 会话；删除用例移除 32 个匹配会话；WAL 用例保持主数据库字节不变，更新留在 WAL。准备索引和修改数据不计时，随后 CLI 的更新和搜索计时。四 Provider 用例增加 500 个 Claude 和 500 个 Pi，总计 2,001 个会话；它不等于四种来源各自的独立基准。

Collect 选取 16 个 Codex 会话，每轮 33 个请求。两种实现的请求数、提示词 hash 和报告 hash 一致。模拟延迟使加速比从 4.14× 缩小到 1.78×；请求存在并发，不能用 33 乘 20 ms 推算总耗时。没有测量真实模型推理和输出质量。

## 批量导出回退的定位与修复

P3～P5 报告的 Rust 批量导出为 3,643.98 ms。P6 在相同工作负载上隔离文件同步调用：修改前中位数 3,657.62 ms，改为与 Python 相同的 `fsync` 后为 330.00 ms。探索阶段的完整数据分别保存在[修改前](2026-09-25-rust-p6-batch-before.json)和[同步调用对齐后](2026-09-25-rust-p6-batch-fsync.json)，它们记录开发中的工作树，不冒充最终制品测量。

Rust 1.90 的 Apple `File::sync_all` 使用 `F_FULLFSYNC`，Python 的 `os.fsync` 使用 `fsync`。501 个导出文件逐个触发更强的同步，造成主要等待。最终实现仅在 Apple 平台通过 `nix::unistd::fsync` 对齐 Python，其他平台继续 `sync_all`。临时文件、私有权限、同步错误传播与原子替换保持不变；复杂度仍为 O(文件数＋输出字节数)。

最终 wheel 制品的五次批量样本为 355.15–381.96 ms，Python 为 879.89–924.94 ms；中位数 367.69 / 905.94 ms。以这组同期交错结果为最终比较，不把探索阶段的 330 ms 与其他时刻的 Python 数字拼接。Rust 用户/系统 CPU 中位数为 117.35 / 232.93 ms，Python 为 593.93 / 348.68 ms。

## 制品大小

下表使用[四目标安装 CI](https://github.com/xingkaixin/agent-dump/actions/runs/36078392209)的构建报告，与[已发布 Python v0.15.9](https://github.com/xingkaixin/agent-dump/releases/tag/v0.15.9)的 PyInstaller 原生文件比较。大小均为字节；原生文件与其所在 wheel 的可执行文件逐字节一致。

| 目标 | Python 原生文件 | Rust 原生文件 | 变化 | Rust wheel |
| --- | ---: | ---: | ---: | ---: |
| darwin-arm64 | 14,017,184 | 9,131,984 | −34.9% | 4,412,534 |
| darwin-x64 | 13,965,232 | 9,541,240 | −31.7% | 4,605,704 |
| linux-x64 | 16,541,376 | 10,375,696 | −37.3% | 4,729,398 |
| win32-x64 | 15,068,768 | 10,604,032 | −29.6% | 4,682,098 |

旧 Python wheel 为 238,984 字节，不包含解释器与依赖；新 wheel 包含完整原生 CLI，因此 wheel 压缩包变大，不能宣称所有安装包都缩小。Python 解释器、依赖及缓存的总安装体积未测量。发布使用的 Linux sdist 为 262,734 字节。

CI macOS arm64 原生文件与本机被测文件大小、hash 不同，构建主机和 SDK 不同；未声称跨主机可复现字节。原始[制品报告](2026-09-25-rust-p6-artifacts.json)分别保留 CI 四目标和本机测量制品的大小与 SHA-256。

## 复现与证据

```bash
just build
# macOS arm64 示例；其他主机改为自己的 native 目标目录
uv run python scripts/eval_rust_release.py \
  --rust-command "$PWD/dist/native/darwin-arm64/agent-dump" \
  --profile standard --repeats 5 --warmups 1 \
  --output dist/benchmarks/rust-p6-standard.json
uv run python scripts/eval_rust_workflows.py \
  --rust-command "$PWD/dist/native/darwin-arm64/agent-dump" \
  --profile standard --repeats 5 --warmups 1 \
  --output dist/benchmarks/rust-p6-workflows.json
```

- Python 原 17 场景：[JSON](2026-09-25-rust-p6-standard-python.json) / [明细](2026-09-25-rust-p6-standard-python.md)。
- Rust 原 17 场景：[JSON](2026-09-25-rust-p6-standard.json) / [明细](2026-09-25-rust-p6-standard.md)。
- 扩展 6 场景配对：[JSON](2026-09-25-rust-p6-workflows.json) / [明细](2026-09-25-rust-p6-workflows.md)。
- 同步调用实验：[修改前明细](2026-09-25-rust-p6-batch-before.md) / [修改后明细](2026-09-25-rust-p6-batch-fsync.md)。

5 次样本只用于描述本轮测量，不声称统计显著性或整个应用的统一加速倍数。原 17 场景的 RSS 中位数下降 48.5%～91.2%。未测量 Ratatui 交互延迟、下载/安装耗时、真实网络和模型，以及其余六个 Provider 的独立性能。功能完整性由独立差分与边界套件验证。
