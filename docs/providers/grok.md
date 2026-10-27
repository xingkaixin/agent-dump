# Grok Provider

Grok CLI 会话的发现和解析以 CodeSesh 的 `agents/grok.rs` 为准。Provider 标识、URI scheme 均为 `grok`，展示名为 `Grok`。

## 1. 来源与发现

- 数据根依次为 `GROK_HOME`、`~/.grok`。会话目录是 `<数据根>/sessions`；该目录不存在而 `data/grok` 存在时，改用后者。
- 递归查找任意深度的 `summary.json`。`info.id` 和 `info.cwd` 都是非空字符串时才视为会话；JSON 解析失败的文件不计为读取失败。
- 消息来自同目录的 `updates.jsonl`。文件缺失或没有可见消息的会话不列出，URI 定位使用相同范围。
- Session ID 为 `info.id`，URI 为 `grok://<info.id>`。目录名与 ID 相同的会话优先定位。
- 工作目录为 `info.cwd`。创建时间取 `created_at`，缺失时取 `summary.json` 的修改时间；更新时间依次取 `last_active_at`、`updated_at`、创建时间。
- 标题依次取 `generated_title` 或 `session_summary`、第一条用户输入、工作目录名称、`Untitled Session`。
- `change_sources` 为 `summary.json` 与 `updates.jsonl`；raw 导出 `updates.jsonl`。

## 2. 正文

- 每行是 ACP `session/update` 通知；`method` 为 `_x.ai/session/update` 的记录是 Grok 私有事件。
- `rewind_marker` 按 `target_prompt_index` 删除该提问及之后的记录，再处理正文。
- 同一提问的连续 `user_message_chunk` 合并为一条 user 消息；`hostTurn` 记录跳过。同一 `promptId` 的连续 assistant 片段合并为一条消息，相邻文本、思考分别拼接。
- `tool_call` 生成工具调用，名称优先取 `_meta["x.ai/tool"].name`；`tool_call_update` 原地更新状态、输入和输出。失败输出写入 `state.error`，其余写入 `state.output`。
- 同一条 assistant 消息中的 `plan` 只保留最后一次，全部条目完成时为 `success`。
- `model_changed`、`model_auto_switched` 更新后续消息的模型，初始模型为 `current_model_id`；`current_mode_update` 更新模式；`subagent_spawned` 记录子会话 ID。
- `turn_completed` 的用量归入最近一条尚无用量的 assistant 消息。`costUsdTicks` 在用量完整时记为费用（1 tick = 1e-10 美元）。
- 记录缺少 `agentTimestampMs` 和 `timestamp` 时，消息时间使用会话创建时间，并标记为推测时间，collect 排除这类消息。

## 3. 统计

会话 token 与费用汇总所有 `turn_completed`，包括被 rewind 撤销的回合，与 CodeSesh 一致。缓存读取和写入大于零时分别输出 `total_cache_read_tokens`、`total_cache_create_tokens`。

## 4. 与 CodeSesh 的差异

- 不估算费用，只使用记录的 `costUsdTicks`；不输出 per-model 用量、父会话引用、project identity、smart tags 和 file activity。
- 消息数量使用清理后的正文消息数，列表、head 与导出一致；CodeSesh 的列表计数是单独的近似值。
- 标题截断到 100 个 Unicode 字符，与其他 Provider 一致；CodeSesh 按 UTF-16 单元截断。
- URL 图片的地址保存在 `data` 字段。
- 发现时不读取 `summary.json` 的 I/O 错误会作为部分失败报告；`updates.jsonl` 中无法解析的行在读取正文时作为可恢复诊断报告。
