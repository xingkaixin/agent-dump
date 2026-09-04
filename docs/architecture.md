# 架构与扩展指南

本文档面向修改架构、Provider、查询、导出或 collect 的贡献者和 Agent。根目录 `AGENTS.md` 保存常驻约束；本文件保存只在相关任务中需要的实现契约。

## 1. 公共接口

`src/agent_dump/__init__.py` 的 `__all__` 是公开 Python API 的单一机器可读来源。公开符号的行为由 `tests/test_version.py` 和对应模块测试保护，用户示例位于 README。

变更公开 API 时保持旧导入路径可用。确需演进时保留兼容入口，增加弃用说明，并同步更新 README 与测试。不要在本文复制完整符号表。

## 2. 数据流与职责

### 2.1 列表、查询与交互导出

```text
cli.py
  → CommandRequest
  → command_plan.py 生成闭集 operation
  → session_workflow.py
  → AgentScanner
  → BaseAgent Provider contract
  → selector / query / search
  → rendering.py / exporting.py
```

`cli.py` 是装配根。它解析参数并注入真实变化的依赖，不读取 Provider 数据，也不重复执行 operation 已完成的 Query 或 URI 解析。

### 2.2 URI

```text
uri_workflow.py
  → uri_support.parse_uri()
  → AgentScanner.locate / Provider.find_session_by_id()
  → head / print / summary / export
```

URI scheme、路径前缀和 identifier label 由 `agent_registry.AGENT_REGISTRATIONS` 声明。共享 URI 代码不得按 Provider 名称增加分支。

### 2.3 Collect

```text
collect_workflow.py
  → 发现并筛选 Session
  → collect_sessions.py 读取
  → collect_events.py 投影可见对话并规划 chunk
  → collect_reduction.py 总结与归并
  → collect_output.py 写入 Markdown
```

`--collect --emit-prompt` 在共享会话筛选后分支，由 `collect_handoff.py` 生成自包含提示词，不进入内部事件提取、chunk 规划和 LLM 请求。

## 3. Provider contract

`src/agent_dump/agents/base.py` 定义 `Session`、`ProviderDiscovery` 和 `BaseAgent`。共享工作流通过以下入口访问 Provider：

- `discover_sessions(days)`：一次返回可用性和会话窗口。
- `get_sessions(days)`、`find_session_by_id(id)`：自包含读取入口，不依赖预先调用 `is_available()`。
- `get_session_data(session)`：读取标准化完整 payload。
- `get_session_facts(session)`：读取 Working Directory、Provider Project、Model、Session Source、change sources 和 Message Count Fact。
- `get_session_head(session)`、`get_session_summary_fields(session)`、`get_formatted_title(session)`、`get_session_uri(session)`：不读取完整 payload 的投影。
- `export_session()`、`export_raw_session()`：统一导出入口。

Provider 私有 schema 只能在 `agent_dump.agents` 层解释。Provider 类可以复用 `FileSessionAgent`、`SQLiteSessionAgent`、transcript decoder、storage helper 和 message assembly helper；共享 workflow 不得自行解释 metadata key 或数据库字段。

完整 payload 有两种所有权入口：

- `get_cached_session_data(session)` 用于同一短工作流中的多投影复用，完成项受 LRU 上限约束。
- `lease_cached_session_data(session)` 用于 Search、Collect 等批量投影，退出 context 后释放完整 payload。

二者按 Provider 声明的 change sources 失效，合并同一 Session 的并发读取，并向消费者返回隔离副本。批量调用方不得使用普通缓存恢复全量驻留。

诊断通过 `AgentScanner.diagnostic_context()` 或显式 `diagnostic_sink` 传播。Provider 不直接打印，诊断 context 退出后不得影响其他调用方。

## 4. 导出格式

格式闭集和别名由 `output_formats.VALID_FORMATS`、`FORMAT_ALIASES` 定义；模式和 Provider 能力分别由 `validate_formats_for_mode()`、`validate_agent_formats()` 校验；`rendering.export_session_in_format()` 负责分发。

同一次导出的 summary、print、JSON 和 Markdown 复用同一份已读取内容。raw 独立复制 Provider 源；标准化读取失败不得阻止 raw 导出。

## 5. Query 与 Search

