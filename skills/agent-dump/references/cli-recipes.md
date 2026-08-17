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
uv run agent-dump --list -query "bug provider:codex role:user path:. limit:20"
uv run agent-dump --list "agents://.?q=refactor&providers=codex,claude&roles=user&limit=20"
uv run agent-dump --list --lang en
```

说明：仅使用 `-days` 或 `-query` 且未指定 `--interactive` 时，CLI 会自动按 `--list` 处理。

### URI 直读 / 单会话导出（uri）

```bash
# 默认 print 到终端
uv run agent-dump opencode://<session_id>
uv run agent-dump zcode://<session_id>
uv run agent-dump codex://<session_id>
uv run agent-dump codex://threads/<session_id>
uv run agent-dump kimi://<session_id>
uv run agent-dump claude://<session_id>
uv run agent-dump cursor://<request_id>
uv run agent-dump pi://<session_id>

# 导出单会话
uv run agent-dump codex://<session_id> --format json --output ./my-sessions
uv run agent-dump codex://<session_id> --format md --output ./my-sessions
uv run agent-dump codex://<session_id> --format print,json --output ./my-sessions
uv run agent-dump codex://<session_id> --format print,json --summary --output ./my-sessions
uv run agent-dump codex://<session_id> --format json,markdown,raw --output ./my-sessions
uv run agent-dump cursor://<request_id> --format print,json --output ./my-sessions
uv run agent-dump codex://<session_id> --head
```

### 汇总分析（collect）

```bash
uv run agent-dump --collect
uv run agent-dump --collect -days 7
uv run agent-dump --collect -since 2026-03-01 -until 2026-03-05
uv run agent-dump --collect -since 20260301 -until 20260305
uv run agent-dump --collect --collect-mode insight
uv run agent-dump --collect "agents://.?q=refactor&providers=codex,claude"
uv run agent-dump --collect --dry-run --save ./reports
```

### 统计（stats）

```bash
uv run agent-dump --stats
uv run agent-dump --stats -days 30
```

### Provider 能力发现

```bash
uv run agent-dump --providers
uv run agent-dump --capabilities
```

输出包含 URI scheme、支持及不支持的导出格式、存储级关键词快路径，以及逐项本地搜索路径状态；不会扫描会话内容。

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
- keyword 在归一化空白后作为一个不区分大小写的字面短语，在标题或逻辑 transcript 中匹配。

当前 agent 名称：
- `opencode`
- `zcode`
- `codex`
- `kimi`
- `claudecode`
- `cursor`
- `pi`

示例：

```bash
uv run agent-dump --list -query "timeout"
uv run agent-dump --list -query "codex,kimi:timeout"
uv run agent-dump --list -query "bug provider:codex role:user path:. limit:20"
uv run agent-dump "agents://.?q=timeout&providers=codex,claude&roles=user&limit=20"
```

结构化查询字段：
- `provider:` 限定 provider，支持逗号分隔；`claude` 会映射到 `claudecode`。
- `role:` 限定消息角色，支持逗号分隔。
- `path:` / `cwd:` 限定项目路径，支持相对路径、绝对路径和 `~`。
- `limit:` 对最终全局匹配结果集截断，且必须为有符号 64 位范围内的正整数。

### `--search`（全文搜索）

- 基于 SQLite FTS5 的本地全文搜索，覆盖标题、消息、reasoning、tool state。
- 按空白切分的 distinct term 均按字面量匹配（不解释 `AND`/`NEAR`/`*` 等 FTS5 操作符语法），全部 term 必须命中，但可以分别落在标题与逻辑 transcript 中；CJK term 必须连续。
- 双分词器：`unicode61` 处理 CJK，`trigram` 处理三字符以上的非 CJK 子串；无法等价表达的输入使用同一逻辑 matcher。
- 索引按 Provider-owned change signal 增量更新；FTS5 不可用时回退到 O(n) 逻辑 transcript 扫描；索引错误会在 stderr 提示并建议 `--reindex`。
- 作为列表搜索模式使用，可与 `--list`、`-days`、`-query` 组合。

示例：

```bash
uv run agent-dump --search "auth timeout"
uv run agent-dump --search "认证"
uv run agent-dump --search "auth" --list -days 30
```

## 3) 行为矩阵（避免误用）

| 场景 | 默认格式 | 关键规则 |
|---|---|---|
| URI 模式（给定 session URI） | `print` | 可显式改为 `json/markdown/raw`，也可组合 `print,json`；支持 `codex://threads/<session_id>`；Cursor URI 支持 `json/print`；`--head` 输出有界发现元数据，消息数可能为未知 |
| `agents://` 查询 URI | N/A | 可配合 list、interactive 或 collect 使用；支持 `q/providers/roles/limit` |
| 非 URI 模式 | `json` | 主要配合 `--interactive` 使用 |
| `--list` 模式 | N/A | 仅列出，不导出；`--format/--output` 会被忽略并警告 |
| `--interactive` 模式 | `json` | 支持 `json/markdown/raw`，不接受 `print` |
| `--stats` 模式 | N/A | 推荐独立使用；支持 `-days` 与 `-query` |
| `--providers` / `--capabilities` | N/A | 只读展示全部注册 provider 的能力与本地路径状态，不扫描会话 |
| `--collect` 模式 | N/A | 可接受 `agents://...` 查询 URI；支持 `-days`、`-since/-until`、`--collect-mode pm/insight`、`--dry-run`、`--save`；普通 session URI、`--interactive`、`--list` 会触发冲突 |
| `--search` 模式 | N/A | 作为列表搜索模式使用；可与 `--list`、`-days`、`-query` 组合 |
| `--reindex` | N/A | 独立的索引维护命令，不应与其他模式标志组合 |

