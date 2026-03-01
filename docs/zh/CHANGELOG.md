# 更新日志

## [未发布]

### 新增功能

- **多格式导出与 raw 原始会话输出**
  - `--format` 现已支持逗号分隔多值，例如 `json,markdown,raw`
  - 为所有 agent 增加 `raw` 导出能力
  - 保留 `md` 作为 `markdown` 的兼容别名

### 变更

- **按模式区分格式行为**
  - URI 模式可组合 `print` 与文件导出，例如 `print,json`
  - 交互模式支持 `json`、`markdown`、`raw`，但拒绝 `print`

## [0.6.2] - 2026-02-28

### 问题修复

- **Codex 响应导出去重**
  - assistant 可见的 `reasoning` 与 `text` 只从 `response_item` 提取
  - 避免 `event_msg` 镜像记录导致的 thinking/commentary 重复导出

### 变更

- **Codex `apply_patch` 工具导出结构**
  - 将 `custom_tool_call(name=apply_patch)` 统一归一化为 `tool=patch`
  - 将 patch input 重建为 `state.arguments.content` 下按文件和操作组织的块列表
  - 文件编辑输出为 diff 文本，新增文件输出为最终文件内容，删除和纯移动输出为空内容
  - 保留原始 patch 文本用于兜底与调试，并继续按 `call_id` 回填工具输出

## [0.6.1] - 2026-02-28

### 新增功能

- **Kimi 解析器支持 `context.jsonl` 会话**
  - 支持 Kimi 较新的会话存储格式
  - 统一工具标题映射，并跳过噪音较大的 `SetTodoList` 工具记录

### 问题修复

- **Codex 导出重建逻辑**
  - 修正重建消息与工具调用时导出的时间戳
  - 改进 assistant/tool 分组逻辑，避免将工具调用挂到仅含 reasoning 的消息上
- **Claude Code 工具轨迹导出**
  - 清理导出会话中的工具轨迹内容
  - 在重建 assistant 状态时回填缺失的工具输出

### 改进

- 扩展 Kimi、Codex 和 Claude Code 会话解析的回归测试覆盖
- 将 `.uv-cache/` 添加到 `.gitignore`

## [0.6.0] - 2026-02-26

### 破坏性变更

- **筛选与分页参数的 CLI 语法调整**
  - `--days` -> `-days`（短别名 `-d`）
  - `--query` -> `-query`（短别名 `-q`）
  - `--page-size` -> `-page-size`（短别名 `-p`）
  - `--list`、`--interactive`、`--output` 仍保持双短横线风格

### 新增功能

- **国际化支持（英文/中文）**
  - 新增 `--lang {en,zh}` 参数，可强制指定 CLI 语言
  - 新增统一的翻译模块，用于管理用户可见文案
- **通过 `--format` 选择导出格式**
  - 支持 `json`、`md`、`print`
  - 新增会话 Markdown 导出能力

### 变更

- **不同模式的默认导出格式**
  - URI 模式默认 `print`
  - 交互/导出流程默认 `json`
- **Python 兼容性基线**
  - 调整代码以支持 Python `>=3.10`

### 改进

- **CI 自动化**
  - 新增 GitHub Actions 工作流，执行 lint、类型检查与测试
  - 扩展 CI Python 版本矩阵覆盖（3.10-3.14）

### 文档

- 更新 README/README_zh 中的 CLI 参数语法与格式用法示例
- 在 `skills/agent-dump/` 下新增 Skills 集成文档与 CLI recipes

## [0.5.0] - 2026-02-24

### 新增功能

- **跨 Agent 关键词查询 (`--query`)**
  - 支持 `keyword` 与 `agent1,agent2:keyword` 两种格式
  - 支持 agent 别名 `claude` -> `claudecode`
  - 支持按会话标题与内容进行关键词匹配，提升定位效率
- **支持 Codex URI 变体**：`codex://threads/<session_id>`
  - `codex://threads/<id>` 与 `codex://<id>` 现在等价

### 变更

- **列表模式输出行为** (`--list`)
  - 现在一次性输出全部匹配会话（不再出现分页提示）
  - `--page-size` 为兼容旧参数仍可传入，但在列表模式下会被忽略

### 问题修复

- **导出与 URI 文本渲染中的消息过滤**
  - 过滤 `developer` 角色消息
  - 过滤注入的上下文型 user 消息（如 AGENTS/instructions/environment 区块）
  - 降低导出结果中的提示词与上下文噪音

### 改进

- **测试覆盖**
  - 新增更完整的 CLI 测试（URI 解析、列表行为、消息过滤）
  - 新增 query 过滤与 Codex 导出过滤的针对性测试

