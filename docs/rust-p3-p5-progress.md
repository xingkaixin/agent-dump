# P3～P5 实施与验收跟踪

P2 已完成，最终提交 `74f6207` 的跨平台 CI 为 22/22 通过。
本轮在 `feat/rust-rewrite` 上继续；Python 参考实现、P0 历史评估器及 pip/npm 默认发布入口保持原样。

| 阶段 | 验收范围 | 状态 | 证据 |
| --- | --- | --- | --- |
| P3 | Query/Search、角色与路径、Unicode、全局排序、索引增量/删除/WAL/竞态、stats/providers/reindex | 核心实现已接入，扩展验收中 | `rust/tests/test_query_search.py`；索引并发单元测试；首轮 273 项相关 CLI 差分通过 |
| P4 | 配置与 shortcut、Collect 本地处理与缺口、两类 LLM 协议、URI summary | 已接入，边界与完整门禁验收中 | 本地 HTTP 差分、配置/shortcut/URI summary 测试 |
| P5 | Ratatui/Crossterm 选择、配置输入、非 TTY、取消与终端恢复 | 已接入，完整门禁验收中 | 非 TTY 批量导出差分；6 项真实 PTY；跨平台 TestBackend 绘制 |

完成要求：功能契约差分、源数据不变性、针对边界的测试、本地完整门禁、跨平台 CI、成对性能评估。
未验证的项目保持未完成，不以已有测试通过代替缺失能力。

P6 的安装制品矩阵、正式发布和默认切换不包含在本轮中。

P3 已验证：Unicode、字面操作符、角色与路径、URI 校验、跨 Provider 全局排序、坏索引回退、冷/暖缓存与正文刷新、Python/Rust 缓存互用、源数据不变性。索引单元测试覆盖并发新旧观察、读取期间删除、失败重试、部分发现窗口保留、过期清理和整批事务回滚。原 39 项 Rust 单元测试仍通过，新增 4 项索引边界测试。P3 的扩展 benchmark（增量更新/删除/WAL/更多 Provider）与最终跨平台验证尚未完成。

P4/P5 当前证据：基础 Collect 的 28 项差分通过；6 项并发与归并对照通过；96 项交互、模式分发和 PTY 测试通过。扩展 HTTP 边界、完整套件与 CI 仍在收口，最终报告将使用最终提交的完整结果。扩展评估器 `scripts/eval_rust_workflows.py` 的六个 smoke 场景（增量、删除、WAL、四 Provider、零延迟/20ms 模拟 HTTP）均完成结果等价校验；这些运行与开发检查并行，仅作为功能 smoke，不作为性能结论。
