# P3～P5 最终验收

状态：P3～P5 实现与本地验收完成。阶段交付要求 [PR #396 当前检查](https://github.com/xingkaixin/agent-dump/pull/396/checks)全部通过；三平台通过记录与随后修复见下。实现位于 `feat/rust-rewrite`，审阅入口为 [Draft PR #396](https://github.com/xingkaixin/agent-dump/pull/396)。Python 参考版本仍为 `dca2d97`；原 P0 evaluator 仍为 `9c1cf61`。

## 阶段范围

| 阶段 | 已交付行为 | 主要验收入口 |
| --- | --- | --- |
| P3 | 字面短语/AND terms、角色/路径/Provider/global limit、agents URI、Unicode/snippet/排序、索引与逻辑扫描回退、stats/providers/reindex | `test_query_search.py`、`search_index/tests.rs`；四个扩展索引 benchmark |
| P4 | TOML 配置、shortcut、日期与模式分发、Collect planning/dry-run/emit-prompt、PM/Insight 分块归并、OpenAI/Anthropic、URI summary、日志与缺口报告 | `test_config_shortcuts.py`、`test_command_routing.py`、`test_collect.py`、`test_collect_reduction.py`、`test_llm_transport.py`；两种模拟 HTTP 延迟 |
| P5 | Ratatui Provider 选择、会话分组多选、配置与密码输入、非 TTY 编号输入、批量导出、取消与恢复 | `test_interactive.py`、`test_tui.py`；Rust TestBackend 绘制 |

测试通过子进程运行真实 Python/Rust CLI，所有 Provider 数据、配置、索引、日志和导出均位于临时合成目录。结构化结果比较字段与值，Markdown/raw 比较内容；动态临时路径和可执行入口单独归一化。终端画面按 Ratatui 的行为契约验证，不要求与 questionary 逐字节相同。

## P3：查询、索引和维护

- 保留 legacy scoped query、结构化字段、字面短语与 AND terms 的区别。覆盖中英文、大小写、字面正则字符、角色和工作目录筛选、跨 Provider 全局排序与 limit。
- SQLite FTS5 使用兼容的 schema、内容版本与来源签名；验证 Python/Rust 缓存互用、健康缓存复用、正文变化后的更新，以及坏索引/无法表达查询时回退逻辑 transcript。
- 索引写事务前有界读取正文；保护旧请求覆盖新观察、读取期间删除、失败重试、部分发现保留、过期清理及整批回滚。
- 扩展评估在实际 CLI 上验证增量 JSONL、删除、未 checkpoint 的 SQLite WAL，以及 Codex/OpenCode/Claude/Pi 四来源的结果集合和源数据不变性。

## P4：Collect、配置和自动化入口

- 配置保留注释、未知字段与键值格式，支持平台换行及旧 Windows 路径修复；查看与确认遮蔽密钥，写入采用私有权限和原子替换。取消或解析失败不覆盖原配置。
- shortcut 保留引号、位置参数、日期变量与错误诊断；命令分发覆盖模式优先级、互斥、忽略参数告警、输出通道和退出码。
- Collect 只处理可见 user/assistant 内容，保留事件预算、分块、去重、日期/项目归属、PM/Insight 和逐会话失败事实；有界并发保留结果顺序，压缩失败保留原事实。
- 确定性本机 HTTP 服务比较 OpenAI/Anthropic 请求、提示词与输出；覆盖暂时错误重试、结构修正、超时、大小限制、无效 JSON/UTF-8、重定向、跨源凭据移除、URI summary 及结构化日志。工作线程日志写入失败不阻塞 Collect。
- `--emit-prompt` 生成 metadata manifest、上下文数量与可执行命令，不调用模型或写报告。`--dry-run` 保留本地计划与统计。

## P5：终端与批量导出

- UI 只接收工作流投影，不解释 Provider schema，不在绘制阶段扫描或读取正文。批量导出与 URI 导出共用路径与写入策略；目标冲突整体排除，其他有效文件继续执行。
- TTY 支持方向键、Home/End/Page、空格、全选/反选、回车、q/Q/Esc/Ctrl+C；文本输入支持中文、粘贴、编辑、默认值、确认与密码遮蔽。
- 真实 PTY 验证窄窗口与 resize、选择导出、取消配置保持文件、密码不可见、stdout 重定向时的密码输入及正常/取消退出后的终端属性恢复。重定向密码测试另连续复测 8 次。
- TestBackend 在 1×1、12×4、24×8、80×24 验证绘制与选择可见性，三平台执行；POSIX PTY 边界在 macOS/Linux 执行。

## 验证结果

本机完整 `just isok` 通过：Python 2,596 passed / 1 skipped，Rust 44 个单元测试、1,539 个 CLI 差分/边界用例，npm 74 个测试，Web E2E 13 个测试；fmt、Clippy、Ruff、pyright、ty 和 release 构建通过。

完整门禁对应 `88688ed`。随后 `b15f079` 修正 Windows 提示词 checkout 换行和 Collect 工作目录投影：资源文件固定 LF，提示词/manifest/归并统一使用 Session 的本机路径事实；相关 179 项 CLI 回归、44 个 Rust 单元测试、fmt/Clippy 和 release 构建通过。没有放宽差分断言；既有请求测试增加带空白、`.` 和重复分隔符的路径。

实现提交 `b15f079` 的[三平台 CI](https://github.com/xingkaixin/agent-dump/actions/runs/36031269957)运行同一套完整契约。22 项检查全部成功。CLI 平台明细如下；44 项 Rust 单元测试、fmt 和 Clippy 均在三平台通过。

| 平台 | 通过 | 条件跳过 | 套件总数 |
| --- | ---: | ---: | ---: |
| macOS | 1,539 | 0 | 1,539 |
| Linux | 1,533 | 6 | 1,539 |
| Windows | 1,523 | 16 | 1,539 |

macOS/Linux 的 7 项真实 PTY 均执行，Windows 用 TestBackend 验证可移植绘制。

随后的 CI 重跑发现首帧后立即 resize 可能早于 Crossterm 注册信号处理器。TTY 现在先初始化事件读取，再绘制首帧；不引入周期重绘。并发测试同时改用显式双请求栅栏，替代依赖 20 ms 调度窗口的睡眠，保留峰值并发必须为 2 的断言。7 项 PTY 和 6 项归并/并发用例连续执行 5 轮，共 65 项通过；44 项 Rust 单元测试、fmt/Clippy、Ruff、pyright/ty 和 release 构建通过。修复后的最终三平台门禁由上述当前 PR 检查提供。

Windows 的条件跳过包括：7 项 POSIX PTY、2 项 POSIX 源权限、1 项私有目录权限、1 项需要授权的符号链接、2 项 Python 不应用 `TZ` 的用例、2 项非法控制字符文件名和 1 项纯空白目录。Linux 只排除 6 项 Python ZCode 默认路径不支持的条件；其余 Provider、查询、配置、Collect 与导出契约均执行。

性能在干净的 `b15f079` 上使用 release 二进制测量，原 17 场景及新增 6 场景均通过等价性和源数据不变性校验。完整方法、耗时、RSS、二进制大小与原始样本见[性能复测](benchmarks/rust-p3-p5.md)。其中批量 JSON 导出为明确回退：Python 0.81 秒、Rust 3.64 秒；其他 22 个场景更快。此回退单独列入 P6 性能工作，不据此抹去功能验收，也不把 benchmark 通过当成完整功能证明。

## 已知差异与后续边界

- Clap 与 argparse 的帮助排版及参数解析器 usage 文案仍有差异，P6 最终 CLI 兼容性审查继续记录；业务模式分发、输出与退出码已按上述契约验证。
- Ratatui 使用自己的画面布局。终端验证覆盖交互行为、文本安全和恢复，不将 ANSI 帧当作 Python 输出兼容承诺。
- Rust 拒绝把索引、导出、Collect 报告或日志写入所选 Provider 源目录，延续仓库只读约束。SQLite `-shm` 原生协调文件与数据库/WAL 持久数据分开判断。
- 本机 HTTP 只验证客户端协议和重试；没有使用真实模型验证模型质量或线上延迟。性能结果不外推为所有 Provider、所有机器或整个应用的统一加速倍数。
- P6 仍需完整发布架构、Linux libc 基线、wheel/npm 安装矩阵、最终兼容审查、版本与默认实现切换。三平台测试不能替代安装制品验证。

Python 继续作为默认实现及 pip/npm 发布来源；未合并、未发布。本阶段交付不代表 P6 已完成。
