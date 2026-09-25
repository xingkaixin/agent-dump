# 架构与扩展指南

Rust CLI 位于根目录 `src/`，Cargo manifest 与工具链位于仓库根。`resources/` 保存编译时嵌入的文案与提示词；`tests/cli/` 用固定的外部 Python v0.15.9 验证兼容性。旧 Python 应用不再保存在主树中。稳定约束见 `AGENTS.md`，领域术语见 `CONTEXT.md`。

## 1. 公开契约与分发

公开契约是 `agent-dump` 命令的参数、默认路径、输出格式和退出码。pip、uv tool、uvx 安装 Maturin `bin` wheel；npm 平台包包含同一 wheel 中的原生可执行文件。没有 PyO3、Python 导入 API 或 Python 模块入口。旧 API 使用方可固定最后的 Python 版本 0.15.9。

`Cargo.toml` 是发布版本来源，npm 版本由脚本同步。目标平台闭集由 `npm/packages/cli/lib/native-targets.json` 拥有。安装、最低 libc 和发布控制见[发布指南](release-guide.md)。

## 2. 数据流与职责

```text
main.rs → cli_args.rs / shortcut.rs → command.rs
  ├─ list_workflow.rs → scanner.rs → query_filter.rs → search_index.rs
  ├─ interactive_workflow.rs → selector.rs / tui.rs → export.rs
  ├─ uri_workflow.rs → registry.rs / Provider → render.rs / export.rs
  ├─ maintenance.rs
  ├─ config_command.rs
  └─ collect_workflow.rs → collect_sessions.rs → collect_events.rs
       → collect_reduction.rs / collect_prompts.rs → llm.rs
```

`main.rs` 处理终端输出边界和错误退出；参数解析不读取 Provider 内容。`command.rs` 确定模式优先级、默认值和冲突，再交给工作流。Provider 条件在扫描前生效。`selector.rs` 和 `tui.rs` 只展示调用方传入的数据，不触发 discovery 或完整读取。Ratatui 用于真实终端；管道输入保留简单行交互。

`--collect --emit-prompt` 使用相同的会话筛选，由 `collect_handoff.rs` 生成任务说明，不进入内部 LLM 请求。生成的读取命令指向正在运行的原生可执行文件。

## 3. Provider 与 Session

`provider.rs` 的 `Provider` 是共享访问边界。`registry.rs` 拥有 Provider 顺序、名称、URI scheme、路径前缀及实例装配；Provider 模块拥有来源选择和私有 schema。

- `discover` 同时返回可用性、会话窗口和部分失败；`find` 是自包含直接定位入口。
- `read` 读取标准化正文。`session.rs` 的 Session facts 供列表、head、统计和筛选共用，未知计数始终保持未知。
- `source_root`、`search_roots`、`change_sources` 声明来源与失效范围。
- `json_payload`、`raw_export`、`supports_format` 投影 Provider 特有输出能力；共享工作流不解释 schema。
- 可恢复诊断经显式 `DiagnosticSink` 传递，Provider 不直接打印。部分失败保留健康会话，并向 Collect 传播遗漏事实。

OpenCode 在同一数据库中兼容旧表与 V2，同 ID 优先 V2，旧版独有会话保留；ZCode 使用旧 SQLite 读取器。正文按定位时记录的来源读取，不在来源消失时静默切换数据库。每次 SQLite 正文读取使用只读事务。

`session_data.rs` 统一拥有正文缓存。`get` 复用有界 LRU；批量 Search/Collect 用 `lease`，完成投影即释放。并发读取合并，消费者得到隔离数据。数据库与 WAL 都属于 change sources，SHM 协调文件不作为持久内容失效依据。缓存不得恢复已经过期或删除的正文。

## 4. 导出与文件边界

格式闭集和 `md` 别名在 `output_formats.rs`。`export.rs` 负责文件名、来源拒写、私有权限、临时文件、同步及原子替换。`private_files.rs` 共享目录和落盘语义。macOS 使用与 Python `os.fsync` 相同的同步级别；不会对每个导出文件额外执行 `F_FULLFSYNC`。

summary、print、JSON、Markdown 复用一次已读取内容。raw 独立于标准化正文读取；print 失败不阻止文件导出。批量导出先规划目标冲突，保留部分成功结果。源目录和目标符号链接拒写，异常清理临时文件。已存在的用户导出目录不会被擅自 chmod。

## 5. Query 与 Search

- `query.rs` 拥有旧查询语法、结构化字段、`agents://`、路径规范化和 home 展开。
- `-query` 与 URI 的 `q` 是一个字面短语；`--search` 是按空白拆分且必须全部命中的 distinct terms。
- `query_filter.rs` 保留匹配证据和读取失败事实；角色过滤直接从允许角色生成 snippet。
- `search_index.rs` 使用 SQLite FTS5，加速语义必须等价。tokenizer 不适用或索引失败时回退到进程内 matcher。
- 跨 Provider 先更新所有参与索引，再全局检索。正文解析在事务外进行；旧请求不能覆盖新观察，也不能恢复已删除行。

搜索语义变化时同步索引内容版本。Provider Project 不充当 Working Directory；路径查询只使用后者。

## 6. Collect

execute、dry-run、emit-prompt 共用配置安全校验和会话筛选。Collect 仅提取 user/assistant 可见文本，排除 tool、reasoning、system、plan 与 Provider 私有事件。没有可见对话的会话在 chunk 规划前忽略。

PM 摘要字段为 requests、decisions、outcomes，outcomes 不从工具轨迹推断成功。PM 仅在日期相同且明确的 Working Directory 相同时归并；未知目录和 INSIGHT 保持单会话归属。读取失败、摘要失败和 Provider 发现不完整分别记录，部分成功报告明确注明遗漏；索引回退成功不计作读取失败。

最终输入限制、结构校验、纠正重试、并发上限、超时和跨源重定向凭据边界由 Collect/LLM 模块持有，验证使用本地 HTTP fixture，不访问真实模型。

## 7. 扩展步骤

1. 新 Provider 实现 `Provider`，优先复用文件、SQLite、transcript 和 message assembly 模块。在 registry 声明身份和 URI。
2. 新格式修改 `output_formats.rs`、`export.rs` 及 Provider 能力；覆盖可观察输出和失败路径。
3. 新模式在 `cli_args.rs` 声明参数，在 `command.rs` 归一化和分发，再实现对应 workflow。
4. 增补隔离行为测试，并同步 README、recipes；领域事实边界变化时同步 `CONTEXT.md`。

现有 Provider 的数据范围见 README 与历史设计文档。DeepChat 不支持 SQLCipher/附件读取/Tape 恢复；Cherry 只读取当前分支及未删除会话；MiniMax 只读取支持的已迁移展示行。重写不会扩大 Provider 源写入权限，也不执行上游迁移。
