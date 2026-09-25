# Rust 正文缓存验收

实现使用请求拥有的 `SessionDataCache`，单 URI 导出已接入。Provider 只声明变化来源，不拥有缓存策略。

| Python 行为依据 | Rust 行为与验证 |
| --- | --- |
| `tests/test_session_data.py` 的 bounded LRU | 默认保留 32 个无 lease 的已完成条目；零容量可用；活动读取和 lease 不被淘汰 |
| 并发 lease 合并 | 同 Provider/name 和 Session ID、同信号的读取共享一个结果；不同信号等待当前读取结束后重算信号 |
| 消费隔离与释放 | `Arc` 写时复制提供独立可变视图；最后一个临时 lease 释放 payload；100 个 256 KiB payload 的弱引用验证回收 |
| get 保留与 lease 临时语义 | get 将条目标记为保留；旧 generation 的 lease 释放不会删除更新后的条目 |
| 失败重试 | 失败不留缓存；共享错误保留 Provider 诊断类型和本地化；reader panic 清理条目并唤醒等待者 |
| Session 与源信号 | title、微秒 updated_at、去重路径的 mtime/ctime/size；缺失与恢复改变信号 |
| 十个 Provider change sources | Codex/Claude/Pi 单文件；Kimi 已存在的 context/wire；六个 SQLite 来源的 Session 数据库和 WAL，排除 SHM |
| WAL 失效 | 真实临时 SQLite WAL 更新后正文重读；主数据库字节未变；读取不改主库/WAL；checkpoint 后信号重新失效 |
| Cursor 当前配置与旧 Session | 配置改变本身不改变旧 Session 的变化源；旧源信号改变后重新读取当前配置；与 Python 当前契约一致 |

对应 Rust 验证在 `session_data/tests.rs`，Cursor 配置行为扩展现有读取边界测试。负容量在 Rust 用 `usize` 排除，不增加无效状态。

缓存信号在读取前取得。来源在读取过程中更新时，后续请求会观察新信号；SQLite 正文仍使用独立只读事务。文件内容的持续并发改写不承诺快照隔离，遵循 Python 的文件读取语义。

搜索索引 generation/旧请求竞态仍属于 P3。本记录不宣称索引缓存已经迁移。
