# P2：存储输入与生命周期验收

本记录关闭剩余 SQLite JSON BLOB、Cherry boot-config 和读取事务边界。生产 Python 源码保持不变，来源均为临时合成文件。

## SQLite 输入类型

| 来源字段 | Python / Rust 行为 | 差分证据 |
| --- | --- | --- |
| OpenCode V2 `session_message.data` | JSON 字符串和 bytes；bytes 检测 UTF-8 BOM、UTF-16/32 BOM 和无 BOM 的大小端编码 | 八种编码的完整支持格式导出 |
| MiniMax `data_json` / `extra_data_json` | 同上；保留 JSON、字符编码、标量类型与非对象错误原因 | 两类字段分别比较导出和失败诊断 |
| Cursor KV value | bytes 只按 UTF-8 解码；BOM/UTF-16/32 不作为有效正文 | 八种编码的实际 CLI 差分 |
| DeepChat metadata | 只有字符串进入 JSON 解析；BLOB 按非对象处理，缺省统计 | 有效 JSON bytes 与非法 UTF-8 bytes |
| Cherry Agent message data | BLOB 不转 JSON，按无效消息拒绝 | 有效 JSON bytes 与非法 UTF-8 bytes，完整失败输出 |
| OpenCode 旧表 / ZCode message 与 part | 非 TEXT 记录跳过并发出原有警告 | 原坏记录差分套件持续验证 |

`sqlite::json_cell` 只解释原始 SQLite 单元格。行读取用 byte 数组保留 BLOB；只有接受 bytes 的 Provider 调用该解码入口。普通嵌套 JSON 数组不会经过此入口。`python_json::from_slice` 保持文件来源的严格 UTF-8 语义，`from_bytes` 单独实现数据库 JSON bytes 的编码检测；不引入新依赖。

新增 54 个 CLI 用例，覆盖以上字段和 JSON/UTF-8/UTF-16/UTF-32 截断、标量与非对象原因。该矩阵描述实际接受的字段，不将 SQLite 任意列的任意类型组合视为合法 schema。

## 配置与读取生命周期

Cherry 每次 discover/find 重新读取 boot-config。新增同实例 Rust 用例依次验证 default → first → second → 四类损坏 → 修复 → 删除配置回到 default。旧 Session 的正文读取继续使用发现时记录的数据库，即使当前 boot-config 损坏；源文件内容保持不变。

另在隔离 Python 进程用真实环境变量与临时配置核对同一序列。14 个自动 CLI 用例覆盖中英文 JSON、UTF-8、根对象及路径映射类型错误与修复后的导出。配置错误引发的候选路径诊断失败保留 Python 的 unexpected failure、退出码和输出通道，不吞掉原因。

SQLite 的只读事务新增真实 WAL 并发提交验证：第一次查询建立快照，writer 提交后同一个 reader 继续看到旧值；新 reader 看到新值；写操作被拒绝；读取期间数据库/WAL 字节不变。此前的 Provider WAL 用例与缓存 checkpoint 失效用例继续保留。SQLite 的 SHM 是原生协调文件，不承诺其字节不变。

单次文件读取期间持续改写文件、进程外更改符号链接或配置，不提供 Python 没有的跨文件原子快照。已验证定位后来源移走/替换、操作间配置变更、缓存加载中信号改变和 SQLite 事务快照；不以无法穷举的任意调度作为未完成的功能。索引 generation/旧请求竞争属于 P3。

本轮针对性 CLI 回归 219 passed，包含既有 URI/共享发现路径；Rust 单元测试新增 boot-config 与事务两个用例。最终平台和完整门禁结果集中记入 [P2 最终验收](rust-p2-completion.md)。
