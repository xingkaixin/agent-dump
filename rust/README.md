# Rust CLI（P2：共享发现与十个 Provider 的读取、导出）

此目录是 Rust 重写的实验实现，目前已接入全部十个 Provider 的发现、消息装配和支持格式的单 URI 导出。ZCode 路径沿用 macOS/Windows 限制。Python 仍是默认实现和发布来源；Rust 二进制尚不能替代完整的 `agent-dump`。迁移状态见[计划](../docs/rust-migration-plan.md)。

## 构建与验证

需要 rustup 和项目现有的 uv/just 环境，工具链固定为 Rust 1.90.0，依赖固定在 `Cargo.lock`。

```bash
just check-rust
just build-rust
./rust/target/release/agent-dump --help
```

`check-rust` 运行 fmt、Clippy、Rust 单元测试、debug 构建与 `rust/tests/`。差分套件通过子进程调用两种 CLI，只使用隔离的合成会话目录；比较完整 stdout/stderr、JSON 结构、Markdown 与 JSONL raw 字节、源数据 hash。SQLite raw 比较 JSON 结构；WAL 用例单独校验数据库与 WAL 持久数据，区分 SQLite 的 `-shm` 协调文件。URI 格式无效、会话不存在和 Provider 格式能力拒绝已做中英文完整输出差分；JSONL 坏行和旧 SQLite 坏记录警告也已做中英文完整差分；Codex/Claude 标题缓存的恢复、坏条目汇总和刷新已验证；Codex/Claude/Pi 的记录级恢复及已验证的转换警告已对齐；底层库错误文本与其他极端输入尚未全量验证。

## 已实现范围

```bash
./rust/target/release/agent-dump --list -d 36500
./rust/target/release/agent-dump --list -d 36500 -q provider:codex,opencode
./rust/target/release/agent-dump --list -d 36500 -q provider:codex
./rust/target/release/agent-dump codex://SESSION_ID --head
./rust/target/release/agent-dump codex://SESSION_ID --format print
./rust/target/release/agent-dump codex://SESSION_ID --format json,md,raw --output ./exports
./rust/target/release/agent-dump --list -d 36500 -q provider:claudecode
./rust/target/release/agent-dump claude://SESSION_ID --head
./rust/target/release/agent-dump kimi://SESSION_ID --format json,md,raw --output ./exports
./rust/target/release/agent-dump pi://SESSION_ID --format print
./rust/target/release/agent-dump --list -d 36500 -q provider:opencode
./rust/target/release/agent-dump opencode://SESSION_ID --format json,md,raw --output ./exports
./rust/target/release/agent-dump zcode://SESSION_ID --head
./rust/target/release/agent-dump cursor://REQUEST_ID --format json,print --output ./exports
./rust/target/release/agent-dump deepchat://SESSION_ID --format json,md --output ./exports
./rust/target/release/agent-dump cherry://topic-TOPIC_ID --head
./rust/target/release/agent-dump minimax://SESSION_ID --format print
```

