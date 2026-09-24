# P2 最终验收

状态：进行中。本文集中跟踪 P2 收尾，不把历史分批报告中的开放项自动视为完成。

Python 参考仍为 `dca2d97`，P0 evaluator 为 `9c1cf61`。所有来源均为临时合成数据，Python 生产入口保持不变。

## 收尾清单

- [x] 正文缓存：LRU、lease、并发读取合并、消费隔离、失败重试、source/title/time/WAL 失效、Cursor 当前配置和旧 Session 的关系。
- [x] 大整数与非标准 JSON 数值、Unicode 表示、日期边界、非字符串 cwd/version，见 [极端值验收](rust-extreme-values-parity.md)。
- [ ] 剩余结构/错误输入：SQLite BLOB 与 Provider 错误原因。
- [ ] 诊断：支持的 Provider/URI/导出路径的底层原因、异常类别、非法导出 ID 和文件系统失败。
- [ ] 来源生命周期：操作间变化、boot-config 编辑/损坏/恢复，读取事务与 WAL/checkpoint 行为。
- [ ] 跨平台：macOS、Linux、Windows 上运行 P2 差分和边界用例，记录真实结果。
- [ ] 行为映射与历史开放项复核；明确 P3–P6 的原定范围。
- [ ] 完整 `just isok`、release 构建、干净版本原七场景配对 benchmark。
- [ ] 更新迁移计划和 Rust README，合理拆分提交并提交最终状态报告。

P3 查询/索引/维护，P4 配置/shortcut/Collect/summary，P5 Ratatui，P6 完整安装/分发/发布切换，保持原计划边界。P2 的跨平台运行验证不代替 P6 的各平台安装与制品验收。
