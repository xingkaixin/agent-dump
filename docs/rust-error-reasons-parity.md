# Rust 底层错误原因验收

本轮把错误路径的检查从“失败且不写源数据”扩展为完整 CLI 差分。

- JSON 语法错误保留 Python 的原因、行列和 Unicode 字符位置；UTF-8 解码错误保留错误字节、位置及原因。语法诊断仅在主解析器失败时运行。
- Codex/Claude 标题索引指向目录时保留 errno、文件名与恢复行为；文件读取诊断统一由 `source_io.rs` 提供路径上下文。
- SQLite 的底层原因去掉 rusqlite 额外附带的 SQL 和 offset；区分 DatabaseError 与 OperationalError。
- OpenCode V2 坏 JSON/非对象/坏 content、DeepChat assistant content、Cherry 分支/消息和 MiniMax 字段错误保留 Python 原因，不叠加额外包装。
- 非法导出 ID 保留能力诊断、原 ID 的 Python repr、失败原因与下一步；PurePosixPath 的末尾 `.` 组件规则保持一致。
- 导出目标被目录或普通文件阻挡时，保留输出路径、错误类别和逐格式部分成功，失败后清理临时文件。差分仅规范化两次进程生成的随机临时文件名。

新增 `test_error_reasons.py` 56 个中英文 CLI 用例；桌面 Provider 原有失败 helper 改为比较完整输出和退出码。第一轮定位到的 DeepChat/Cherry 双重包装差异已经修复。

本记录不代替 [P2 总验收](rust-p2-completion.md) 的 SQLite BLOB、来源生命周期、跨平台与最终全项目门禁。