## [0.4.0] - 2026-02-23

### 新增功能

- **URI 模式** - 通过 Agent Session URI 直接导出会话文本
  - 新命令: `agent-dump <uri>` (如 `opencode://session-id`)
  - 支持的 URI 协议: `opencode://`, `codex://`, `kimi://`, `claude://`
  - 直接将格式化的会话文本渲染到终端
  - 适用于快速查看会话内容，无需导出到文件
- **Agent Session URI 显示** - 在 CLI 列表和交互式选择器中显示 URI
  - 每个会话现在显示其唯一的 URI，便于引用
  - 支持复制粘贴格式，方便在 URI 模式中使用
- **开发命令** - 新增 `just isok` 命令，一键运行 lint、check 和 test

### 问题修复

- **会话列表中断处理** - 正确处理退出和中断信号
  - `display_sessions_list` 返回布尔值指示用户是否退出
  - 将 `EOFError` 和 `KeyboardInterrupt` 作为退出信号处理

## [0.3.0] - 2026-02-23

### 破坏性变更

- **CLI 默认行为变更**：直接运行 `agent-dump` 现在显示帮助信息，而不是进入交互模式
  - 使用 `--interactive` 参数进入交互式选择模式
  - 仅使用 `--days N` 时自动启用列表模式

### 新增功能

- **列表模式支持分页** (`--list`)
  - 新增 `--page-size` 参数控制每页显示数量（默认：20）
  - 交互式分页，按 Enter 查看更多，输入 'q' 退出
- **交互模式时间分组**
  - 会话按时间分组：今天、昨天、本周、本月、更早
  - 时间组之间显示视觉分隔符，便于导航
- **大量会话警告**：当发现超过 100 个会话时显示警告，建议使用 `--days` 缩小范围

### 问题修复

- **`--days` 过滤在 `--list` 模式下现在正常工作**
  - 之前显示所有扫描的会话，忽略时间过滤
  - 现在根据指定的时间范围正确过滤会话
- **时区兼容性**：修复 naive 和 aware datetime 之间的比较错误
  - Claude Code 和 Codex 使用 UTC 时区感知的 datetime
  - OpenCode 和 Kimi 使用无时区的 datetime
  - 所有比较现在统一归一化为 UTC

### 改进

- 交互式 Agent 选择现在根据 `--days` 参数显示过滤后的会话数量
- 更好的用户体验，提供清晰的提示和导航说明

## [0.2.0] - 2026-02-22

### 新增功能

- 多 Agent 支持的扩展架构
  - 新增 `BaseAgent` 抽象类和 `Session` 数据模型
  - 实现 OpenCode、Codex、Kimi 和 Claude Code 的 Agent
  - 新增 `AgentScanner` 用于发现可用 Agent 和会话
  - 重构 CLI 以支持 Agent 选择和统一导出格式
- Claude Code 和 Codex 的智能会话标题提取
  - Claude Code: 优先使用 `sessions-index.json` 元数据中的标题
  - Codex: 优先使用全局状态 `thread-titles` 缓存中的标题
  - 两者: 当元数据不存在时回退到消息提取

### 变更

- 交互式选择库从 `inquirer` 更换为 `questionary`
- 使用 `agents/` 目录重新组织项目结构
- 移除旧的 `db.py` 和 `exporter.py` 模块，采用基于 Agent 的新架构
- 更新测试以适配新架构

### 改进

- 所有 Agent 的错误处理，添加 try-catch 块和描述性错误消息
- 标准化导入，统一使用 UTC 时区处理
- 修复 selector 模块中的键绑定安全检查
- 改进 Claude Code 内容列表格式的标题提取
- 所有 Agent 使用一致的文件打开模式

## [0.1.0] - 2025-02-21

### 新增功能

- 首次发布 agent-dump
- 支持 OpenCode 会话导出
- 使用 questionary 提供交互式会话选择
- 导出会话为 JSON 格式
- 具有多个选项的命令行界面
  - `--days` - 按最近天数过滤会话
  - `--agent` - 指定 AI 工具名称
  - `--output` - 自定义输出目录
  - `--list` - 仅列出会话而不导出
  - `--export` - 导出指定会话 ID
- 完整的会话数据导出，包括消息、工具调用和元数据
- 支持 `uv tool install` 和 `uvx` 运行

[0.6.2]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.2
[0.6.1]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.1
[0.6.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.6.0
[0.5.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.5.0
[0.4.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.4.0
[0.3.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.3.0
[0.2.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.2.0
[0.1.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.1.0
