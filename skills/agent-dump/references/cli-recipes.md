# agent-dump CLI Recipes

## 1) 常用命令模板

### 交互式导出（interactive）

```bash
uv run agent-dump --interactive
uv run agent-dump --interactive -days 3
uv run agent-dump --interactive -query "修复"
uv run agent-dump --interactive -format json -output ./sessions
uv run agent-dump --interactive -format md -output ./my-sessions
uv run agent-dump --interactive --format json,markdown,raw -output ./my-sessions
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
uv run agent-dump codex://<session_id> --format print,json --output ./my-sessions
uv run agent-dump codex://<session_id> --format print,json --summary --output ./my-sessions
uv run agent-dump codex://<session_id> --format json,markdown,raw --output ./my-sessions
```

### 汇总分析（collect）

```bash
uv run agent-dump --collect
uv run agent-dump --collect -since 2026-03-01 -until 2026-03-05
uv run agent-dump --collect -since 20260301 -until 20260305
```

### 统计（stats）

```bash
uv run agent-dump --stats
uv run agent-dump --stats -days 30
```

### 搜索（search）

```bash
# Full-text search across all sessions
uv run agent-dump --search "auth timeout"
uv run agent-dump --search "认证"

# Combine with list + days
uv run agent-dump --search "auth" --list -days 30

# Rebuild index
uv run agent-dump --reindex
```

### 配置管理（config）

```bash
uv run agent-dump --config view
uv run agent-dump --config edit
```

## 2) 查询语法

### `-q` / `-query`（过滤查询）

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

### `--search`（全文搜索）

- 基于 SQLite FTS5 的本地全文搜索，覆盖标题、消息、reasoning、tool state。
- 双分词器：`unicode61` 处理西文，`trigram` 处理 CJK 与模糊匹配。
- 索引基于源文件 mtime 增量更新；FTS5 不可用时回退到 O(n) 文件扫描。
- 可与 `--list` 组合使用；不能与 URI、`--interactive`、`--collect`、`--stats` 同时使用。

示例：

```bash
uv run agent-dump --search "auth timeout"
uv run agent-dump --search "认证"
uv run agent-dump --search "auth" --list -days 30
```

## 3) 行为矩阵（避免误用）

| 场景 | 默认格式 | 关键规则 |
|---|---|---|
| URI 模式（给定 `uri`） | `print` | 可显式改为 `json/markdown/raw`，也可组合 `print,json`；支持 `codex://threads/<session_id>` |
| 非 URI 模式 | `json` | 主要配合 `--interactive` 使用 |
| `--list` 模式 | N/A | 仅列出，不导出；`--format/--output` 会被忽略并警告 |
| `--interactive` 模式 | `json` | 支持 `json/markdown/raw`，不接受 `print` |
| `--stats` 模式 | N/A | 不能与 URI/`--interactive`/`--list`/`--collect` 同时使用 |
| `--collect` 模式 | N/A | 不能与 URI/`--interactive`/`--list` 同时使用 |
| `--search` 模式 | N/A | 不能与 URI/`--interactive`/`--collect`/`--stats` 同时使用。可与 `--list` 组合 |
| `--reindex` | N/A | 独立的索引维护命令，不应与其他模式标志组合 |

补充：
- `-p/-page-size` 参数目前在 `--list` 模式下保留兼容，不生效。
- `--lang` 支持 `en` 与 `zh`。
- `md` 是 `markdown` 的别名。
- `--summary` 仅 URI 模式可用，且需 `--format` 包含 `json`。

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

### collect 模式参数冲突

现象：
- `--collect` 与 URI、`--interactive` 或 `--list` 同时出现。

处理：
1. 仅保留 `--collect` 与可选的 `-since/-until`。
2. 将导出/列表操作拆成单独命令执行。

### summary 配置缺失或不完整

现象：
- URI 命令携带 `--summary`，但 AI 配置文件缺失或字段不完整。

处理：
1. 先执行 `uv run agent-dump --config view` 检查状态。
2. 再执行 `uv run agent-dump --config edit` 补齐 `provider/base_url/model/api_key`。
3. 若当前只需导出，可去掉 `--summary`，CLI 会继续完成导出。

### format 语法非法

现象：
- `--format` 含不支持值或空片段（例如 `json,foo`、`json,,raw`）。

处理：
1. 仅使用 `json/markdown/raw/print`（支持逗号组合）。
2. 需要 markdown 简写时使用 `md`（等价 `markdown`）。
