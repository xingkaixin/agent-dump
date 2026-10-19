# 架构与扩展指南

根目录是 Cargo workspace 和 CLI package：`src/` 负责命令与交互，`crates/agent-dump-core/src/` 负责可独立于终端调用的读取、查询和导出。依赖只从 CLI 指向 core；core 的具体 Provider 模块为 crate 内可见。`resources/` 保存编译时嵌入的文案与提示词。项目目标、非目标和设计原则见[项目定位](product.md)，稳定约束见 `AGENTS.md`，领域术语见 `CONTEXT.md`，测试与验证见[开发指南](development-guide.md)。

## 1. 公开契约与分发

公开契约是 `agent-dump` 命令的参数、默认路径、输出格式和退出码。pip、uv 安装的 wheel 与 npm 平台包分发同一原生可执行文件，没有 PyO3、Python 导入 API 或 Python 模块入口。内部 `agent-dump-core` 固定为 `0.0.0` 且 `publish = false`，不独立发版。版本来源、目标平台和发布控制见[发布指南](release-guide.md)。

## 2. 数据流与职责

```text
agent-dump (root CLI package)
  src/main.rs → cli_args.rs / shortcut.rs → command.rs
    ├─ workflows/{list,interactive,uri,read,browse,machine,maintenance,config,collect}.rs
    ├─ terminal/{selector,tui,reader}.rs
    └─ collect/{sessions,events,reduction,prompts,llm,...}.rs
              ↓
agent-dump-core (internal library)
  providers/  → contract, registry, provider families
  session/    → facts, message assembly, cache, timestamp
  query/      → parser, scanner, filter, text, index, transcript
  output/     → formats, rendering, export, diagnostics, i18n
  storage/    → source I/O and private output files
  compat/     → frozen Python JSON/value semantics
  parallel.rs → bounded ordered worker pool
  config.rs
```

`main.rs` 处理终端输出边界和错误退出；参数解析不读取 Provider 内容。`command.rs` 确定模式优先级、默认值和冲突，再交给工作流。Provider 条件在扫描前生效。`terminal/` 只展示调用方传入的数据，不触发 discovery 或完整读取。

`compat/` 已冻结：只为保留既有可观察输出而存在，不再扩展，新代码不依赖它。

下面的 Provider、Session、Query 和输出路径均相对 `crates/agent-dump-core/src/`；CLI 路径相对根 `src/`。

## 3. Provider 与 Session

`providers/contract.rs` 的 `Provider` 是共享访问边界。`providers/registry.rs` 拥有 Provider 顺序、名称、URI scheme、路径前缀及实例装配；Provider 模块拥有来源选择和私有 schema。

- `discover` 返回可用性、会话窗口和部分失败。`Window::Created` 按创建时间裁剪；`Window::Updated` 不按创建时间裁剪；`Window::All` 发现全部会话元数据。会话和诊断按来源文件顺序产生，不受并行读取影响。`find` 是自包含的直接定位入口。
- 在 `Window::Updated` 下，文件型 Provider 可跳过修改时间早于窗口的来源文件，前提是 `updated_at` 取自该文件；`updated_at` 取自其他文件的 Provider（如 Kimi-Code 的 wire.jsonl）不剪枝。
- `read` 读取标准化正文。`session/mod.rs` 的 Session facts 供列表、head、统计和筛选共用，未知计数始终保持未知。
- `source_root`、`search_roots`、`change_sources` 声明来源与失效范围。`select_source` 只做来源选择，不发现会话、不打开数据库。registry 的 `inside_source` 用它检查所有 Provider 的来源根；导出、collect 报告与日志、搜索索引写入前都经过该检查。
- `json_payload`、`raw_export`、`supports_format` 投影 Provider 特有输出能力；共享工作流不解释 schema。
- 可恢复诊断经显式 `DiagnosticSink` 传递，Provider 不直接打印。部分失败保留健康会话，并向 Collect 传播遗漏事实。

正文按定位时记录的来源读取，来源消失时不静默切换数据库。SQLite 正文读取使用只读事务；数据库文件被替换后不复用旧连接。OpenCode 新旧表的合并规则见 [providers/opencode-v2.md](providers/opencode-v2.md)。

