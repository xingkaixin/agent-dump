# MiniMax Code Provider

## 1. 目标与依据

将 MiniMax Code CLI 的本地展示会话接入现有发现、查询、搜索、导出和 collect 流程。用户无需启动 MiniMax Code、登录或配置模型 API。

设计基线为 MiniMax Code 0.4.12，源码提交 `81b666a10bb1bd097633b373679dbf399278b8d3`。官方 npm 包需要另行验证；相同版本号不代表源码与发布包完全一致。

上游依据：

- [存储目录与环境变量](https://github.com/MiniMax-AI/minimax-code/blob/81b666a10bb1bd097633b373679dbf399278b8d3/docs/installation.md#accounts-and-data)
- [SQLite 连接与 WAL](https://github.com/MiniMax-AI/minimax-code/blob/81b666a10bb1bd097633b373679dbf399278b8d3/packages/local-runtime-v2/src/infra/db/client.ts)
- [会话字段及版本](https://github.com/MiniMax-AI/minimax-code/blob/81b666a10bb1bd097633b373679dbf399278b8d3/packages/local-runtime-v2/src/service/session-system/sessions/repo/drizzle/codec.ts)
- [消息表与顺序](https://github.com/MiniMax-AI/minimax-code/blob/81b666a10bb1bd097633b373679dbf399278b8d3/packages/local-runtime-v2/src/service/session-system/messages/repo/drizzle.ts)
- [消息类型、工具状态与用量](https://github.com/MiniMax-AI/minimax-code/blob/81b666a10bb1bd097633b373679dbf399278b8d3/packages/agent-core/src/protocol/agent-message.ts)
- [旧展示消息迁移](https://github.com/MiniMax-AI/minimax-code/blob/81b666a10bb1bd097633b373679dbf399278b8d3/packages/local-runtime-v2/src/service/session-system/messages/repo/readiness.ts)

## 2. 用户能力

| 能力 | 首版行为 |
| --- | --- |
| 自动发现与交互选择 | 作为 `MiniMax Code` 出现在现有 Provider 列表中 |
| Provider 标识 | `minimax` |
| 单会话 URI | `minimax://<session_id>`；使用源数据库的 session ID |
| 列表与 head | 标题、创建/更新时间、工作目录、模型、消息数量 |
| 查询 | 支持现有 Provider、路径、角色、关键字和时间窗口语义 |
| 搜索 | 使用标准化正文、思考和工具状态构建现有搜索语料 |
| 导出 | print、JSON、Markdown；格式别名沿用现有规则 |
| collect | 仅收集真实 user/assistant 的可见正文 |
| raw | 明确拒绝，提示使用 JSON/Markdown；不会复制整库 |

示例：

```bash
agent-dump --list -query "provider:minimax"
agent-dump 'minimax://<session_id>' --head
agent-dump 'minimax://<session_id>' --format json,markdown --output ./sessions
agent-dump --search "fix timeout" -query "provider:minimax"
```

## 3. 数据目录与支持范围

数据库位于 `<数据目录>/v2/sqlite/runtime-state.sqlite`。路径优先级为：

1. 非空 `MINIMAX_DATA_DIR`。
2. 非空 `MAVIS_DATA_DIR`。
3. `~/.minimax`。

环境变量先去除首尾空白。指定目录不存在时，不回退到另一份用户数据。自定义 profile、早期源码版的 `~/.minimax-code` 和其他安装目录由用户显式设置 `MINIMAX_DATA_DIR`；不扫描或合并多个 profile，不自动迁移目录。

首版支持当前 SQLite 中 `columnar_version = 3` 的 `pi-agent` 会话及已落盘的展示消息行。发现范围是可见的 `conversation`、`task`、`unknown` 会话，保留归档会话与父子关系；不把隐藏会话、peek、channel、cron 内部会话混入列表。URI 定位使用相同范围。空会话可显示，消息数为零。不同会话各自导出，不合并父子正文。

不承诺桌面端兼容，不读取旧 OpenCode 数据库、旧 JSON blob 正文、ledger/snapshot 或 `messages.jsonl` 模型上下文，不恢复 rewind 已删除的消息。附件只保留已有引用，不读取外部文件、不下载资源。

## 4. Session facts

| Session fact | 数据源与规则 |
| --- | --- |
| ID | `local_runtime_sessions.session_id` |
| 标题 | `title`；空值使用工作目录名称，再使用 session ID |
| 创建时间 | `created_at_ms`；空值使用 `updated_at_ms` |
| 更新时间 | `updated_at_ms` |
| Working Directory | `workspace_dir`；不把 Provider 名称或源数据库目录当成工作目录 |
| Model | `extra_data_json.effectiveModel`；缺失时保持未知，不读取当前全局模型配置 |
| Message Count Fact | 当前会话消息行 `COUNT(*)`，包括保留的内部事件；与完整导出消息数量一致 |
| Session Source | 实际读取的 SQLite 文件 |
| change sources | 数据库及同路径 `-wal`；不使用 `-shm` |

列表不读取 `data_json` 正文，不反序列化 `record_json`，不扫描模型历史文件。`get_session_head()` 等展示入口只投影已发现的 facts。

## 5. 正文与内部事件

按 `local_runtime_message_rows.id` 升序读取，保持上游展示顺序；不按时间重新排序。上游对同一 `msg_id` 的更新已经体现在数据库中，不重放流式片段。

每条 `data_json` 必须是 JSON object，且 `msg_id` 与行标识一致。损坏正文使该会话读取失败，不静默跳过，也不拼接其他来源掩盖错误。

| 上游字段 | 标准化结果 |
| --- | --- |
| `msg_content` | text part |
| `thinking_content` | reasoning part |
| `tool_calls[]` | tool part；保留工具名、调用 ID、参数、结果、状态和耗时 |
| 工具状态 1 / 2 / 3 / 4 / 5 | running / completed / error / pending / pending |
| 参数、结果的 JSON 字符串 | 解码为逻辑数据；无法解析的流式片段保留文本 |
| `usage.input_tokens` / `output_tokens` | 只保留源中存在的用量 |
| `usage.cache_read` / `cache_write` | cache read/write |
| `attachments` | 已有名称、路径、URL、类型等引用，不读取实体 |
| `kind = compaction*` | compaction 角色 |
| 其他非空 `kind` | custom 角色，保留原始 kind |
| `msg_type = 3` | system 角色 |
| 未知消息类型或角色 | unknown，避免伪装成普通对话 |
| user 正文以 `<permission-response>` 开头 | custom，保留权限响应但不作为用户需求收集 |

内部事件仍作为一条消息计数。其状态保存在 Provider 私有 part/metadata，不把状态 JSON 变成用户正文。collect 复用既有角色与 part 规则，排除思考、工具、压缩和其他内部事件。JSON 保留单条消息已知用量，不用当前模型补写历史模型，也不推算费用。

## 6. 只读与失败语义

- 每次发现、直接定位和正文读取独立建立 `mode=ro` 连接，启用 `query_only`，使用一个读取事务；无预先调用 `is_available()` 的要求。
- 正文始终从 `session.source_path` 读取，不回退到实例新发现的其他数据库。
- 不调用上游运行时、迁移器或会触发惰性迁移的读接口。只读事务可读取已提交 WAL；缓存以数据库和 WAL 的变化失效。
- 验证必要表及字段。缺表、缺字段或不可读取数据库通过现有诊断路径报告，不能把整库失败当成零会话。
- 单会话元数据损坏、未知 columnar version，或存在未完成迁移的旧展示消息时，发现保留其他成功会话并返回 `complete=False`；直接读取失败。
- 检查 `local_runtime_message_row_migrations`：已有 marker 时以消息行为准；没有 marker 且旧 `display_messages_json` 非空时，报告需要由 MiniMax Code 完成迁移。不会由 agent-dump 写 marker 或清空旧 blob。
- 数据源不存在返回 unavailable；一个受支持的空数据库保持 available。

## 7. 实现位置

`crates/agent-dump-core/src/providers/desktop/minimax.rs` 负责路径、只读连接、Session facts 与消息转换；只读连接与导出复用 `desktop/mod.rs`。历史恢复、桌面端和 raw 另行设计，不预先增加抽象。
