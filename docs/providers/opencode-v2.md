# OpenCode 2.x Provider

## 1. 目标与依据

在现有 OpenCode Provider 中支持 OpenCode 2.x 本地 SQLite 会话，使列表、统计、URI、查询、全文搜索、JSON/Markdown/print/raw 导出及 collect 使用同一份标准化正文。保留旧版 OpenCode 和 ZCode 的既有行为与 `opencode://<session_id>`。

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
| 新旧表共存，`kv` 中 `migration.v1-v2` 的 `phase` 为 `completed` | 只读取 V2 |
| 新旧表共存，迁移未完成 | 读取 V2，并补入 ID 小于 `cursor` 且不在 V2 中的旧版会话；没有 `cursor` 时补入全部不在 V2 中的旧版会话 |
| 没有支持的会话表 | 明确读取失败，不能视为合法空结果 |

OpenCode 按会话 ID 降序逐个复制旧版会话，并把最后复制的 ID 记为 `cursor`。ID 不小于 `cursor` 却不在 V2 中的会话已在 V2 删除，不从旧表复活；两边都有的会话只读 V2。迁移完成后已发现的旧版会话按缺失处理，不回退到旧表正文。

去重先于时间窗口判断：即使 V2 会话在窗口外，也不能让窗口内的旧副本重新出现。列表继续按创建时间倒序；直接定位在两种结构中使用相同优先级。`--time-field created` 时，发现阶段按 `time_created` 筛选最近 N 天；默认的 updated 窗口由调用方按 `updated_at` 过滤。

会话选择：

- 子会话作为独立 Session 列出。V2 和迁移中的旧版会话保留父会话不存在的孤立子会话。
- 纯旧版数据库有 `parent_id` 列时，只保留根会话及能沿父链到达根会话的子会话；父会话不存在的子会话丢弃。没有 `parent_id` 列时（ZCode），排除 `task_type = 'subagent_child'` 的会话。
- 没有可见消息的会话不列出。缺少消息表时仍列出，消息数未知，正文读取失败。

一次发现使用 SQLite 读事务，保证新旧合并、计数和元数据来自同一快照。V2 正文读取在独立读事务内重新读取当前会话行与消息，避免长期持有的 Session 元数据导致正文过时。读取失败向既有 Scanner/Query/Collect 错误处理传播，不回退到同 ID 的旧正文。

## 4. Session facts 与统计口径

| 信息 | V2 来源与规则 |
| --- | --- |
| 身份 | `id` |
| 标题 | `title` 去除系统标签后取首个非空行，压缩空白并截到 100 字符；为空时用首条普通用户文本，再没有时为 `Untitled Session` |
| 工作目录 | `directory`，不以 project ID 或数据库目录代替 |
| Provider Project | `project_id` |
| 模型 | 会话 `model.id`；缺失或无效时未知 |
| 时间 | 毫秒时间戳 `time_created/time_updated`；`time_updated` 为空时使用创建时间 |
| 消息数 | 可见消息数；丢弃 `idle`，以及既没有可见内容也没有用量的记录 |
| token 与费用 | 正文 stats 使用会话行的累计值：输入为 `tokens_input` 加缓存读写，输出为 `tokens_output` 加 `tokens_reasoning`，`total_tokens` 为五项之和，费用为 `cost`；每条消息另保留其自身用量，二者不重复相加 |
| 父子、fork、归档、revert | 保留为 Provider 元数据，不自动合并父子会话 |
| 修改文件数 | `summary_files` 是数量，不能把数字显示成文件路径 |

发现时解码消息以计算可见消息数和标题回退。无法解码的消息计为可见，坏会话仍在列表中，正文读取报告失败。没有 `session_message` 表时消息数未知，正文读取失败，不能导出伪空会话。

归档会话仍可发现。读取数据库当前保留的完整消息序列，包括运行中的已持久化内容；不把尚未投递的 `session_inbox/session_pending` 当成对话。不模拟 UI 的暂存 revert 筛选，也不恢复已经删除的消息。会话移动后的工作目录使用当前 `directory`，移动事件保留在元数据中。

## 5. 消息映射

按 `seq ASC` 读取，保留每行的 ID、原始 `type`（`entry_type`）及顺序。数据库列中的 ID/type 是权威值，不接受 JSON 覆盖。

