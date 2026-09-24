# CLI 性能基线

这套评估用于比较当前 Python、PyInstaller 制品与未来 Rust release 二进制。它通过 CLI 子进程执行，不 import `agent_dump`，无需为 Rust 改写计时入口。

完整迁移验收见 [Rust 迁移计划](../rust-migration-plan.md)。这里的结果校验只保护 benchmark 工作负载，不能代替完整功能矩阵。

首份已归档结果：[2026-09-24 Python 基线](python-baseline.md)，包含源码运行与 PyInstaller 原生制品。

阶段复测：[Rust P1 四场景比较](rust-p1.md)，保留同期 Python 源码、PyInstaller 与 Rust 的原始样本；仅代表已实现子集。

[Rust P2 Codex 五场景比较](rust-p2-codex.md)增加 JSON＋Markdown 导出，保留缓冲优化前后的完整数据与同期 Python 测量。

[JSONL Provider 接入后的 Codex 复测](rust-p2-jsonl.md)验证共享模块变化后的五场景表现；三个新 Provider 的性能仍待独立测量。

[SQLite Provider 接入后的六场景复测](rust-p2-sqlite.md)增加原有 OpenCode V2 列表场景，保留两轮配对测量、波动说明及 SQLite 引擎版本差异。

[十个 Provider 接入后的六场景复测](rust-p2-desktop.md)记录共享消息与 JSON 投影调整后的表现；四个新增 Provider 的性能仍待独立测量。

[共享发现后的七场景复测](rust-p2-discovery.md)增加原有 `list-all` 场景，验证跨 Provider 列表；fixture 仍只有 Codex 与 OpenCode 数据。

[URI 诊断对齐后的七场景复测](rust-p2-uri.md)记录共享工作流调整后的成功路径表现；不把这些测量当作错误路径性能证据。

[Provider 专属错误接入后的七场景复测](rust-p2-provider-errors.md)验证共享错误传播调整后的成功路径，保留相同 fixture、evaluator 和原始样本。

[源缺失诊断接入后的七场景复测](rust-p2-source-errors.md)记录共享 raw 错误传播调整后的成功路径；Kimi 文件身份和源缺失行为由功能测试验证，不纳入本轮性能结论。

## 运行

```bash
# 快速检查工具和结果断言
uv run python scripts/benchmark_cli.py --profile smoke --repeats 1 --warmups 0 --output dist/benchmarks/smoke.json

# Python 源码运行基线：默认使用当前解释器 -m agent_dump
uv run python scripts/benchmark_cli.py --profile standard --output dist/benchmarks/python-source.json

# 当前 npm 实际分发的 PyInstaller 路径；构建结束后再测量
just build-native
uv run python scripts/benchmark_cli.py --command "$(pwd)/dist/agent-dump" --label python-native --output dist/benchmarks/python-native.json

# Rust 完成后：先保持相同 evaluator 与 fixture，在同机重新测一次 Python
uv run python scripts/benchmark_cli.py --command "/absolute/path/to/agent-dump" --label rust-release --baseline dist/benchmarks/python-source.json --output dist/benchmarks/rust-release.json

# 实施中只验证已完成路径，不形成全量性能结论
uv run python scripts/benchmark_cli.py --profile smoke --case startup-version --case head-large-jsonl --output dist/benchmarks/partial.json
```

`--command` 使用参数解析，不通过 shell 执行；可执行文件会在隔离前定位。命令中的脚本或制品路径应使用绝对路径。上例的 `$(pwd)` 由用户的 shell 展开。

默认每场景 1 次预热、7 次测量。每次为新进程；预热用于减少一次性加载噪声，不意味着复用应用内缓存。JSON 保存原始样本，旁边的 Markdown 展示 median/min/max 与峰值 RSS。

源码入口不计入 `uv`/`uvx` 启动器时间，原生入口不计入 Node/npm wrapper 时间。下载和安装也不在这些计时范围内；后续分发体验另行测量。

## 数据与场景

| Profile | Codex 普通会话 | OpenCode V2 会话 | 每普通会话消息数 | 每消息基础字符数 | 额外 Codex 大会话 |
| --- | ---: | ---: | ---: | ---: | --- |
| smoke | 8 | 8 | 4 | 128 | 2 条消息，其中 1 条为 64 Ki 字符 |
| standard | 500 | 500 | 20 | 256 | 2 条消息，其中 1 条为 8 Mi 字符 |
| large | 2,000 | 2,000 | 40 | 1,024 | 2 条消息，其中 1 条为 32 Mi 字符 |

字符数不等于 UTF-8 字节数；实际文件数、总字节数与内容 SHA-256 写入报告。内容含中英文、换行、确定性编号及稀疏搜索标记。会话时间固定为 2026-01-15，文件 mtime 固定；列表使用明确的大日期窗口，collect 使用固定日期范围。