`session/cache.rs` 统一拥有正文缓存。常驻缓存同时限制会话数和字节数；批量 Search、Collect、批量导出和 `--search --locate` 使用 `lease`，用完即释放。并发读取合并，消费者得到隔离数据。数据库与 WAL 属于 change sources，SHM 协调文件不作为失效依据。缓存不得恢复已经过期或删除的正文。

Codex 与 Claude 的连续 assistant 片段由 `session/assembly.rs` 合并。合并边界、相邻重复片段消除及 Codex 计划审批位置保持既有语义。

## 4. Query 与 Search

- `query/mod.rs` 拥有旧查询语法、结构化字段、`agents://`、路径规范化和 home 展开。
- `-query`、URI 的 `q` 与 `--search` 使用同一匹配语义：按空白拆分且必须全部命中的 distinct terms。`--search` 额外按相关度排序并输出证据；`--read --match` 仍是单消息字面短语。
- `query/filter.rs` 保留匹配证据和读取失败事实；角色过滤只从允许的角色生成 snippet。
- `query/index.rs` 使用 SQLite FTS5，加速语义必须与进程内 matcher 等价。tokenizer 不适用或索引失败时回退到进程内 matcher。命中片段统一由 Rust 证据窗口生成，不调用 FTS5 `snippet()`。
- 路径范围内没有候选时直接返回空结果，不打开或更新索引。非空查询先更新所有参与索引，BM25 按全局索引评分，结果只返回范围内会话。change sources 变化后重新读取受影响会话；未变化索引上的重复搜索不发起写入。旧请求不能覆盖新观察，也不能恢复已删除行。

搜索语义变化时同步索引内容版本。Provider Project 不充当 Working Directory；路径查询只使用后者。

### 活动时间筛选

`Query.time_field` 默认 Updated，`--time-field created` 改为 Created；scanner 的时间字段由调用方显式传入。Updated 以 `Window::Updated` 发现，再按 Session.updated_at 应用日期窗口；Created 由 Provider 发现按创建时间裁剪。不用扩大天数的近似值冒充完整发现。普通活动列表先按更新时间排序再截断；Terms 搜索保留相关性优先。渲染和 selector 用同一 TimeField 投影日期分组，不改写 Session facts。collect、stats 和 reindex 不接受该选项；stats 固定按创建时间开窗。

## 5. 读取与消息定位

### 分段读取与读取提示词

`--read` 由 `workflows/uri.rs` 通过 Provider find/read 定位和读取单个会话。core 的 `query/read.rs` 基于标准化 SessionData 提供文本视图、角色和字面短语筛选、消息分页及长消息字符续读。`output/render.rs` 拥有文本展示，CLI 的 `workflows/read.rs` 输出机器信封和读取提示词。

游标是版本化的自包含编码，记录 URI、正文 revision、筛选、顺序、预算和位置；续读只接受游标，不另行覆盖选择条件。revision 与消息 locator 来自 `query/context.rs`。正文变化时拒绝旧游标；不持久化历史正文，也不新增索引。每次调用都执行完整 Provider read。可恢复来源诊断标记 partial；分页、视图省略和字符分段不代表源读取失败。

`--read-prompt` 只经 registry 校验 URI 语法，输出本地化静态说明与命令清单，不打开 Provider、发现会话或读取正文。命令使用当前原生程序路径，shell 参数引用与 collect handoff 共用 `command.rs` 的命令构造。

### 消息定位

`query/context.rs` 基于标准化 SessionData 生成消息定位符并校验上下文范围。`--search --locate` 按现有搜索语义定位命中消息，无 `--locate` 时保持原搜索输出。`workflows/uri.rs` 通过 Provider read 校验正文快照并输出消息范围；正文变化拒绝旧定位符，读取失败保留筛选失败事实。`--message --format json,markdown` 在定位校验后复用 core output 的片段渲染与安全导出，保留 URI、定位符和原始消息范围；可恢复来源诊断标记 partial。

