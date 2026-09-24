# P2：同实例来源选择与重试验收

本批对齐固定配置路径下，Codex、Claude Code、Kimi、Pi、OpenCode、ZCode 在同一 Provider 实例内的来源选择行为。Python 生产源码、P0 evaluator 和 pip/npm 默认入口保持不变；P2 尚未完成。

Python 的规则不是每次操作都重新选择最优来源：尚未找到任何来源时，下次发现或查找重试；一旦选中路径，即使它没有会话，也保持该选择。后来出现的高优先级来源不会取代已选 fallback。

## 行为与证据

| Python 契约 | Rust 归属 | 验证 |
| --- | --- | --- |
| 构造实例时不固定来源，首次发现/查找选择首个存在的候选 | `SourceRoots`、`SqliteProvider::ensure_database` | 先构造实例，再创建 primary/fallback；分别以 discover/find 作为首个操作 |
| 所有来源缺失时不缓存不存在的路径，下次操作可发现后来出现的来源 | 同上 | 首次无来源，随后创建两个来源，选择 primary；原 Rust 文件来源会固定不存在的 fallback，SQLite 会永久保留 None |
| 空目录与空数据库也会固定来源，稍后新增内容仍从原来源读取 | 同上 | 初始 primary、fallback、二者同时存在；随后写入同 ID 会话，检查实际源路径 |
| 已选来源被移走时不切换到另一个现存候选；恢复后可继续使用原实例 | 各 Provider 发现/查找 | 移走并恢复已选目录/数据库，检查结果、错误及未重新创建源路径 |
| Claude 已选根目录缺失或不是目录时失败；其他三个文件 Provider 对缺失根返回不可用 | `Claude::files`、`SourceRoots::files` | 同实例目录移走测试；根为普通文件时增加两种语言的 CLI 边界用例 |
| 导出保护目录跟随实际选择，SQLite 选中后更新数据库父目录 | `SourceRoots::owned`、SQLite root | 每次状态变化检查 `source_root()`；其余源目录写入保护继续由既有 CLI 用例覆盖 |

新增 5 个 Rust 单元用例，四个文件 Provider 各一个，SQLite 一个覆盖 OpenCode/ZCode。每个 Provider 执行四种初始状态（全缺失、primary、fallback、两者均存在）× 两种首次入口（discover/find），合计 48 组状态序列。使用临时文件和临时 SQLite，候选路径显式注入，不修改进程环境或工作目录，不访问真实用户会话。

ZCode 测试注入两个候选来检查共享 SQLite 选择契约；实际 ZCode 配置仍只有原有主路径，本批没有新增 fallback 配置。

本轮另用隔离的 Python 参考实例核验同样的 48 组状态序列。候选根通过 `get_search_roots` 边界注入，HOME 和 Provider 环境变量指向临时目录。此项是本轮参考核验，不计入 Rust 自动测试或完整 CLI 差分总数。

新增 2 个 CLI 边界用例比较根为普通文件时的完整 stdout、退出码、警告次数与源 hash；OS 错误原因及异常类别不逐字比较。CLI 套件增加至 834 个，Rust 单元测试增加至 22 个。

## 实现边界

文件 Provider 的 `base` 使用 `Option<PathBuf>` 表达尚未选中来源，不用 fallback 路径冒充已解析结果。`SourceRoots` 持有候选路径，在列举文件前选择；`find` 先取得当前文件集，再使用已选根作路径约束。导出保护目录由选择结果派生，不保留第二份可变 owned 路径。

SQLite 同样只在 database 为 None 时检查候选路径，选中后保持来源身份。现有 Session 的完整读取仍使用 Session 记录的文件或数据库；不会因为重新发现而改写旧 Session 的来源。

Claude 在目录扫描入口保留目录访问失败，其余文件 Provider 继续遵循各自的空结果规则。标题缓存和 Kimi 工作目录映射仍按操作刷新，本批没有增加正文缓存、后台监控或新依赖。

## 仍待完成

- 运行期间修改环境变量后的候选路径和 Codex 全局标题索引选择；Rust 目前在 open 时读取配置路径，本批只验收配置固定时的来源出现、消失与恢复。
- Cursor、DeepChat、Cherry、MiniMax 的长生命周期路径选择；本批不声明十个 Provider 的全部刷新行为完成。
- 全部底层文件/SQLite 错误原因和异常类别、权限变化、竞争时序、符号链接变化。
- 正文缓存、lease/LRU、并发失效、极端消息/数值输入和跨平台验证。搜索、配置、Collect、Ratatui 与 pip/npm Rust 发布仍在后续阶段。

## 本轮验证

相关 CLI 回归 210 passed；新增根路径异常用例 2 passed。最终完整 `just isok` 通过：Python 2596 passed / 1 skipped，Rust 单元测试 22 passed、CLI 差分与边界 834 passed，npm 74 passed、Web E2E 13 passed；格式、Clippy 和类型检查通过。

固定 Rust 1.90.0 的 `cargo build --locked --release` 通过。Python 生产源码与 `dca2d97`、四个 evaluator 文件与 P0 `9c1cf61` 一致。测试和参考核验均使用临时合成来源。

实现提交：`3e599a9`。[原七场景复测](benchmarks/rust-p2-source-selection.md)全部通过；测量时两轮均为同一干净 checkout，源码、evaluator、fixture 与上一批 hash 一致。跨 Provider 列表为 5.02×、JSON＋Markdown 导出为 3.25×，仅描述本轮健康数据上的独立 CLI 进程，不测同实例来源选择、刷新或失败恢复性能。