- Codex `CODEX_HOME/sessions`、默认 home 和 `data/codex` 回退；索引标题、第二条 user 消息标题、目录与文件名回退。
- 日期窗口、注册顺序与 metadata summary；`--list` 发现全部 Provider，`-q provider:NAME[,NAME]` 在扫描前限定来源，支持大小写归一化、去重与 `claude` 别名。Provider 包括 `opencode`、`zcode`、`codex`、`kimi`、`claudecode`、`cursor`、`pi`、`deepchat`、`cherry`、`minimax`。
- `codex://ID`、`codex://threads/ID`；head 的已知/未知消息数量和有界首尾读取。
- text/reasoning、assistant 分组与相邻 part 去重、工具调用及输出回填、孤立输出、计划审批、token 汇总。
- Codex patch 解析、subagent prompt/昵称/通知、完整注入上下文识别；图片等非文本 part 和未知事件按当前 Python 规则忽略。patch 只解析和导出，不执行文件操作。
- JSON 专用 skill 转换和 wait_agent 过滤；Markdown/print 保留各自展示行为，混合导出共用读取结果且互不污染。
- Claude Code：`CLAUDE_CONFIG_DIR/projects` 与 `data/claudecode`，项目级标题索引、meta/TodoWrite 过滤、工具结果回填与 usage；只发现项目目录下的会话文件，不扫描嵌套 subagent 会话。
- Kimi：`KIMI_SHARE_DIR/sessions` 与 `data/kimi`，工作目录 hash 映射、metadata 标题/时间、context 优先与旧 wire 格式、分段工具参数、SetTodoList 过滤；raw 优先选择定位时记录的 context，否则选择当时记录的 wire；之后文件变化不静默切换 raw 来源。
- Pi：`PI_HOME/agent/sessions` 与 `data/pi`，文件后缀定位及 header ID 回退、session_info 标题、分支/压缩/custom 记录、图片字段、usage/cost。保留所有分支消息，工具结果保留为独立消息。
- OpenCode：显式 `OPENCODE_DB`（相对路径基于 OpenCode 数据目录，不存在时不回退）、XDG/default 与 local fallback；旧表和 V2 共存时优先 V2，按 `seq` 读取 V2 消息、保留工具状态与元数据，损坏正文明确失败。
- ZCode：macOS/Windows 的 `~/.zcode/cli/db/db.sqlite`；复用旧表消息/part、批量读取、费用与 token 汇总。两种 SQLite Provider 的 head 使用发现 facts，不解析完整正文。
- Cursor：global `state.vscdb`、requestId 定位与无 requestId 时的 composer 回退；按 rowid 读取 bubble、按消息时间稳定排序；保留工具挂接、plan 审批、model 继承、子会话输出与循环保护。发现计数按 100 个 composer 分批，正常 metadata 只读取各自前 20 个 bubble；坏 JSON 触发兼容回退。
- DeepChat：当前未加密 `agent.db`，排除草稿；优先结构化 user/assistant 表，缺少结构化行或表时回退 content；保留工具、附件引用、links、compaction 和内部事件。
- Cherry Studio：普通聊天的当前父链、虚拟根和空叶节点过滤，Agent 会话与 workspace；兼容软删除字段迁移前后 schema，保留消息模型快照、token、工具和内部事件。损坏聊天分支不阻止其他会话发现。
- MiniMax Code：columnar v3 与已迁移展示行，`MINIMAX_DATA_DIR` / `MAVIS_DATA_DIR` 的 trim、home 展开及默认路径；拒绝待迁移旧 blob，保留 ID 顺序、usage、附件引用及独立内部事件。
- Cursor 支持 JSON/print；DeepChat、Cherry Studio、MiniMax 支持 JSON/Markdown/print。包含不支持格式的组合整体拒绝，不产生部分导出。
- JSONL Provider 未设置环境变量时使用对应默认 home 路径；环境变量值按 Python 的字面路径语义处理。文件发现或查找时跳过单个读取失败的会话并告警，其他有效会话继续处理。
- print、JSON、Markdown（含 md 别名）、raw，格式去重与顺序；单个文件格式失败后继续其他格式，任一成功返回 0，全部失败返回 1。JSONL raw 直接复制源字节；OpenCode/ZCode raw 需要成功解码正文，输出单会话 `.raw.json`，不是数据库副本。
- 共享发现区分源不可用、时间窗口内无会话和部分失败；坏文件、坏数据库或 Provider 初始化异常不阻止其他来源。无可用来源输出中英文诊断和候选路径：无过滤时返回 1，显式 Provider 过滤时返回 0；部分可用返回 0，警告走 stderr。
- URI 无效/无匹配/格式能力拒绝使用结构化诊断；最终诊断走 stdout，查找失败警告走 stderr。`--head` 与 `--format` 冲突返回 1；head 允许 `--output` 且不写文件。无效格式列表返回 2，完整 argparse/Clap usage 文案仍未对齐。
- JSONL 坏行按扫描汇总，最多展示前五个行号，未完成的坏尾行不告警；旧 SQLite 坏消息/part 跳过后继续处理。警告走 stderr 并跟随 `--lang`，head/list 和 JSONL raw 不触发正文警告。
- Codex、Claude 仅在有效 metadata 需要标题时加载索引，加载失败告警后回退；同一操作内缓存空结果，下次操作重新加载。Claude 坏索引条目按项目汇总数量，非空非字符串 summary 保留为单会话解析失败。
- Codex、Claude、Pi 的单条记录转换失败告警后继续，保留已有消息与工具关联；Codex 不累计转换失败记录的 usage，Pi 保留有效 JSON 对象序号。具体已验收错误与 metadata 阶段差异见[转换恢复验收](../docs/rust-message-conversion-parity.md)。
- 已定位来源消失时保留 Provider 的路径证据和本地化恢复建议；OpenCode V2 会话或表消失时不读取旧表中的同 ID 副本。
- 文件名快速定位失败时回退到完整 metadata 扫描，同 ID 选择创建时间最新的会话；保留查找期间的逐文件失败。
- 中英文成功输出，终端控制字符清理，导出文件名身份保留与原子私有写入；拒绝写入 Provider 根目录及覆盖符号链接。
- `-days`、`-query`、`-format`、`-output`、`-v` 等本阶段参数别名。