17 个场景：

- `startup-version`、`startup-help`：新进程启动到命令完成。
- `list-jsonl`、`list-sqlite`、`list-all`、`stats-all`：分别发现与投影，检查会话集合/计数。
- `head-large-jsonl`、`print-large-jsonl`：区分轻量元数据与完整正文读取。
- `export-large-json-md`：同一大正文导出 JSON 与 Markdown；检查全部消息内容。
- `export-batch-jsonl`：通过现有非 TTY 多选输入 `all`，导出所有 Codex 会话，逐文件检查角色与完整正文。
- `reindex-empty`：每次空索引，包含正文提取和索引写入。
- `search-cold-index`：每次空索引，包含首次建索引及查询。
- `search-warm-index`、`search-cjk-warm`：每场景先在计时外建索引，随后测量更新检查与查询。
- `search-fallback-warm`：单字母 `q`，当前 Python 因 trigram 无法保持该语义而走字面匹配；未来实现只须语义等价，不限制索引算法。
- `collect-dry-run`：本地正文读取、可见对话提取及 chunk 规划，不发模型请求。
- `collect-emit-prompt`：会话清单与交接提示词生成，不把它当作正文处理性能。

## 测量边界与安全

- 全部源文件由 evaluator 生成；临时工作目录、HOME、Provider 路径、配置、索引、导出和临时文件都隔离。不继承用户 Provider 覆盖、API key 或 Python 配置。只对子进程设置环境，不修改当前 shell 环境。
- 在计时外创建 fixture、预建热索引、清理输出并校验结果。计时包含 CLI 启动、读取、计算、stdout/stderr 写入和导出写入；不测显示器或终端绘制。
- 每次冷索引样本都清空项目缓存。操作系统页缓存不清空，数据生成和校验也会影响页缓存，故这些数据不能标注为冷磁盘性能。
- collector 为每个样本启动独立进程，在其唯一 CLI 子进程退出后读取 `RUSAGE_CHILDREN`。Darwin 的 RSS 按字节、Linux 按 KiB 转成字节。RSS 是 OS 报告的子进程最大值，不是整个进程树同时驻留内存之和。Windows 暂只记录 wall time，不伪造内存值。
- stdout/stderr 写入文件，避免 evaluator 的字符串捕获或输出校验进入被测进程的 RSS。
- 所有样本都检查结果；运行结束重新计算所有 Provider 源文件 hash，变化则拒绝产出成功报告。非零退出、超时、重复样本结果变化也视为失败。
- JSON 中的 `executable_bytes` 是命令首个可执行文件大小。对 Python 源码运行它是解释器大小，不能当成 Python 包大小与 Rust 比较；只有对应原生制品之间可以直接比较该字段。

## 结果等价与比较

首次运行使用独立 fixture 断言验证会话集合、计数、导出文件和消息正文，并保存结果摘要。重复测量必须产生相同摘要。

`--baseline` 还要求报告 schema、fixture、数据 hash、evaluator hash、主要机器信息、场景集合与参数相同。每个场景的校验摘要一致后，才计算 `baseline wall median / current wall median`。JSON 导出比较完整 payload 摘要；集合场景只比较命中集合，不声称已验证排序、snippet 或排名。CLI help 只验证关键选项，不声称已验证全部参数。

handoff 验证 envelope 长度、会话身份、失败数量及读命令后，只规范化生成时间、临时根目录、命令前缀与派生的 shell 命令。完整提示词指令、实际执行读命令与结束标记属于后续功能 eval，不由本基准证明。

严格比较拒绝不同场景子集。需要比较实施中的子集时，两边都用相同的 `--case` 重新运行。修改 evaluator 或 fixture 后，两边都重新生成报告，不绕过兼容检查。

正式结论应在同机、接近的时间内交错运行 Python 与 Rust；避免同时构建、运行测试或执行其他重任务。历史报告用于保存迁移起点，不能消除机器负载和系统升级的影响。7 次样本只报告描述统计，不声称统计显著性。

## 当前覆盖缺口

- 两种代表性存储，不代表全部十个 Provider；没有复现 WAL、索引增量更新/删除、损坏文件和所有 schema 版本。
- 没有真实 LLM 请求、完整 collect execute、终端交互延迟、下载/安装耗时或压缩包大小。
- 大正文具有重复性，FTS 压缩与分词表现不代表所有真实会话；后续增加不同内容分布时升级 fixture 版本并重测两边。
- 子进程环境隔离是针对仓库当前 Provider 发现实现，不是操作系统沙箱。未来新增发现入口时必须同步更新隔离契约。

上述缺口在迁移阶段按需补齐，不影响当前基线作为明确范围内的比较依据。