- `-query` 和 `agents://...?q=` 把归一化输入视为一个字面短语。
- `--search` 按空白解析 distinct 字面 term，全部 term 必须命中，且可跨标题和逻辑 transcript 字段。
- FTS5 只作为等价加速层；tokenizer 无法表达当前语义或索引失败时，整组回退到进程内 matcher。
- 跨 Provider 搜索先更新所有参与 Provider 的索引，再进行一次全局检索，避免混用不同快照的相关度。
- 索引正文解析在写事务外完成，批次通过短事务更新。旧请求的成功或失败不得覆盖更新的观察结果，慢读取不得恢复已删除行。
- 查询内部保留 `QuerySessionMatch` 证据。带 `role:` 的查询直接从允许角色的消息生成 snippet。

搜索语义或正文提取规则变化时同步更新索引内容版本，使旧缓存自动重建。

## 6. Collect 契约

- execute、dry-run 和 emit-prompt 在发现会话前调用 `ConfigurationDocument.validate_collect_safety()`。
- `CollectOperation.action` 使用 `CollectAction` 表示互斥动作，不增加可矛盾的平行布尔状态。
- collect 只读取 user/assistant 的可见文本，排除 system/developer/tool、reasoning、plan、工具调用和工具结果。
- 没有真实对话的 Session 在 chunk 规划前忽略。
- PM 摘要字段固定为 requests、decisions、outcomes；outcomes 只记录 Agent 明确报告的结果，不从工具轨迹或文件推断完成状态。
- 跨会话归并只在 PM 的同一日期和明确相同的工作目录内执行；工作目录未知时保留单会话归属；INSIGHT 保留单会话归属。
- 读取阶段返回失败数量，摘要失败数由计划与成功摘要数之差派生；部分失败时 Markdown 固定标明遗漏，完成日志记录实际成功数。兼容 `collect_entries()` 保持列表返回值。
- 最终输入超过 64,000 字符时拒绝请求并提示缩小范围。
- 模型响应先校验字段和字符串数组类型，再规范化。空对象、未知字段和错误类型进入现有纠正重试。

## 7. 扩展步骤

### 7.1 新增 Provider

1. 文件型 Provider 优先继承 `FileSessionAgent`；SQLite Provider 先评估 `SQLiteSessionAgent` 是否适用。
2. 实现 Provider 的 discovery、session data、search roots 和必要的直接定位能力。读取入口必须自包含。
3. 在 Provider 类声明 `provider_name`、`provider_display_name`，并在 `AGENT_REGISTRATIONS` 注册 factory、URI scheme 及可选路径前缀。
4. 从 `agents/__init__.py` 导出。只有稳定库 API 才加入顶层 `__init__.py`。
5. 增加 Provider 实现测试和 `tests/test_agents/test_contracts.py` 合约用例。
6. 更新 README、skill recipes 和 Provider 能力说明。

### 7.2 新增导出格式

1. 更新 `VALID_FORMATS` 和必要的 `FORMAT_ALIASES`。
2. 在 `export_session_in_format()` 增加分发。
3. 更新模式限制和 Provider 能力声明。
4. 覆盖解析、分发、成功导出和错误路径。
5. 更新 README 与 skill recipes。

### 7.3 新增 CLI 模式

1. 在 `cli.py` 增加参数，并只在 Namespace → `CommandRequest` 的投影处记录原始事实。
2. 在 `command_plan.py` 增加闭集 operation、默认值和组合校验。
3. 新建或复用 workflow。workflow 只接收对应 operation；稳定协作者直接 import，只注入真实变化的依赖。
4. 共享逻辑进入其职责模块，不把业务逻辑放回 `cli.py`。
5. 增加 command plan 归一化、CLI 分发和 workflow 行为测试。
6. 更新 README 与 skill recipes。

## 8. Provider 数据源

准确路径和 schema 由各 Provider 的 `get_search_roots()` 与实现代码拥有；URI 形状由 registry 拥有。诊断和文档展示必须从这些来源派生，不在共享模块复制 Provider 分支。

当前支持 OpenCode、ZCode、Codex、Kimi、Claude Code、Cursor 和 Pi。新增或移除 Provider 时以 registry、公开 API 和用户文档为同步边界，不在根 `AGENTS.md` 维护重复清单。