文件导出必须显式指定 `--output`。URI 默认 `print`，输出文件位于 `<output>/<provider>/`，Claude Code 的目录名为 `claudecode`。文件名与 JSON 内容对齐，JSON 空白排版不作为契约。

## 尚未实现的行为

- 完整 Provider contract、批量交互导出、通用 Query/Search、统计、索引、Collect、摘要、配置、shortcut、Ratatui。
- 配置文件尚不读取；因此不应用保存的语言、默认目录等配置。帮助、错误文案、错误组合的退出码与全部工作流的部分失败策略未完成全量对齐；未支持的参数会报错。
- 本地验证只代表 macOS arm64。CI 增加 Linux/macOS 差分任务；Windows 行为和全部发布平台在后续阶段验证。

行为映射和待验收边界见 [Codex](../docs/rust-codex-parity.md)、[Claude Code / Kimi / Pi](../docs/rust-jsonl-parity.md)、[OpenCode / ZCode](../docs/rust-sqlite-parity.md)及 [Cursor / DeepChat / Cherry Studio / MiniMax](../docs/rust-desktop-parity.md) 差分验收记录。共享发现与跨 Provider 隔离见[验收记录](../docs/rust-discovery-parity.md)。URI 共用诊断见[验收记录](../docs/rust-uri-parity.md)。DeepChat / Cherry / MiniMax 的 schema、源缺失与迁移错误见[专属错误验收](../docs/rust-provider-errors-parity.md)。其余七个 Provider 的源缺失与 Kimi raw 文件身份见[源缺失验收](../docs/rust-source-parity.md)。JSONL/旧 SQLite 坏记录警告见[验收记录](../docs/rust-record-diagnostics-parity.md)。Codex/Claude 标题缓存恢复与刷新见[验收记录](../docs/rust-title-cache-parity.md)。Codex/Claude/Pi 消息转换恢复见[验收记录](../docs/rust-message-conversion-parity.md)。底层错误文案、其他刷新/缓存边界、极端输入和跨平台行为仍需后续验收；功能矩阵尚未完成。

## 模块归属

`main.rs` 解析参数并装配工作流，`list_workflow.rs` 管理 Provider 范围、发现、失败隔离及列表输出，`uri_workflow.rs` 管理单 URI 的读取与输出分发。`provider.rs` 的发现结果保存可用性、会话和逐源失败事实；完整性由失败集合是否为空确定，与警告输出独立。各 Provider 通过统一读取契约和 `registry.rs` 的静态注册表进入工作流；共享路径、文件发现与失败隔离位于 `file_sessions.rs`。各 Provider 模块解释自己的 metadata 与 transcript，Kimi wire 单独解析。SQLite 连接与行转换位于 `sqlite.rs`，路径/schema/发现位于 `sqlite_provider.rs`，旧表和 V2 正文分别由 `sqlite_legacy.rs`、`opencode_v2.rs` 解释。`desktop.rs` 装配 DeepChat / Cherry / MiniMax 的只读连接与标准化导出，各自模块拥有路径与 schema；Cursor 的存储/发现和正文展开分别在 `cursor.rs`、`cursor_transcript.rs`。`SessionData` 的扩展字段用于保留已有导出字段，renderer 不解释 Provider 私有事件。共享 JSONL 字节读取在 `jsonl.rs`，assistant 合并和工具结果回填在 `message_assembly.rs`。`session.rs` 保存稳定的会话/消息字段；其中 `source_metadata` 是只由所属 Provider 解释的发现快照。`render.rs` 负责会话展示，`diagnostics.rs` 统一列表与 URI 诊断结构、本地化及动态字段清理；`Lookup` 保存可选的定位结果和逐文件失败，工作流决定输出通道。`provider_error.rs` 保留 Provider 的本地化原因、恢复建议、证据及能力限制，逐源失败保存错误对象，展示层选择语言；URI 多格式输出保留原始读取错误。发现、查找和正文读取显式接收诊断 sink；Provider 发送结构化标题缓存、坏记录或转换失败事实，工作流选择警告输出流和语言；静默扫描使用空 sink。`export.rs` 负责文件身份、权限与原子写入。

