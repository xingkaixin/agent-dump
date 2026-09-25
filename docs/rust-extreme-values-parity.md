# Rust 极端值与 metadata 验收

本轮使用同一组合成来源，通过两份 CLI 比较 stdout/stderr、退出码、JSON 值、Markdown/raw 字节与源数据 manifest。

新增 `tests/cli/test_extreme_values.py` 覆盖以下契约：

- Codex、Claude、Kimi、Pi 的 token 超过 i64、负大整数、数字字符串、有限大浮点、下划线及 Unicode 十进制数字；累加不截断、不溢出中止。
- OpenCode 旧表/V2、Cursor、DeepChat、Cherry、MiniMax 的大 token 与非有限输入；MiniMax 继续只接受非负整数，不扩大接受类型。
- Python JSON 接受的 NaN/Infinity/-Infinity；消息保留，safe_int/safe_float 统计仍回退；浮点总和溢出保留 Python 的 Infinity，不丢后续消息。
- 工具参数中的非有限数值与同名字符串互不混淆；任意精度 JSON 数字不会先转成 f64。
- Python 容器字符串表示中的 C1、Unicode 分隔符、不可见格式、私用区、引号、反斜杠和非 BMP 字符。
- Codex/Claude/Pi 的非字符串 cwd/version；原始导出值与展示 facts 各自保留参考行为。
- 日期 year 1/year 9999、无效 year 0、非字符串和过大数值的回退；毫秒输出遵循 Python 的浮点 timestamp 转换和截断。

新增 `num-bigint` 用于溢出后的整数运算；普通 i64 累加保留直接路径。`serde_json` 开启 arbitrary_precision。非有限 JSON 的兼容处理集中在 `python_json.rs`，不让各 Provider 复制解析规则。此模块在内部使用规范化数值编码，输出恢复 Python 的非标准 JSON 拼写，字符串不参与替换。

`timestamp.rs` 用 UTC civil datetime 保留 Python 支持的完整公历范围。Jiff 的 Timestamp 为时区转换预留边界，不能直接表示 year 9999 最后 26 小时；仅在这一边界使用公历 400 年周期查询 IANA 远期循环规则。一般日期继续使用 Jiff 的实际时区转换。Session 毫秒、正文毫秒与缓存微秒信号共用时间实现。

本轮不改变 Python 生产源码、原始 benchmark 或默认发布入口。底层异常文案、SQLite BLOB 和生命周期闭环继续在 [P2 总验收](rust-p2-completion.md) 跟踪。

本机验证：新增 101 个 CLI 用例全部通过；完整 Rust CLI 差分套件 935 passed，Rust 单元测试 37 passed；fmt、Clippy、Ruff、ty 通过。最终全项目门禁与平台结果在 P2 总验收中汇总。
