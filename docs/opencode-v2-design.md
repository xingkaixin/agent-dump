# OpenCode 2.x 会话兼容设计

## 1. 目标与依据

在现有 `OpenCodeAgent` 中支持 OpenCode 2.x 本地 SQLite 会话，使列表、统计、URI、查询、全文搜索、JSON/Markdown/print/raw 导出及 collect 使用同一份标准化正文。保留旧版 OpenCode 和 ZCode 的既有行为、公开 Python API 与 `opencode://<session_id>`。

本设计核对 OpenCode `v2` 分支提交 `88a9688c9c44ada8e01c4c7cad3ae92f54027aba`，包版本 `2.0.15`（2026-09-23）：

- `packages/core/src/session/sql.ts`：`session_v2`、`session_message`。
- `packages/schema/src/session-message.ts`：消息与工具状态。
- `packages/core/src/session/store.ts`：消息按 `seq` 排序。
- `packages/core/src/database/v1-migration.bun.ts`：旧会话复制到新表，旧表仍可保留。
- `packages/cli/src/database-path.ts`、`packages/util/src/global-roots.ts`：数据库定位。

现有读取器固定访问 `session/message/part`。临时数据库复现表明：纯 V2 数据库报 `no such table: session`；新旧表共存时会漏读 V2 会话。

## 2. 用户行为与数据源

已有命令无需改变，例如：

```bash
agent-dump --list -query 'provider:opencode'
agent-dump opencode://ses_example --head
agent-dump opencode://ses_example --format json,markdown
agent-dump --search 'timeout' -query 'provider:opencode'
agent-dump --collect --emit-prompt -query 'provider:opencode'
```

数据库选择规则：

1. 非空 `OPENCODE_DB` 指定唯一数据库；绝对路径直接使用，相对路径相对于 OpenCode 数据目录。指定路径不存在时不回退。
2. 数据目录为 `$XDG_DATA_HOME/opencode`，未设置时为 `~/.local/share/opencode`，Windows 同样如此。
3. 未显式指定数据库时，先查上述目录的 `opencode.db`，再保留本项目此前 Windows 的 LOCALAPPDATA/APPDATA 路径作为兼容候选，最后使用 `data/opencode/opencode.db` 开发回退。
4. 其他 channel 数据库通过 `OPENCODE_DB=opencode-<channel>.db` 选择；一次读取一个数据库，避免多个安装的同 ID 会话混淆。
5. `:memory:` 没有可读取的持久文件，报告不可用；不把它作为文件名打开。

只读连接使用 `mode=ro`。不启动 OpenCode、不执行迁移、不重放事件、不访问附件指向的文件或 URL。正文始终读取 `Session.source_path`，与实例此前发现的路径无关。数据库和 `-wal` 继续作为缓存变化来源。

## 3. 版本识别、发现与定位

以表结构识别存储版本，不使用会话 `version` 判断；迁移后的会话仍可能保留创建时的旧版本字符串。

| 结构 | 行为 |
| --- | --- |
| 只有 `session` | 沿用旧版读取器 |
| 只有 `session_v2` | 读取 V2 会话 |
| 新旧表共存 | V2 与旧版独有会话合并，同 ID 始终以 V2 为准 |
| 没有支持的会话表 | 明确读取失败，不能视为合法空结果 |

去重先于时间窗口判断：即使 V2 会话在窗口外，也不能让窗口内的旧副本重新出现。列表继续按创建时间倒序；直接定位在两种结构中使用相同优先级。保留现有按创建时间筛选最近 N 天的行为。

一次发现使用 SQLite 读事务，保证新旧合并、计数和元数据来自同一快照。V2 正文读取在独立读事务内重新读取当前会话行与消息，避免长期持有的 Session 元数据导致正文过时。读取失败向既有 Scanner/Query/Collect 错误处理传播，不回退到同 ID 的旧正文。

## 4. Session facts 与统计口径

| 信息 | V2 来源与规则 |
| --- | --- |
| 身份、标题 | `id`、`title`；空标题使用既有 `Untitled` 回退 |
| 工作目录 | `directory`，不以 project ID 或数据库目录代替 |
| Provider Project | `project_id` |
| 模型 | 会话 `model.id`；缺失或无效时未知 |
| 时间 | 毫秒时间戳 `time_created/time_updated` |
| 消息数 | `session_message` 的行数；每行对应一个标准化消息，包括系统和状态记录 |
| token 与费用 | 正文 stats 使用会话行的累计 `cost/tokens_input/tokens_output`；每条消息另保留其自身用量，二者不重复相加 |
| 父子、fork、归档、revert | 保留为 Provider 元数据，不自动合并父子会话 |
| 修改文件数 | `summary_files` 是数量，不能把数字显示成文件路径 |