直接依赖各有明确用途：Clap 解析参数，Serde/serde_json 处理契约与源记录，regex 识别完整上下文块，Jiff 处理时间与本地时区名称，WalkDir 递归发现，SHA-256 保持特殊 ID 的文件身份，MD5 对齐 Kimi 既有工作目录映射，rusqlite 的 bundled SQLite 负责只读数据库查询，tempfile 保证导出原子替换和异常清理。不调用 Python 作为 Rust 的运行时依赖。

## 性能评估

历史四场景对比见 [P1 性能复测](../docs/benchmarks/rust-p1.md)。[P2 Codex 复测](../docs/benchmarks/rust-p2-codex.md)增加现有的 JSON＋Markdown 导出场景，并保留缓冲优化前后的数据。

接入 Claude Code / Kimi / Pi 后的[复测](../docs/benchmarks/rust-p2-jsonl.md)仍使用同五个 Codex 场景，检查共享模块变化后的表现；不代表这三个 Provider 的性能。

接入 OpenCode / ZCode 后的[六场景复测](../docs/benchmarks/rust-p2-sqlite.md)增加 OpenCode V2 列表，保留两轮数据、SQLite 引擎版本差异和二进制体积变化；尚未测量 SQLite 正文导出或 ZCode 的性能。

接入其余四个 Provider 后的[六场景复测](../docs/benchmarks/rust-p2-desktop.md)仍使用这六个场景，记录共享消息/JSON 投影变化后的结果与历史差值；它不代表 Cursor、DeepChat、Cherry Studio、MiniMax 的性能。

共享发现后的[七场景复测](../docs/benchmarks/rust-p2-discovery.md)增加 `list-all`，覆盖 501 个 Codex 和 500 个 OpenCode 会话的跨 Provider 列表；其他八个来源在此 fixture 中不可用。

URI 诊断对齐后的[七场景复测](../docs/benchmarks/rust-p2-uri.md)沿用同一 fixture 和 evaluator，记录共享工作流调整后的表现；未测量失败诊断性能。

Provider 专属错误接入后的[七场景复测](../docs/benchmarks/rust-p2-provider-errors.md)继续使用原成功场景，记录共享错误传播调整后的表现；它不代表三个桌面 Provider 或失败路径的性能。

源缺失诊断接入后的[七场景复测](../docs/benchmarks/rust-p2-source-errors.md)记录共享 raw 错误传播调整后的表现；Kimi 和失败路径不在本轮性能测量范围内。

坏记录警告接入后的[七场景复测](../docs/benchmarks/rust-p2-record-warnings.md)记录显式诊断 sink 接入后的健康数据路径；不测警告和旧 SQLite 读取性能。

标题缓存恢复后的[最新七场景复测](../docs/benchmarks/rust-p2-title-cache.md)保留同轮 Python/Rust 数据；跨 Provider 列表为 4.97×，JSON＋Markdown 导出为 3.04×。这些健康 Codex/OpenCode V2 场景不测 Claude、损坏索引或缓存刷新性能。

使用原有 [CLI evaluator](../docs/benchmarks/README.md)，不为 Rust 改写 fixture 或验收摘要。本阶段只运行以下已实现子集：

```bash
just benchmark --command './rust/target/release/agent-dump' \
  --label rust-p2-title-cache --profile standard \
  --case startup-version --case list-jsonl --case list-sqlite --case list-all \
  --case head-large-jsonl --case print-large-jsonl \
  --case export-large-json-md \
  --output dist/benchmarks/rust-p2-title-cache.json
```

Python 用同样的 `--case` 组合重测；Rust 再传入该报告的 `--baseline` 做严格比较。当前共七个场景；不得解释为应用整体加速比。复杂工具消息由差分测试验证，benchmark 仍使用 P0 的固定文本工作负载。