补充：
- `-p/-page-size` 参数为兼容保留，当前不生效。
- `--lang` 支持 `en` 与 `zh`；诊断与用户可见文案跟随 locale。
- `md` 是 `markdown` 的别名。
- `--head` 仅 URI 模式可用，用于查看有界发现元数据，不重读完整正文；消息数可能明确为未知。不能与 `--format` 或 `--summary` 组合。
- `--summary` 仅 URI 模式可用，且需 `--format` 包含 `json`。
- `--collect-mode` 默认 `pm`，`insight` 用于作者洞察视角。
- `--collect` 日期优先级为显式 `-since/-until` > 显式 `-days` > 缺省当天。
- 结构化 `role:` 查询的 snippet 只来自允许角色的消息，不会混入无角色维度的 FTS 证据。
- 退出码：`0` 成功（含合法空结果、交互式导出部分成功）；`1` 无法完成请求（无 provider 数据、URI 未命中、交互式导出全部失败、参数组合非法）；`2` 用法错误。

## 4) 常见错误与处理

### URI 格式非法

现象：
- URI 不匹配 `<scheme>://<session_id>`
- 或 scheme 不在支持列表中

处理：
1. 改为受支持格式：
   - `opencode://<session_id>`
   - `zcode://<session_id>`
   - `codex://<session_id>`
   - `codex://threads/<session_id>`
   - `kimi://<session_id>`
   - `claude://<session_id>`
   - `cursor://<request_id>`
   - `pi://<session_id>`
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
- `--list` / `--stats` / URI 等模式退出码为 `1`，并输出「未找到任何可用的本地会话数据」类诊断。

处理：
1. 确认本地对应工具已有会话数据目录。
2. 重试 `uv run agent-dump --list` 进行快速探测。
3. 不要把该退出码 `1` 与「时间窗内无会话」的退出码 `0` 混为一谈。

### 无匹配会话

现象：
- `-days` 时间窗内无会话，或 `-query` / `--search` 过滤后为空。
- 退出码仍为 `0`（合法空结果）。

处理：
1. 扩大时间窗（例如 `-days 30`）。
2. 放宽关键词或移除 agent 限定范围。

### query 语法非法

现象：
- `-query` 使用了无效 agent 名称或格式不正确。

处理：
1. 改为 `keyword` 或 `agent1,agent2:keyword`。
2. 将 agent 名称改为 `opencode/zcode/codex/kimi/claudecode/cursor/pi` 中的合法值。

### collect 模式参数冲突

现象：
- `--collect` 与普通 session URI、`--interactive` 或 `--list` 同时出现。

处理：
1. 保留 `--collect` 与可选的 `agents://...` 查询 URI、`-since/-until`、`--collect-mode`、`--dry-run`、`--save`。
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
