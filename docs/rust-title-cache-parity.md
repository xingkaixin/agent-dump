# P2：标题缓存恢复与诊断验收

本批对齐 Codex、Claude Code 标题索引读取失败后的继续发现、标题回退和中英文警告，并验证同一 Provider 实例在后续操作中重新加载索引。Python 生产源码、P0 evaluator 和 pip/npm 默认入口保持不变；P2 尚未完成。

## 行为与证据

| Python 契约 | Rust 归属 | 验证 |
| --- | --- | --- |
| 有相关会话 metadata 时才加载标题索引，打开或解析失败不终止发现 | `codex.rs`、`claude.rs` | 两种语言的列表、head、JSON/raw 导出；空目录、过期会话和无效 header 不触发索引警告 |
| Codex 每次发现/查找只加载一次全局索引；Claude 每次操作按项目缓存，包括空结果 | 各 Provider 的标题缓存 | CLI 两会话只警告一次；Rust 同实例测试覆盖 Claude 两项目隔离 |
| Claude 索引根必须为对象；缺少 `entries` 等同空数组，显式非数组则告警后回退 | `Claude::load_titles` | 根为数组、`entries` 为 null/对象、缺字段和空数组的中英文完整差分 |
| Claude 无效或空白 `sessionId` 按索引汇总数量；有效重复 ID 使用最后一条记录 | `Claude::load_titles` | 七个坏条目与有效条目混合，检查完整警告、标题空白归一化和多格式产物 |
| Claude 非空非字符串 summary 导致对应会话解析失败；空值回退消息标题 | `Claude::parse` | bool、int、float、list、dict 及五种空值，列表隔离坏会话，URI 返回对应退出码 |
| 下次发现/查找重新加载标题；已修复索引更新标题，删除索引恢复回退标题 | 各 Provider 的 `discover`、`find` | 两个 Rust 单元用例复用同一实例，检查修复/删除后的结果和不创建源文件 |

新增 `rust/tests/test_title_cache.py` 的 52 个 CLI 用例：44 个使用完整退出码、stdout/stderr 与产物差分；8 个覆盖目录替代索引、非法 JSON/UTF-8，比较完整 stdout、产物、退出码、警告次数和本地化前缀。后 8 个保留底层依赖错误原因差异，不计作完整 stderr 一致。测试均检查源数据 hash，使用临时合成数据，不读取真实用户目录。

列表 fixture 使用不同创建时间，避免 Python 并行发现中同时间戳会话的完成顺序影响比较；没有归一化输出顺序来掩盖差异。

## 实现边界

`Provider::discover`、`find` 与 `read` 显式接收同一诊断 sink 契约。Provider 发送结构化缓存失败或坏条目数量，工作流负责本地化、动态字段清理和 stderr 输出。缓存损坏不记为会话源失败；无效 summary 引起的单会话解析失败仍进入既有失败集合。

Codex 的未加载状态与已加载空缓存分开，首次有效 metadata 才读取索引。Claude 保留 summary 的原始 JSON 类型，只在会话解析时应用 Python 的空值与字符串规则。没有新增依赖、全局诊断状态或并发缓存框架。

Python 的 Codex/Claude `_extract_title(lines)` 是没有生产调用方的历史私有包装；当前 CLI 使用 `_extract_title_from_records`。本批不为未进入 CLI 的包装异常路径增加 Rust 入口。消息字段的极端输入和实际标题提取行为仍需逐项验收。

## 仍待完成

- Codex/Claude/Pi 单条记录转换恢复与已验证的警告类型在后续补齐，见[转换恢复验收](rust-message-conversion-parity.md)；其他极端消息/数值字段仍待验证。
- 全部 JSON、UTF-8、文件系统底层原因文本、异常类别及其他极端标题/消息字段。
- 长生命周期源目录重新定位、正文缓存、lease/LRU、并发读取合并与失效；本批仅验证标题索引在同一实例、相同路径下的刷新。
- 完整 CLI usage、全部参数组合及跨平台发布。搜索、配置、Collect、Ratatui 和 pip/npm Rust 发布切换仍在后续阶段。

## 本轮验证

标题缓存专项 52 passed。2026-09-24，macOS arm64，固定 Rust 1.90.0：完整 `just isok` 通过，Python 2596 passed / 1 skipped、Rust 单元测试 17 passed、CLI 差分与边界 784 passed、npm 74 passed、Web E2E 13 passed。`just build-rust` release 构建通过。

Python 生产源码与 `dca2d97` 相同，P0 evaluator 四个脚本相对 `9c1cf61` 无改动；没有新增依赖。

实现提交：`768e4ba`。[原七场景复测](benchmarks/rust-p2-title-cache.md)在干净 checkout 上通过结果比较和源 hash 校验；这些健康 Codex/OpenCode V2 场景不测 Claude、损坏索引或缓存刷新性能。
