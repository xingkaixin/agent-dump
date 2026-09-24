# Rust CLI（P2：JSONL Provider 与导出）

此目录是 Rust 重写的实验实现，目前覆盖 Codex、Claude Code、Kimi、Pi 的发现、消息装配和单 URI 导出。Python 仍是默认实现和发布来源；Rust 二进制尚不能替代完整的 `agent-dump`。迁移状态见[计划](../docs/rust-migration-plan.md)。

## 构建与验证

需要 rustup 和项目现有的 uv/just 环境，工具链固定为 Rust 1.90.0，依赖固定在 `Cargo.lock`。

```bash
just check-rust
just build-rust
./rust/target/release/agent-dump --help
```

`check-rust` 运行 fmt、Clippy、debug 构建与 `rust/tests/`。差分套件通过子进程调用两种 CLI，只使用隔离的合成会话目录；比较完整 stdout/stderr、JSON 结构、Markdown/raw 字节、源数据 hash。异常诊断文案暂未对齐，损坏行测试单独比较恢复后的 JSON 并检查警告。

## 已实现范围

```bash
./rust/target/release/agent-dump --list -d 36500 -q provider:codex
./rust/target/release/agent-dump codex://SESSION_ID --head
./rust/target/release/agent-dump codex://SESSION_ID --format print
./rust/target/release/agent-dump codex://SESSION_ID --format json,md,raw --output ./exports
./rust/target/release/agent-dump --list -d 36500 -q provider:claudecode
./rust/target/release/agent-dump claude://SESSION_ID --head
./rust/target/release/agent-dump kimi://SESSION_ID --format json,md,raw --output ./exports
./rust/target/release/agent-dump pi://SESSION_ID --format print
```

- Codex `CODEX_HOME/sessions`、默认 home 和 `data/codex` 回退；索引标题、第二条 user 消息标题、目录与文件名回退。
- 日期窗口、列表顺序与 metadata summary；当前要求显式指定一个 `-q provider:NAME`，支持 `codex`、`claudecode`、`kimi`、`pi`。
- `codex://ID`、`codex://threads/ID`；head 的已知/未知消息数量和有界首尾读取。
- text/reasoning、assistant 分组与相邻 part 去重、工具调用及输出回填、孤立输出、计划审批、token 汇总。
- Codex patch 解析、subagent prompt/昵称/通知、完整注入上下文识别；图片等非文本 part 和未知事件按当前 Python 规则忽略。patch 只解析和导出，不执行文件操作。
- JSON 专用 skill 转换和 wait_agent 过滤；Markdown/print 保留各自展示行为，混合导出共用读取结果且互不污染。
- Claude Code：`CLAUDE_CONFIG_DIR/projects` 与 `data/claudecode`，项目级标题索引、meta/TodoWrite 过滤、工具结果回填与 usage；只发现项目目录下的会话文件，不扫描嵌套 subagent 会话。
- Kimi：`KIMI_SHARE_DIR/sessions` 与 `data/kimi`，工作目录 hash 映射、metadata 标题/时间、context 优先与旧 wire 格式、分段工具参数、SetTodoList 过滤；raw 同样优先 context。
- Pi：`PI_HOME/agent/sessions` 与 `data/pi`，文件后缀定位及 header ID 回退、session_info 标题、分支/压缩/custom 记录、图片字段、usage/cost。保留所有分支消息，工具结果保留为独立消息。
- 各 Provider 未设置环境变量时使用对应默认 home 路径；环境变量值按 Python 的字面路径语义处理。发现或查找时跳过单个读取失败的会话并告警，其他有效会话继续处理。
- print、JSON、Markdown（含 md 别名）、raw，格式去重与顺序；单个文件格式失败后继续其他格式，任一成功返回 0，全部失败返回 1。raw 不依赖正文解码。
- 中英文成功输出，终端控制字符清理，导出文件名身份保留与原子私有写入；拒绝写入 Provider 根目录及覆盖符号链接。
- `-days`、`-query`、`-format`、`-output`、`-v` 等本阶段参数别名。

文件导出必须显式指定 `--output`。URI 默认 `print`，输出文件位于 `<output>/<provider>/`，Claude Code 的目录名为 `claudecode`。文件名与 JSON 内容对齐，JSON 空白排版不作为契约。

## 尚未实现的行为

- 其余 Provider、批量交互导出、通用 Query/Search、统计、索引、Collect、摘要、配置、shortcut、Ratatui。
- 配置文件尚不读取；因此不应用保存的语言、默认目录等配置。帮助、错误文案、错误组合的退出码与全部工作流的部分失败策略未完成全量对齐；未支持的参数会报错。
- 本地验证只代表 macOS arm64。CI 增加 Linux/macOS 差分任务；Windows 行为和全部发布平台在后续阶段验证。

行为映射和待验收边界见 [Codex 差分验收记录](../docs/rust-codex-parity.md)与[Claude Code / Kimi / Pi 差分验收记录](../docs/rust-jsonl-parity.md)。发现缓存刷新、诊断、极端输入和跨平台行为仍需后续验收；功能矩阵尚未完成。下一步迁移 OpenCode / ZCode SQLite Provider。

## 模块归属

`main.rs` 解析参数并装配工作流，`uri_workflow.rs` 管理单 URI 的读取与输出分发。四个实际 Provider 通过 `provider.rs` 的统一读取契约和 `registry.rs` 的静态注册表进入工作流；共享路径、文件发现与失败隔离位于 `file_sessions.rs`。各 Provider 模块解释自己的 metadata 与 transcript，Kimi wire 单独解析。共享 JSONL 字节读取在 `jsonl.rs`，assistant 合并和工具结果回填在 `message_assembly.rs`。`session.rs` 保存稳定的会话/消息字段，`render.rs` 负责展示，`export.rs` 负责文件身份、权限与原子写入。

直接依赖各有明确用途：Clap 解析参数，Serde/serde_json 处理契约与源记录，regex 识别完整上下文块，Jiff 处理时间与本地时区名称，WalkDir 递归发现，SHA-256 保持特殊 ID 的文件身份，MD5 对齐 Kimi 既有工作目录映射，tempfile 保证导出原子替换和异常清理。不调用 Python 作为 Rust 的运行时依赖。

## 性能评估

历史四场景对比见 [P1 性能复测](../docs/benchmarks/rust-p1.md)。[P2 Codex 复测](../docs/benchmarks/rust-p2-codex.md)增加现有的 JSON＋Markdown 导出场景，并保留缓冲优化前后的数据。

使用原有 [CLI evaluator](../docs/benchmarks/README.md)，不为 Rust 改写 fixture 或验收摘要。本阶段只运行以下已实现子集：

```bash
just benchmark --command './rust/target/release/agent-dump' \
  --label rust-p2-codex --profile standard \
  --case startup-version --case list-jsonl \
  --case head-large-jsonl --case print-large-jsonl \
  --case export-large-json-md \
  --output dist/benchmarks/rust-p2-codex.json
```

Python 用同样的 `--case` 组合重测；Rust 再传入该报告的 `--baseline` 做严格比较。不得把这五个性能场景解释为应用整体加速比；复杂工具消息由差分测试验证，本批 benchmark 仍使用 P0 的固定文本工作负载。
