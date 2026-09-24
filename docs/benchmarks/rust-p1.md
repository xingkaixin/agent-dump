# Rust P1：首条路径的性能复测

P1 已打通 Codex 文本会话的列表、URI、head、print 和 JSON 导出。这里比较四个已实现的性能场景；完整 Provider、工具消息、搜索、Collect 和 Ratatui 仍未迁移，不能据此宣称重写完成或计算应用整体加速比。

- 性能测量 checkout：`b473f37d3019ce3861d68a3eadc279e3fbfde1e0`，测量时工作树干净。
- Python 生产源码仍与 P0 的 `dca2d97` 一致；PyInstaller 二进制 SHA-256 也与 P0 记录一致。
- macOS arm64，Apple M1 Pro，Darwin 27.0.0；Rust 1.90.0，`cargo build --locked --release`。
- 使用原有 evaluator 和 fixture v1，未修改任何 benchmark 脚本。standard 数据共 1001 个会话、503 个源文件、23,839,547 字节；本次列表仅选择 501 个 Codex 会话。
- 每场景 1 次预热、7 次测量，新进程执行；顺序为 Python 源码 → Rust → PyInstaller，构建和测试在测量前完成。OS 页缓存未清空。
- 每个样本均通过结果断言，源文件 hash 保持不变。三份报告通过同一比较器的兼容性与输出摘要检查。

## 耗时中位数

| 场景 | Python 源码 ms | PyInstaller ms | Rust ms | 源码/Rust | PyInstaller/Rust |
| --- | ---: | ---: | ---: | ---: | ---: |
| 启动 / version | 131.74 | 495.38 | 3.91 | 33.66× | 126.58× |
| Codex 列表（501 个） | 226.85 | 588.18 | 42.02 | 5.40× | 14.00× |
| 大文件 head | 133.13 | 480.61 | 6.06 | 21.98× | 79.33× |
| 大正文 print | 233.03 | 601.26 | 88.66 | 2.63× | 6.78× |

大正文场景包含一条 8 Mi 字符消息，读取、转换、输出写入都在计时内。head 只读取轻量 metadata，不能用它的加速比推断正文解析性能。启动开销的下降是当前结果的重要组成部分；七个样本仅提供描述统计。

## 峰值 RSS 中位数

| 场景 | Python 源码 MiB | PyInstaller MiB | Rust MiB |
| --- | ---: | ---: | ---: |
| 启动 / version | 38.73 | 45.53 | 2.31 |
| Codex 列表（501 个） | 42.12 | 47.86 | 4.08 |
| 大文件 head | 39.16 | 45.58 | 3.47 |
| 大正文 print | 123.28 | 130.02 | 63.14 |

被测 Rust release 可执行文件为 1,785,808 字节；现有 PyInstaller 制品为 13,828,560 字节。Rust 目前只包含 P1 子集，这不是最终功能等价制品的体积比较。源码报告的 executable_bytes 是 Python 解释器文件大小，不用于此比较。

## 验收与限制

- `just isok` 通过：2596 个 Python 测试通过、1 个跳过；53 个 Rust/Python 差分及边界用例通过；npm 74 个、网页 E2E 13 个通过；格式、类型检查和 Clippy 通过。
- 测量后，`c5053fd` 修复相对导出路径的回显并增加 1 个差分用例；`just check-rust` 再次通过，现为 54 个用例。该修复只影响 JSON 导出路径回显，不在本报告的四个计时场景中；原始报告保留实际被测 commit 和二进制 hash。
- 差分套件覆盖完整列表顺序与成功文案、中英文、UTC/上海/纽约时区、URI 别名、标题/路径回退、超长正文、reasoning 分组、JSON 结构、特殊 ID、损坏行、日期错误、权限与源数据保护。
- 未迁移的消息和命令明确报错。复杂 Codex schema、配置、完整错误文案/退出码、部分成功策略和其他平台仍属于待验收项。
- JSON 导出已做内容差分，但原有导出 benchmark 同时要求 Markdown；P1 不运行该场景，也不提供 JSON 导出性能结论。
- CI 已增加 Linux/macOS Rust job，本次只报告本机运行结果，未宣称远端 CI 或 Windows 验证通过。
- 启动 help 场景要求全量选项；P1 帮助明确显示实验范围，因此不将该场景列为通过。

## 复现与原始数据

先运行 `just build-rust`。对 Python 源码、Rust 和 PyInstaller 使用相同参数：

```bash
uv run python scripts/benchmark_cli.py --profile standard \
  --case startup-version --case list-jsonl \
  --case head-large-jsonl --case print-large-jsonl \
  --output dist/benchmarks/p1-python-source.json

uv run python scripts/benchmark_cli.py --command ./rust/target/release/agent-dump \
  --label rust-p1 --profile standard \
  --case startup-version --case list-jsonl \
  --case head-large-jsonl --case print-large-jsonl \
  --baseline dist/benchmarks/p1-python-source.json \
  --output dist/benchmarks/p1-rust.json
```

PyInstaller 使用相同场景，将 `--command` 替换为 `./dist/agent-dump` 并选择另一份输出路径。无需改写 evaluator 或筛掉失败样本。

- Python 源码：[原始 JSON](2026-09-24-python-source-p1-standard.json) / [明细](2026-09-24-python-source-p1-standard.md)。
- PyInstaller：[原始 JSON](2026-09-24-python-native-p1-standard.json) / [明细](2026-09-24-python-native-p1-standard.md)。
- Rust：[原始 JSON](2026-09-24-rust-p1-standard.json) / [明细](2026-09-24-rust-p1-standard.md)。

最终性能评估仍安排在功能矩阵全部完成之后，届时重新测量全部场景和正式分发制品。
