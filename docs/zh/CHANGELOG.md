# 更新日志

## [未发布]

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

[0.3.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.3.0
[0.2.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.2.0
[0.1.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.1.0
