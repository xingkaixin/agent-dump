# agent-dump CLI Recipes

## 1) 常用命令模板

### 交互式导出（interactive）

```bash
uv run agent-dump --interactive
uv run agent-dump --interactive -days 3
uv run agent-dump --interactive -query "修复"
uv run agent-dump --interactive -format json -output ./sessions
uv run agent-dump --interactive -format md -output ./my-sessions
uv run agent-dump --interactive --lang zh
```

### 列表查询（list）

```bash
uv run agent-dump --list
uv run agent-dump --list -days 7
uv run agent-dump --list -query "error"
uv run agent-dump --list -query "codex,kimi:error"
uv run agent-dump --list --lang en
```

说明：仅使用 `-days` 或 `-query` 且未指定 `--interactive` 时，CLI 会自动按 `--list` 处理。

### URI 直读 / 单会话导出（uri）

```bash
# 默认 print 到终端
uv run agent-dump opencode://<session_id>
uv run agent-dump codex://<session_id>
uv run agent-dump codex://threads/<session_id>
uv run agent-dump kimi://<session_id>
uv run agent-dump claude://<session_id>

# 导出单会话
uv run agent-dump codex://<session_id> --format json --output ./my-sessions
uv run agent-dump codex://<session_id> --format md --output ./my-sessions
```

## 2) 查询语法（-q / -query）

- 关键词查询：`-query "keyword"`
- 指定 agent 范围查询：`-query "agent1,agent2:keyword"`

当前 agent 名称：
- `opencode`
- `codex`
- `kimi`
- `claudecode`

示例：

```bash
uv run agent-dump --list -query "timeout"
uv run agent-dump --list -query "codex,kimi:timeout"
```

## 3) 行为矩阵（避免误用）

| 场景 | 默认格式 | 关键规则 |
|---|---|---|
| URI 模式（给定 `uri`） | `print` | 可显式改为 `json/md` 并导出到 `--output` |
| 非 URI 模式 | `json` | 主要配合 `--interactive` 使用 |
| `--list` 模式 | N/A | 仅列出，不导出；`--format/--output` 会被忽略并警告 |
| `--interactive` 模式 | `json` | 仅支持 `json/md`，不接受 `print` |

补充：
- `-p/-page-size` 参数目前在 `--list` 模式下保留兼容，不生效。
- `--lang` 支持 `en` 与 `zh`。

## 4) 常见错误与处理

### URI 格式非法

现象：
- URI 不匹配 `<scheme>://<session_id>`
- 或 scheme 不在支持列表中

处理：
1. 改为受支持格式：
   - `opencode://<session_id>`
   - `codex://<session_id>`
   - `codex://threads/<session_id>`
   - `kimi://<session_id>`
   - `claude://<session_id>`
2. 确认 `<session_id>` 非空。

### URI 协议与实际会话来源不匹配

现象：
- 会话能找到，但 URI scheme 对应的 agent 与真实 agent 不一致。

处理：
1. 改用真实 agent 的 URI scheme。
2. 重新执行同一导出命令。

### 无可用 agent

现象：
- 扫描后没有可用 agent 数据源。

处理：
1. 确认本地对应工具已有会话数据目录。
2. 重试 `uv run agent-dump --list` 进行快速探测。

### 无匹配会话

现象：
- `-days` 时间窗内无会话，或 `-query` 过滤后为空。

处理：
1. 扩大时间窗（例如 `-days 30`）。
2. 放宽关键词或移除 agent 限定范围。

### query 语法非法

现象：
- `-query` 使用了无效 agent 名称或格式不正确。

处理：
1. 改为 `keyword` 或 `agent1,agent2:keyword`。
2. 将 agent 名称改为 `opencode/codex/kimi/claudecode` 中的合法值。