列表和 head 只投影发现 facts，不读取完整消息 JSON。没有 `session_message` 表时消息数未知，正文读取失败，不能导出伪空会话。SQL `COUNT` 不要求解码正文；坏消息可以在列表中存在，但正文读取必须报告失败。

归档会话仍可发现。读取数据库当前保留的完整消息序列，包括运行中的已持久化内容；不把尚未投递的 `session_inbox/session_pending` 当成对话。不模拟 UI 的暂存 revert 筛选，也不恢复已经删除的消息。会话移动后的工作目录使用当前 `directory`，移动事件保留在元数据中。

## 5. 消息映射

按 `seq ASC` 读取，保留每行的 ID、原始 `type`（`entry_type`）及顺序。数据库列中的 ID/type 是权威值，不接受 JSON 覆盖。

| V2 消息 | 标准化角色 | 正文处理 |
| --- | --- | --- |
| `user` | user | `text` 转 text part |
| `assistant` | assistant | `content[]` 按原序转换 text、reasoning、tool |
| `system`、`skill` | system | 保留 text，可搜索，不进入 collect |
| `synthetic` | custom | 保留 text，可搜索，不冒充用户需求 |
| `shell` | tool | 命令、状态、已存输出转换为工具调用 |
| `compaction` | compaction | 保留 summary/recent，排除 collect |
| agent/model/location 切换、idle | custom | 保留事件元数据，不生成虚构正文 |
| 未知类型 | unknown | 保留原始数据作为元数据，不猜测对话角色 |

工具调用映射 `name → tool`、`id → callID`、`state.input → state.input`、`state.content → state.output`。保留 streaming/running/completed/error、结构化错误、执行时间和文件引用；错误文本进入可搜索的输出。streaming 的部分 JSON 参数保持字符串，不强行解析。

用户附件、agent/skill 引用，以及模型 variant、完成原因、错误和其他非正文信息保留在消息元数据中。附件内容不追加成用户可见文本。未知 assistant content 保留为元数据，不静默丢弃，也不让其原始序列化字段参与搜索。

JSON 无效、正文类型错误、已知工具结构错误时，整条 Session 正文读取失败。这样 collect 能报告真实遗漏，搜索不会将解析失败记为成功空结果。新增解析不改变旧版坏记录的现有处理。

## 6. 导出、搜索与 collect

- JSON 输出继续使用现有标准格式；V2 特有字段通过 metadata 和 entry_type 保留。
- Markdown/print 复用渲染器。工具输出、推理和可见正文通过现有 parts 展示。
- raw 沿用本项目 OpenCode 的 `.raw.json` 语义：内容与标准化 JSON 一致，不是数据库备份，也不是 OpenCode import 文件。
- Search/Query 读取标准化正文、推理和工具状态；Provider 原始元数据不是检索语料。
- 索引内容版本递增，避免已迁移会话在数据库未变化时继续命中旧缓存正文。
- collect 仅使用 user/assistant 可见文本；合成输入、系统/技能、压缩、shell、推理与工具结果不会混入需求和成果。

## 7. 实现归属

- `agents/opencode.py`：路径、schema 识别、发现/定位、V2 会话事实和正文组装。
- `agents/opencode_messages.py`：V2 消息到标准格式的纯转换。
- `agents/sqlite_sessions.py`：继续负责旧版 OpenCode/ZCode 的读取与通用 SQLite 生命周期，不引入 V2 schema。
- 不新增 Provider 注册、公开 API、CLI 参数、依赖或通用存储框架。

## 8. 验收与提交

测试使用临时 SQLite 和显式路径，覆盖以下真实边界：

1. 旧版、纯 V2、共存、同 ID 去重及跨时间窗；URI 直接定位；未知 schema 和缺表。
2. 默认、自定义、Windows 兼容路径，显式缺失不回退，特殊字符文件名，内存库不可用。
3. `seq` 与时间戳顺序不同；11 种已知消息、未知消息/part、工具生命周期、错误、附件、模型与累计用量。
4. head/list/count 一致、展示无正文 I/O；新实例按 source_path 读取；源缺失无路径回退。
5. JSON/Markdown/raw、CLI 列表/URI、Search/Query 与 collect 排除规则。
6. 损坏正文失败；DELETE/WAL 更新使正文缓存与搜索索引失效；读前后数据库内容不变。
7. 运行 OpenCode/ZCode 相关测试和 Provider contract，再运行 `just isok`；PR CI 包含 Python 3.10–3.14 与覆盖率检查。

提交按设计文档、Provider 实现与行为测试、使用文档与集成验证拆分。PR 使用英文说明。CI 通过、无未解决的阻塞评审且无合并冲突后，按用户授权执行 squash merge 并删除分支。
