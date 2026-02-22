# 更新日志

## [未发布]

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

[0.2.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.2.0
[0.1.0]: https://github.com/xingkaixin/agent-dump/releases/tag/v0.1.0
