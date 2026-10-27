# Antigravity CLI Provider

## 1. 目标与依据

读取 Antigravity CLI 的本地会话数据库，接入现有发现、查询、搜索、导出和 collect 流程。会话发现与解析以 CodeSesh 的 `antigravity-cli` 适配器为准（`crates/codesesh-core/src/agents/antigravity_cli.rs` 及其格式说明 `docs/agents/antigravity-cli.md`）。

该存储没有公开的 Protobuf schema。字段编号来自 CodeSesh 引用的第三方读取器和本地数据库核对，不是官方 schema 保证。agent-dump 只解码下表列出的字段。

## 2. 来源与发现

| 项目 | 规则 |
| --- | --- |
| Provider 标识 | `antigravity-cli`，展示名 `Antigravity CLI` |
| URI | `antigravity-cli://<conversation_id>`，ID 为数据库文件名去掉 `.db` |
| 会话目录 | `AGY_CONVERSATIONS_DIR` → `~/.gemini/antigravity-cli/conversations` → `data/antigravity-cli/conversations` |
| 会话 | 会话目录下任意深度的 `*.db`，每个文件是一个会话 |
| 摘要库 | 会话目录的父目录中的 `conversation_summaries.db`，可选 |
| 不读取 | Antigravity IDE 的 `.gemini/antigravity/conversations/*.pb` |

数据库与摘要库均以只读事务打开，不写入、不迁移。摘要库提供标题、第一个可转换为本地路径的 `file://` 工作区 URI，以及 `last_modified_time`。摘要库中没有对应数据库的条目不会列出。

## 3. 字段映射

`steps` 按 `idx` 排序，`step_payload` 为 Protobuf：

| 字段 | 含义 |
| --- | --- |
| 5 | 步骤元数据：1 创建时间（1 秒、2 纳秒），4 工具调用（1 ID、2 名称、3 输入、9 备用名称），9 用量，28 重试（2 用量） |
| 19 | 用户输入：2 文本，回退到 3.1 |
| 20 | 助手文本：1 |
| 30 | 标题更新：4 |

用量字段：1 模型 ID，2 输入，3 总输出，4 缓存写入，5 缓存读取，7 消息 ID，9 推理，10 可见输出，11 响应 ID，12 Provider 消息 ID。`gen_metadata.data` 的 1.3 模型 ID 映射到 1.19 模型名。

解码器只实现 varint、64 位、长度分隔和 32 位 wire type。未知字段跳过；重复出现的单值 message 字段按 Protobuf 语义合并。截断、超长 varint、字段号 0、group 和非法 wire type、已知字段 wire type 不符、字符串非 UTF-8 都返回错误。

## 4. 消息与用量

- 类型 14 为用户消息，15 为助手文本，23 只更新标题。其他类型、或文本为空的 14/15，若元数据带工具调用，则作为助手工具消息；否则计为未识别步骤并跳过。
- 工具结果与状态码含义未知，工具状态固定为 `unknown`，`metadata` 保留 `antigravity_step_type` 和 `antigravity_status`。输入是 JSON 时解析，否则保留字符串。
- 没有原生创建时间的步骤使用摘要更新时间，再回退到数据库修改时间，并标记 `inferred_time`。创建与更新时间是该时间与全部消息时间的最小值和最大值。
- 标题依次取最后一个标题更新、摘要标题、首条用户消息，最后为 `Untitled Session`。
- 用量按响应 ID、Provider 消息 ID、消息 ID 去重，重试列表中的重复记录只计一次；全零记录忽略。用量挂到下一条助手消息，最后一步之后剩余的用量生成一条只有用量的助手消息。
- 输入包含缓存读写；会话输出包含推理，总量为输入加输出。会话模型取最后一次带模型的用量。
- 没有任何步骤的数据库不列出。表结构不支持或 payload 格式错误时，该会话发现失败并给出诊断，其他会话照常列出。

## 5. 与 CodeSesh 的差异

- 不估算费用、不输出按模型的用量分布：agent-dump 不维护定价表，Session 只有一个模型字段。
- 不输出父会话引用：agent-dump 的 Session 没有父会话字段。
- 不输出“未识别步骤数量”提示：agent-dump 没有对应的会话提示字段。
- 缓存读写总量只保留在消息 token 中，会话统计没有单独字段。
- 没有原生时间的消息标记为推测时间，collect 排除这类消息。CodeSesh 直接使用回退时间。
- 增加 `data/antigravity-cli/conversations` 本地开发回退目录，与其他文件型 Provider 一致。
- 不支持 raw 导出：来源是 SQLite 数据库，与 DeepChat、Cherry Studio、MiniMax Code 一致。