## 6. 导出与文件边界

格式闭集和 `md` 别名在 `output/formats.rs`。`output/export.rs` 负责文件名、来源拒写、私有权限、临时文件、同步及原子替换。`storage/private_files.rs` 共享目录和落盘语义。

summary、print、JSON、Markdown 复用一次已读取内容。raw 独立于标准化正文读取；print 失败不阻止文件导出。批量导出先规划目标冲突，再并行读取和写出，进度与诊断按选择顺序输出；保留部分成功结果。源目录和目标符号链接拒写，异常时清理临时文件。已存在的用户导出目录不会被擅自 chmod。

## 7. Collect

execute、dry-run、emit-prompt 共用配置安全校验和候选会话筛选，候选发现不按创建日期截断。`--emit-prompt` 由 `collect/handoff.rs` 生成任务说明，不发起内部 LLM 请求；生成的读取命令指向正在运行的原生可执行文件。

- 日期归属：core transcript 的 visible_segments 投影标准化文本段及可靠时间；Collect 按文本段的本地日期筛选并逐日分块。无时间或 Provider 标记为推测时间的内容不属于任何日期，直接排除，不记录覆盖缺口。外部汇总通过 read 的 text_spans 使用同一日期事实。
- 外部汇总清单：读取候选正文并按相同日期投影筛选，但不规划 chunk；只交接含本期活动的唯一会话，并携带读取失败来源。
- 计数与 limit：会话计数是唯一 URI 数，跨日单元分别摘要；查询先选候选，按文本日期过滤后再对唯一会话应用 limit。
- 内容范围：只提取 user/assistant 可见文本，排除 tool、reasoning、system、plan 与 Provider 私有事件。没有可见对话的会话在 chunk 规划前忽略。
- 分块与归并：候选正文并行读取，结果、诊断和进度按候选顺序处理。全部符合筛选规则的正文进入有界事件块，超长消息按 Unicode 字符拆分，不设置会话总字符截断。会话摘要逐层归并；最终报告超过单次输入限制时按来源组拆分请求，单个过大归属组明确失败。

PM 摘要字段为 requests、decisions、outcomes，outcomes 不从工具轨迹推断成功。PM 仅在日期相同且明确的 Working Directory 相同时归并；未知目录和 INSIGHT 保持单会话归属。读取失败、摘要失败和 Provider 发现不完整分别记录，部分成功报告列出遗漏会话 URI；索引回退成功不计作读取失败。

最终输入限制、结构校验、纠正重试、并发上限、超时和跨源重定向凭据边界由 Collect/LLM 模块持有，验证使用本地 HTTP fixture，不访问真实模型。

## 8. 会话阅读器

`workflows/browse.rs` 拥有 `--browse` 的发现、筛选、按需读取和导出；`terminal/reader.rs` 只接收行数据和已读取的 SessionData，处理键盘与展示，不调用 Provider。当前会话读取失败不阻止切换。跨会话搜索复用 core Query/filter 并保留启动时的范围；命中位置复用 `context::locate`。导出复用 URI 工作流及 revision/message locator 校验，保证预览与导出来源一致。复制请求使用 OSC 52，不依赖平台剪贴板进程。

## 9. 扩展步骤

1. 新 Provider 实现 `Provider`，优先复用文件、SQLite、transcript 和 message assembly 模块。在 registry 声明身份和 URI。
2. 新格式修改 `output/formats.rs`、`output/export.rs` 及 Provider 能力；覆盖可观察输出和失败路径。
3. 新模式在 `cli_args.rs` 声明参数，在 `command.rs` 归一化和分发，再实现对应 workflow。
4. 增补隔离行为测试，并同步 README、recipes；领域事实边界变化时同步 `CONTEXT.md`。

现有 Provider 的数据范围见 README；OpenCode 2.x、MiniMax、Grok 与 Antigravity CLI 的读取规则见 [providers/](providers/)。DeepChat 不支持 SQLCipher/附件读取/Tape 恢复；Cherry 只读取当前分支及未删除会话；MiniMax 只读取支持的已迁移展示行。读取不执行上游迁移。