| V2 消息 | 标准化角色 | 正文处理 |
| --- | --- | --- |
| `user` | user | `text` 转 text part；内联图片附件转 image part，其他附件转 `[Attachment] 名称 · 类型 · URI`；`agents/skills` 提及转 `@name` |
| `assistant` | assistant | `content[]` 按原序转换 text、reasoning、tool；没有名字的 tool 和未知内容转 `[Unknown content] JSON` |
| `system`、`skill` | system | `[类型] 描述或名称` 加 text，可搜索，不进入 collect |
| `synthetic` | custom | `[synthetic] 描述或名称` 加 text，不冒充用户需求 |
| `shell` | tool | 命令、状态、已存输出转换为工具调用 |
| `compaction` | compaction | `[Compaction: 状态]` 与 summary/recent 合成一段文本，排除 collect |
| agent/model/location 切换 | custom | `[类型] 原始 JSON` 文本 |
| `idle` | - | 丢弃 |
| 未知类型 | unknown | `[类型] 原始 JSON` 文本，不猜测对话角色 |

任意类型带 `error` 时追加 `[Error] 错误内容` 文本。图片以外的附件只显示名称、类型和 URI，不读取引用文件；附件不再写入消息元数据的 `files`。模型 variant、完成原因和其他非正文信息保留在消息元数据中。

工具调用映射 `name → tool`、`id → callID`、`state.input → state.input`、`state.content → state.output`。状态只保留 completed/error，其余（含 streaming）归一为 running。保留结构化错误、执行时间和文件引用；错误文本进入可搜索的输出。streaming 的部分 JSON 参数保持字符串，不强行解析。shell 的 `status` 为 running 时为运行中；`exited` 且 `exit` 为空或 0 时为完成；其余为失败，并写入 `Shell 状态 (exit: 退出码)` 错误。`subagent` 工具的 `metadata.sessionID` 唯一时写入消息的 `subagent_id`。

只有消息 JSON 无效、不是对象，或 assistant 的 `content` 不是数组时，整条 Session 正文读取失败。其他字段缺失或类型错误时置空，不让整条会话读取失败。

### 旧版与 ZCode

- 丢弃 internal 类型（progress、file history snapshot、queue operation、last prompt）和没有可见 part 的消息。可见 part 为非空 text/reasoning/plan、image 和有名字的 tool。
- ZCode 的 plan part 转 plan，文本取 `text`，否则按审批结果取 `input` 或 `output`；image part 转 image，需要 `data` 加 `mime_type`，或 `url`；只有 `url` 时 image 的 `data` 为该 URL。
- tool 的输入依次取 `state.input`、`state.arguments`、`input`，输出依次取 `state.output`、`state.result`、`output`。状态归一为 running/error/completed：`success` 视为完成；没有状态时，有错误为失败，有输出为完成。缺少工具名时使用去掉 `Tool:` 前缀的 title，仍为空的 tool 丢弃。
- stats 只统计可见消息。输入 token 包含缓存读写，输出 token 包含推理。纯旧版数据库中，父会话另加上全部后代会话非 internal 消息的费用和 token，消息数不变。

## 6. 导出、搜索与 collect

- JSON 输出继续使用现有标准格式；V2 特有字段通过 metadata 和 entry_type 保留。
- Markdown/print 复用渲染器，展示可见正文和推理，沿用现有不展开普通工具轨迹的规则。工具参数、输出和错误保留在 JSON/raw 中并可搜索。
- raw 沿用本项目 OpenCode 的 `.raw.json` 语义：内容与标准化 JSON 一致，不是数据库备份，也不是 OpenCode import 文件。
- Search/Query 读取标准化正文、推理和工具状态；Provider 原始元数据不是检索语料。
- 索引内容版本递增，避免已迁移会话在数据库未变化时继续命中旧缓存正文。
- collect 仅使用 user/assistant 可见文本；合成输入、系统/技能、压缩、shell、推理与工具结果不会混入需求和成果。

## 7. 实现位置

`crates/agent-dump-core/src/providers/sqlite/` 下，`mod.rs` 负责路径、schema 识别、发现/定位与 Session facts，`v2.rs` 负责 V2 消息转换，`legacy.rs` 继续负责旧版 OpenCode/ZCode，`connection.rs` 负责只读连接。
