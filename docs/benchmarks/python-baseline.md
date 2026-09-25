# Rust 重写前的 Python 基线

记录日期：2026-09-24。迁移阶段 P0 已完成；Rust 尚未进入这些性能对比。

## 参考实现与测量条件

- 应用：`agent-dump 0.15.9`，生产源码与 `dca2d97` 一致。
- 评估工具：commit `a3d8f18`，Python 3.11.15，无新增第三方依赖。
- 原生制品：通过现有 `packaging/pyinstaller.spec` 构建，PyInstaller 6.22.3；13,828,560 字节（约 13.19 MiB）。构建没有发布任何包。
- 机器：Apple M1 Pro、arm64、10 个逻辑 CPU、32 GiB RAM、Darwin 27.0.0。
- 数据：501 个 Codex 会话（包含 1 个大正文会话）与 500 个 OpenCode V2 会话；20,002 条 user/assistant 消息；503 个源文件，共 23,839,547 字节。
- 每场景 1 次预热、7 次正式样本；全部启动新进程。构建、项目测试和两种入口的性能运行依次完成，没有相互并行。
- stdout/stderr 重定向到临时文件；未读取真实用户会话，未请求真实模型。源文件在运行前后哈希一致。

## 关键结果

下表为 wall time 中位数和每次运行峰值 RSS 的中位数。完整 17 个场景与 min/max、CPU 时间、原始样本见报告。

| 场景 | Python 源码 ms | PyInstaller ms | 源码 RSS MiB | PyInstaller RSS MiB |
| --- | ---: | ---: | ---: | ---: |
| 启动 / version | 150.54 | 495.06 | 38.86 | 45.47 |
| 全来源列表（1,001 会话） | 264.34 | 609.34 | 43.89 | 49.23 |
| 大正文 head | 144.35 | 496.82 | 39.19 | 45.80 |
| 大正文 print | 245.72 | 605.85 | 123.30 | 129.83 |
| 大正文 JSON + Markdown 导出 | 266.55 | 604.56 | 151.62 | 158.12 |
| 批量 JSON 导出（501 会话） | 938.58 | 1,189.75 | 144.12 | 149.59 |
| 空索引重建 | 2,928.99 | 3,366.96 | 313.58 | 321.44 |
| 首次搜索（空索引） | 3,167.90 | 3,566.76 | 313.61 | 319.20 |
| 已有索引搜索 | 556.11 | 923.36 | 220.09 | 224.72 |
| collect dry-run | 1,795.40 | 2,192.33 | 228.53 | 234.08 |
| collect emit-prompt | 263.99 | 637.47 | 48.55 | 53.33 |

这份基线分开保留了启动开销、完整正文处理、索引构建与查询的表现。后续 Rust 对比逐场景计算，不预设提速倍数。Python 源码入口不包含 uv/uvx 启动器，PyInstaller 入口不包含 Node/npm wrapper。

## 验证证据

- 17 个场景的所有预热和正式样本均通过结果断言。
- PyInstaller 通过 `--baseline` 与 Python 源码结果比较，全部校验摘要一致。
- `just isok`：Python 2,596 passed / 1 skipped；npm 74 passed；网页 E2E 13 passed；Ruff、Pyright、ty、锁文件检查和网页构建通过。
- 新增 7 项评估工具测试覆盖真实 CLI smoke、数据隔离和确定性、错误输出、非零退出、源文件修改、超时、漏会话与截断导出，以及不兼容报告比较。

## 已归档文件

- Python 源码：[汇总](2026-09-24-python-source-standard.md) / [原始 JSON](2026-09-24-python-source-standard.json)
- PyInstaller：[汇总](2026-09-24-python-native-standard.md) / [原始 JSON](2026-09-24-python-native-standard.json)
- [复测命令、测量边界及覆盖缺口](README.md)
- [迁移计划与完整功能验收矩阵](../rust-migration-plan.md)

这组数据只覆盖两种合成存储工作负载，不证明十个 Provider 或整个 CLI 已实现功能对齐。页缓存未清空，不能称为冷磁盘测试；RSS 不是同时运行的整个进程树内存总和。正式评价 Rust 时，需要在同机重新运行 Python 和 Rust，并单独完成完整功能矩阵验收。
