# Antigravity CLI Provider

## 1. 目标与依据

读取 Antigravity CLI 与隔离 ACP 实例的本地会话数据库，接入现有发现、查询、搜索、导出和 collect 流程。会话发现与解析参照 CodeSesh 的 [`antigravity-cli` 适配器](https://github.com/xingkaixin/codesesh/blob/1265b0586e45148b67992523cb66221750580df8/crates/codesesh-core/src/agents/antigravity_cli.rs) 及其格式说明 `docs/agents/antigravity-cli.md`。

该存储没有公开的 Protobuf schema。字段编号来自 CodeSesh 引用的第三方读取器和本地数据库核对，不是官方 schema 保证。agent-dump 只解码下表列出的字段。

## 2. 来源与发现

| 项目 | 规则 |
| --- | --- |
| Provider 标识 | `antigravity-cli`，展示名 `Antigravity CLI` |
| URI | `antigravity-cli://<conversation_id>`，ID 为数据库文件名去掉 `.db` |
| 会话目录 | `AGY_CONVERSATIONS_DIR` → `~/.gemini/antigravity-cli/conversations` → `data/antigravity-cli/conversations` |
| 自动补充来源 | `<T3 home>/userdata/providers/antigravity/<instance>/antigravity-acp/conversations`，与常规会话目录同时读取 |
| T3 home | 非空 `T3CODE_HOME` → `~/.t3`；T3 使用 `--base-dir` 时，把 `T3CODE_HOME` 设为同一目录 |
| 显式覆盖 | 非空 `AGY_CONVERSATIONS_DIR` 关闭 T3 实例自动发现，保留原有本地开发回退规则 |
| 会话 | 会话目录下任意深度的 `*.db`，每个文件是一个会话 |
| 摘要库 | 各会话目录的父目录中的 `conversation_summaries.db`，分别读取，可选 |
| 不读取 | Antigravity IDE 的 `.gemini/antigravity/conversations/*.pb` |

数据库与摘要库均以只读事务打开，不写入、不迁移。摘要库提供标题、`workspace_uris`、`last_modified_time`，以及可选列 `parent_conversation_id` 与 `agent_name`。摘要库中没有对应数据库的条目不会列出。

摘要没有有效工作目录时，从会话数据库可选的 `trajectory_metadata_blob.data` 重复字段 7 读取本地 `file://` 工作区 URI。

当摘要或 trajectory 提供多个去重后的本地工作区候选时，按以下顺序判定活跃工作目录：同摘要目录下的可选 `history.jsonl`（匹配 `conversationId` 的 `workspace`）→ 用户输入上下文 URI 与工具入参路径/文件/目录字段的唯一最多命中 → 工具入参命令字符串的唯一最多命中 → 父会话工作区（先查 `history.jsonl`，再递归解析同来源下的父会话并防环）→ 第一个本地 URI。

每次发现和 URI 查找都重新枚举 T3 实例，只读取固定的 `antigravity-acp/conversations` 子目录，不打开 T3 应用数据库。某个实例的数据库、摘要库或目录读取失败时报告部分失败，其他来源继续返回结果。导出、collect 输出和搜索索引的写入保护覆盖常规来源根目录和 T3 的 Antigravity 实例父目录。

## 3. 字段映射

`steps` 按 `idx` 排序，读取 `step_payload`（Protobuf）与可选列 `error_details`（Protobuf）：

| 字段 | 含义 |
| --- | --- |
| 5 | 步骤元数据：1 创建时间（1 秒、2 纳秒），4 工具调用（1 ID、2 名称、3 输入、9 备用名称），9 用量，24 模型配置（8 展示名、12 API 名），28 重试（2 用量） |
| 14 | `view_file` 结果：4 文本内容 |
| 19 | 用户输入：2 文本；为空时依次拼接重复字段 3 中的 1 文本，并从各分段 2 上下文的 1 文件 / 2 目录读取 5 URI |
| 20 | 助手文本：1 |
| 28 | `run_command` 结果：21 输出文本（1） |
| 30 | 标题更新：4 |
| 31 | 步骤显式错误：2 错误消息、3 详细信息（在 `steps.error_details` 为空时回退） |
| 47 | `call_mcp_tool` 结果：3 结果文本 |
| 140 | 工具执行结果：2 结果文本（1） |

用量字段：1 模型 ID，2 输入，3 总输出，4 缓存写入，5 缓存读取，7 消息 ID，9 推理，10 可见输出，11 响应 ID，12 Provider 消息 ID。`gen_metadata.data` 的 1.3 模型 ID 映射到 1.19 模型名。

主请求用量没有模型 ID 时，使用步骤模型配置中非空的 API 名，再回退到展示名。重试可能使用不同模型，缺少模型 ID 时保持未知，不套用主请求的配置。

解码器只实现 varint、64 位、长度分隔和 32 位 wire type。未知字段跳过；重复出现的单值 message 字段按 Protobuf 语义合并。截断、超长 varint、字段号 0、group 和非法 wire type、已知字段 wire type 不符、字符串非 UTF-8 都返回错误。

## 4. 消息与用量

- 类型 14 为用户消息，15 为助手文本，23 只更新标题。其他类型、或文本为空的 14/15，若元数据带工具调用，则作为助手工具消息；否则计为未识别步骤并跳过。
- 解码步骤类型 `132`（`140.2.1`）、`8`（`14.4`）、`21`（`28.21.1`）与 `38`（`47.3`）的非空工具结果到 `output`，不根据输出文本猜测成功或失败；优先读取 `steps.error_details`（回退字段 `31`）去重拼接 `message` 与 `details`，存在显式错误时工具状态为 `error` 并写入 `error`，其余状态保持 `unknown`，`metadata` 保留 `antigravity_step_type` 和 `antigravity_status`。输入是 JSON 时解析，否则保留字符串。
- 无错误且 `swarm` 调用 `input.action == "add"` 时，若输出 JSON（含或不含 `Created At:/Completed At:` 头）包含 `status == "added"` 与非空 `conversation_id`，将其写入对应消息的 `subagent_id`。
- 没有原生创建时间的步骤使用摘要更新时间，再回退到数据库修改时间，并标记 `inferred_time`。创建与更新时间是该时间与全部消息时间的最小值和最大值。
- 标题依次取最后一个标题更新、摘要标题、子会话（有非空且不同于自身的 `parent_conversation_id`）的 `agent_name`、首条用户消息，最后为 `Untitled Session`。
- 用量按响应 ID、Provider 消息 ID、消息 ID 去重，重试列表中的重复记录只计一次；全零记录忽略。用量挂到下一条助手消息，最后一步之后剩余的用量生成一条只有用量的助手消息。
- 输入包含缓存读写；会话输出包含推理，总量为输入加输出。会话模型取最后一次带模型的用量。
- 没有任何步骤的数据库不列出。表结构不支持或 payload 格式错误时，该会话发现失败并给出诊断，其他会话照常列出。

## 5. 与 CodeSesh 的差异

- 不估算费用、不输出按模型的用量分布：agent-dump 不维护定价表，Session 只有一个模型字段。
- 不输出父会话引用：agent-dump 的 Session 没有父会话字段（但会读取父会话 ID 用于多工作区继承和子会话 `agent_name` 标题回退）。
- 不输出“未识别步骤数量”提示：agent-dump 没有对应的会话提示字段。
- 缓存读写总量只保留在消息 token 中，会话统计没有单独字段。
- 没有原生时间的消息标记为推测时间，collect 排除这类消息。CodeSesh 直接使用回退时间。
- 增加 `data/antigravity-cli/conversations` 本地开发回退目录，与其他文件型 Provider 一致。
- 不支持 raw 导出：来源是 SQLite 数据库，与 DeepChat、Cherry Studio、MiniMax Code 一致。
