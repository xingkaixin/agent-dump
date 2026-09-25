![logo](https://raw.githubusercontent.com/xingkaixin/agent-dump/refs/heads/main/assets/logo.png)

# Agent Dump

AI 编码助手会话导出工具 - 支持从多种 AI 编码工具导出 JSON、Markdown、raw，并通过 URI 直接打印会话内容。

操作教程：[将 Codex 会话导出为 Markdown](https://agent-dump.xingkaixin.me/zh/guides/export-codex-session/)。

## 支持的 AI 工具

- **OpenCode** - 开源 AI 编程助手
- **ZCode** - ZCode 编码助手会话
- **Claude Code** - Anthropic 的 AI 编码工具
- **Codex** - OpenAI 的命令行 AI 编码助手
- **Kimi** - Moonshot AI 助手
- **Cursor** - Cursor composer 会话
- **Pi** - Earendil 的 AI coding agent
- **DeepChat** - 当前版本的本地会话（未加密数据库）
- **Cherry Studio** - 2.x 的本地聊天和 Agent 会话
- **MiniMax Code** - 当前 CLI 的本地 SQLite 会话
- **更多工具** - 欢迎提交 PR 支持其他 AI 编码工具

## 功能特性

- **交互式选择**: 使用 Ratatui 提供友好的命令行交互界面
- **多 Agent 支持**: 自动扫描多种 AI 工具的会话数据
- **批量导出**: 支持导出最近 N 天的所有会话
- **指定导出**: 通过会话 URI 导出特定会话
- **会话列表**: 仅列出会话而不导出
- **直接文本查看**: 通过 URI 直接在终端查看会话内容（如 `agent-dump opencode://session-id`）
- **统计数据**: 导出包含 tokens 使用量、成本等统计信息
- **消息详情**: 完整保留会话消息、工具调用等详细信息
- **智能标题提取**: 从各 Agent 元数据中自动提取会话标题
- **会话统计**: `--stats` 查看按 Agent 和时间分组的会话使用统计
- **全文搜索**: 基于 SQLite FTS5 的本地全文搜索，覆盖标题、消息、reasoning 和 tool state (`--search`)；检索词按字面量匹配
- **带证据的搜索结果**: 搜索结果包含匹配度、URI、更新时间与高亮命中片段
- **可执行诊断**: CLI 错误会展示已检查路径、URI 解析字段、能力缺口和下一步建议（文案随 `--lang en|zh` 本地化）

## 路径发现

`agent-dump` 大多数 provider 按以下顺序解析会话数据根目录：官方环境变量 → 工具默认目录 → 本地开发回退路径 `data/<agent>`。ZCode 当前只使用 macOS/Windows 默认数据库路径。

- **Codex**: `CODEX_HOME` -> `~/.codex` -> `data/codex`
- **Claude Code**: `CLAUDE_CONFIG_DIR` -> `~/.claude` -> `data/claudecode`
- **Kimi**: `KIMI_SHARE_DIR` -> `~/.kimi` -> `data/kimi`
- **OpenCode**: `OPENCODE_DB` 指定唯一数据库（相对路径以 `XDG_DATA_HOME/opencode` 或 `~/.local/share/opencode` 为基准）；未指定时读取该目录的 `opencode.db`，再回退到旧 Windows `LOCALAPPDATA`/`APPDATA` 路径和 `data/opencode/opencode.db`。
- **ZCode**: macOS `~/.zcode/cli/db/db.sqlite`；Windows `%USERPROFILE%\.zcode\cli\db\db.sqlite`；Linux 无默认路径
- **Cursor**: Cursor 默认用户目录下的 `globalStorage/state.vscdb`
- **Pi**: `PI_HOME` -> `~/.pi` -> `data/pi`
- **DeepChat**: `DEEPCHAT_USER_DATA_DIR/app_db/agent.db`；默认 macOS `~/Library/Application Support/DeepChat/app_db/agent.db`、Windows `%APPDATA%\DeepChat\app_db\agent.db`、Linux `${XDG_CONFIG_HOME:-~/.config}/DeepChat/app_db/agent.db`。
- **Cherry Studio**: `CHERRY_STUDIO_USER_DATA_DIR/Data/cherrystudio.sqlite`；未指定时，依次检查 `~/.cherrystudio/boot-config.json` 中配置的用户数据目录，再检查平台默认目录，使用第一个存在的数据库。默认目录为 macOS `~/Library/Application Support/CherryStudio`、Windows `%APPDATA%\CherryStudio`、Linux `${XDG_CONFIG_HOME:-~/.config}/CherryStudio`，数据库均位于其下的 `Data/cherrystudio.sqlite`。该覆盖变量由 agent-dump 提供，可用于便携版、开发版或选择多个安装中的一个。
- **MiniMax Code**: `MINIMAX_DATA_DIR` → `MAVIS_DATA_DIR` → `~/.minimax`；数据库位于所选目录的 `v2/sqlite/runtime-state.sqlite`。只选择一个目录，显式路径不存在时不回退。

注意：

- Windows 上建议优先配置工具官方环境变量。
- `data/<agent>` 回退路径保留用于本地开发和测试。

DeepChat 支持当前 `agent.db` 中的已保存会话（含已迁移的历史会话、ACP 会话和子会话），忽略草稿。支持列表、查询、搜索、统计、collect，以及 print / JSON / Markdown 导出。优先读取结构化消息，缺失时回退到 `content`；保留正文、思考和工具记录，压缩提示不进入 collect。JSON 还保留附件引用、链接及其他消息块，不读取附件实体或外置工具输出文件。Token 来自消息记录，不提供计费金额。

暂不支持 SQLCipher 加密库、旧版 `chat.db` 直读和 raw 导出；不会执行 DeepChat 的迁移或 Tape 恢复。`DEEPCHAT_USER_DATA_DIR` 可用于指定自定义用户数据目录。

Cherry Studio 支持当前 2.x 数据库中的普通聊天和 Agent 会话（含已迁移历史），可用于列表、查询、搜索、统计、collect，以及 print / JSON / Markdown 导出。普通聊天仅包含当前选中的根到叶路径，其他分支和多模型并列回复不进入导出、搜索或计数；虚拟根和空的待输入叶节点不计入消息。Agent 会话按时间排序，并从 workspace 获取工作目录；普通聊天不推断工作目录。已删除会话和聊天消息不会导出。

正文、思考、工具调用及结果、代码和翻译会转换为统一格式。JSON 保留附件引用和控制事件，压缩摘要与内部事件不进入 collect 或搜索。Token 来自消息统计；各币种费用仅在 JSON 中保留，不换算或汇总计费金额。不读取附件实体、SDK 日志，也不执行应用迁移。暂不支持 1.x IndexedDB/Redux 原始数据和 raw 导出。

MiniMax Code 支持当前 CLI 已迁移展示消息的列表、查询、搜索、统计、collect 及 print / JSON / Markdown 导出。包含可见的普通会话、子任务和归档会话，排除隐藏及 peek/channel/cron 内部会话。正文按数据库消息行顺序读取，保留文字、思考、工具状态/结果和附件引用；压缩、审查和系统事件不进入 collect 或搜索。模型来自会话元数据，缺失时显示未知；JSON 保留消息中已记录的 token 用量，不推算费用。

自定义 profile、早期源码版 `~/.minimax-code` 或其他目录需显式设置 `MINIMAX_DATA_DIR`。不读取模型上下文 JSONL、附件实体，不执行迁移或恢复已回退删除的正文；暂不支持 raw、旧存储直读和桌面端数据。尚未完成迁移或损坏的会话会报告错误，不会被当成空会话。实现与验收范围见 [MiniMax Code 功能设计](docs/minimax-provider-design.md)。

OpenCode 支持旧版 SQLite 和 2.x `session_v2/session_message`。新旧表共存时同 ID 优先新版，旧版独有会话继续可读；新版消息按 `seq` 排序，消息数包含系统和状态记录。合成输入、系统/技能、压缩与 shell 记录不进入 collect。自定义或 channel 数据库使用 `OPENCODE_DB` 指定，显式路径缺失不回退，`:memory:` 不可用。附件保留在 JSON 元数据中，不打开引用文件。运行中和归档记录仍可读取，待投递 inbox 不计入会话。raw 仍是标准化 `.raw.json`，不是 OpenCode import 文件。详见[功能设计与验收范围](docs/opencode-v2-design.md)。

## 安装

本分支将安装制品切换为 Rust；已发布的 0.15.9 仍为 Python，直到新的 Rust 版本正式发布。Rust wheel 仅提供 `agent-dump` 命令，不包含 Python 导入 API，也不提供 `python -m agent_dump`。依赖旧 API 的程序可固定 `agent-dump==0.15.9`。

支持 macOS x64/arm64、Linux x64（glibc ≥ 2.17）和 Windows x64。Linux musl/Alpine 没有预构建 wheel。wheel 安装无需 Rust 编译器；从 Git/sdist 构建需要 Rust 1.90.0 和 C 工具链。

```bash
pip install agent-dump
```

### 方式一：使用 uv tool 安装（推荐）

```bash
# 从 PyPI 安装（发布后可使用）
uv tool install agent-dump

# 从 GitHub 直接安装
uv tool install git+https://github.com/xingkaixin/agent-dump
```

### 方式二：使用 uvx 直接运行（无需安装）

```bash
# 从 PyPI 运行（发布后可使用）
uvx agent-dump --help

# 从 GitHub 直接运行
uvx --from git+https://github.com/xingkaixin/agent-dump agent-dump --help
```

### 方式三：使用 bunx / npx 直接运行（无需 Python）

```bash
# 从 npm 直接运行
bunx @agent-dump/cli --help
npx @agent-dump/cli --help
```

`bunx`、`npx` 以及 npm/pnpm/Bun 全局安装路径都需要 Node.js 22 或更高版本。
这些入口会先执行同一个 Node.js 包装器，再启动原生二进制文件。

`@agent-dump/cli` 通过 npm 下载当前平台包，因此会沿用 scoped registry、认证、代理与 CA 配置，
并在落盘前校验发布时生成的 checksum。

当前支持的平台：

<!-- native-targets:start -->
- `darwin-x64`
- `darwin-arm64`
- `linux-x64`
- `win32-x64`
<!-- native-targets:end -->

若平台暂不支持，wrapper 会输出当前检测到的 `platform/arch`，并提示前往 GitHub Releases 页面。

### 方式四：本地开发

```bash
# 克隆仓库
git clone https://github.com/xingkaixin/agent-dump.git
cd agent-dump

# 构建原生命令行程序
cargo build --locked --release

# 本地安装测试
uv tool install . --force
```

### 方式五：安装为 Skill 使用

```bash
npx skills add xingkaixin/agent-dump
```

## 使用方法

### 交互式导出

```bash
# 进入交互模式选择和导出会话
agent-dump --interactive

# 或使用源码构建的原生程序
./target/release/agent-dump --interactive
```

运行后会显示最近 7 天的会话列表，按时间分组显示（今天、昨天、本周、本月、更早）。使用空格选择/取消，回车确认导出。

> **注意：** 从 v0.3.0 开始，默认行为已更改。直接运行 `agent-dump` 将显示帮助信息，需要使用 `--interactive` 进入交互模式。
>
> 如果同时传入多个显式模式，agent-dump 会保留既有模式优先级，并告警列出被忽略的较低优先级参数。

### URI 模式（直接文本查看）

无需导出文件，直接在终端查看会话内容：

```bash
# 通过 URI 查看指定会话
agent-dump opencode://session-id-abc123

# URI 格式在列表模式和交互选择器中显示
#   • 会话标题 (opencode://session-id-abc123)
```

支持的 URI 协议：
- `opencode://<session_id>` - OpenCode 会话
- `zcode://<session_id>` - ZCode 会话
- `codex://<session_id>` - Codex 会话
- `codex://threads/<session_id>` - Codex 会话
- `kimi://<session_id>` - Kimi 会话
- `claude://<session_id>` - Claude Code 会话
- `cursor://<requestid>` - Cursor 会话（`requestid` 作为 URI 标识符）
- `pi://<session_id>` - Pi 会话
- `deepchat://<session_id>` - DeepChat 会话
- `cherry://topic-<id>` / `cherry://session-<id>` - Cherry Studio 普通聊天 / Agent 会话
- `minimax://<session_id>` - MiniMax Code CLI 会话

### 典型错误

`agent-dump` 输出可操作的结构化诊断，而不是一行笼统的失败信息。文案跟随 CLI locale
（`--lang en|zh`）。常见示例：

```text
诊断信息
结论: 未找到任何可用的本地会话数据。
已检查路径:
  - Codex: CODEX_HOME/sessions: /Users/me/.codex/sessions
  - OpenCode: XDG/default opencode.db: /Users/me/.local/share/opencode/opencode.db
下一步:
  - 确认对应 agent 已在本机生成过会话数据。
  - 若使用自定义目录，检查相关环境变量是否指向正确位置。
```

```text
诊断信息
结论: 未找到匹配的会话。
解析后的 URI: codex://session-123
  - scheme: codex
  - session_id: session-123
证据:
  - 已扫描当前可用 provider，但未匹配到该 session id。
下一步:
  - 先运行 `agent-dump --list` 确认该会话是否仍存在。
  - 检查 URI 中的 session id 是否完整且对应正确 provider。
```

```text
诊断信息
结论: 当前 URI 请求了 Cursor 不支持的导出能力。
缺失能力: Cursor URI 仅支持 json, print；当前请求了 raw
下一步:
  - 移除 `raw`，改用支持的格式。
  - 若需要进一步处理，先导出 JSON 再做转换。
```

### 退出码

显式 Provider 范围（`provider:`、旧式 Provider 前缀或查询 URI 的 `providers=`）在发现会话前生效，不扫描未选中的 Provider。范围内无会话时按对应模式的无匹配行为处理，不探测其他来源。

| 退出码 | 含义 |
|------|------|
| `0` | 命令做到了被要求的事——包括结果集本就为空（`-days` 窗口内没有会话、关键词或 `--search` 没有命中），以及交互式导出部分成功。 |
| `1` | 命令做不到被要求的事：本机不存在任何 provider 数据、URI 未能解析到会话、交互式导出全部失败、或参数组合非法。 |
| `2` | 参数用法错误，由 `argparse` 抛出（未知参数、非法的 `--format` 值）。 |

这样 `agent-dump --list && ...` 才有意义：列出了会话就成功，因为没有任何 provider
数据而无从列出则失败。

## 命令行参数

```bash
# 显示帮助
agent-dump                             # 显示帮助信息
agent-dump --help                      # 显示详细帮助

# 列表模式（输出全部匹配内容，不分页）
agent-dump --list                      # 列出最近 7 天的会话
agent-dump --list -days 3              # 列出最近 3 天的会话
agent-dump --list -query 报错          # 列出匹配关键词“报错”的会话
agent-dump --list -query codex,kimi:报错  # 仅在 Codex/Kimi 范围内查询
agent-dump --list -query 'bug provider:codex path:. limit:20'  # 结构化查询：关键词 + provider + path
agent-dump --interactive -query 'role:user limit:20 refactor'  # 结构化查询带 role 和全局 limit
agent-dump 'agents://.?q=refactor&providers=codex,claude'  # 查询当前仓库最近的相关会话
agent-dump 'agents://.?q=refactor&providers=codex,claude&roles=user&limit=20'  # 结构化查询 URI
agent-dump --list 'agents:///Users/me/work/repo?providers=codex,opencode'  # 按绝对路径查询
agent-dump --interactive 'agents://~/work/repo?q=bug'  # 按路径作用域进入交互式选择
agent-dump --list -page-size 10        # 参数保留兼容，当前不生效

# 交互式导出模式
agent-dump --interactive               # 交互模式（默认 7 天）
agent-dump --interactive -days 3       # 交互模式（3 天）
agent-dump -days 3                     # 自动启用列表模式
agent-dump -query 报错                 # 自动启用列表模式

# 说明：interactive + --query 时，Agent 列表仅显示命中关键词的工具，
#       且括号内会话数量为过滤后的命中数量。
#
# 查询歧义规则：
# - `error:timeout` 仍是纯关键词查询。
# - `codex,kimi:报错` 仍是旧版 agent 限定查询语法。
# - 仅当已知 key 出现时才激活结构化模式：provider / role / path / cwd / limit。
# - `role:...` 将关键词匹配限制在指定角色的消息中。
# - `limit:...` 截断最终全局匹配结果集。

# URI 模式 - 直接查看会话内容
agent-dump opencode://<session-id>     # 查看 OpenCode 会话内容
agent-dump zcode://<session-id>        # 查看 ZCode 会话内容
agent-dump codex://<session-id>        # 查看 Codex 会话内容
agent-dump kimi://<session-id>         # 查看 Kimi 会话内容
agent-dump claude://<session-id>       # 查看 Claude Code 会话内容
agent-dump cursor://<request-id>       # 查看 Cursor 会话内容
agent-dump pi://<session-id>           # 查看 Pi 会话内容
agent-dump deepchat://<session-id>     # 查看 DeepChat 会话内容
agent-dump minimax://<session-id>      # 查看 MiniMax Code 会话
agent-dump codex://<session-id> --head # 查看轻量会话元数据，不导出也不打印正文
agent-dump codex://<session-id> --format json --output ./my-sessions  # 导出 JSON 文件
agent-dump codex://<session-id> --format markdown --output ./my-sessions  # 导出 Markdown 文件
agent-dump codex://<session-id> --format print,json --output ./my-sessions # 打印并导出 JSON
agent-dump codex://<session-id> --format json,markdown,raw --output ./my-sessions  # 同时导出多种格式
agent-dump cursor://<request-id> --format json --output ./my-sessions  # Cursor 支持 JSON 导出
agent-dump cursor://<request-id> --format print,json --output ./my-sessions # Cursor 打印 + JSON
agent-dump codex://<session-id> --format json --summary --output ./my-sessions  # 导出包含 AI summary 的 JSON
agent-dump codex://<session-id> --format print,json --summary --output ./my-sessions # 打印并导出带 summary 的 JSON

# 搜索模式（全文搜索）
agent-dump --search "auth timeout"           # 搜索匹配关键词的会话
agent-dump --search "认证"                    # 支持 CJK 关键词搜索
agent-dump --search "auth" --list -days 30   # 与 list + days 组合
agent-dump --reindex                         # 强制重建搜索索引

# 说明：搜索结果会展示来源、更新时间、URI、匹配度和高亮命中片段。

# 统计模式
agent-dump --stats                     # 显示最近 7 天会话统计
agent-dump --stats -days 30            # 显示最近 30 天会话统计

# Provider 能力矩阵（只读；--capabilities 是别名）
agent-dump --providers

# collect 模式（按时间段汇总并调用 AI 总结）
agent-dump --collect
agent-dump --collect -days 7
agent-dump --collect -since 2026-03-01 -until 2026-03-05
agent-dump --collect -since 20260301 -until 20260305
agent-dump --collect --collect-mode insight
agent-dump --collect --save ./reports
agent-dump --collect --save ./reports/weekly.md
agent-dump --collect --save /tmp/agent-dump-reports
agent-dump --collect --save /tmp/agent-dump-reports/weekly.md
agent-dump --collect 'agents://.?q=refactor&providers=codex,claude'
agent-dump --collect --dry-run -since 20260301 -until 20260305 --save ./reports
agent-dump --shortcut ob 20260408

# 说明：--collect 只保留 user/assistant 的可见文本，排除 system/developer/tool 消息、
#       reasoning、plan、工具调用和工具结果；投影后为空的 session 直接忽略。
#       PM chunk 只提取 requests、decisions、Agent 明确报告的 outcomes，再做 session 级归并，
#       最后在同一日期/项目内归并（insight 按 session），保留归属后生成 Markdown。
#       最终输入超过 64,000 字符时需要缩小日期范围或查询条件，不会静默丢弃来源。
# 说明：collect 日期优先级为显式 -since/-until，其次显式 -days，最后缺省为当天。
# 说明：--collect --dry-run 会完成扫描、查询过滤和 chunk planning，并输出 provider 分布、
#       session 数、chunk 数、并发配置、日期范围和保存路径预览。
# 说明：--collect 会在 stderr 输出多阶段进度，包括 scan_sessions、plan_chunks、
#       summarize_chunks、merge_sessions、tree_reduction、render_final、write_output。
# 说明：无法读取的会话会在 stderr 告警；可读取但没有可见对话的会话会直接忽略。
# 说明：collect 输出文件名示例：agent-dump-collect-20260301-20260305.md。
# 说明：--save 接受目录或 .md 文件路径。缺失的非 .md 路径会被当作目录处理。

# 配置模式
agent-dump --config view
agent-dump --config edit

# 其他选项
agent-dump --interactive --format json # 交互式导出 JSON（默认）
agent-dump --interactive --format markdown   # 交互式导出 Markdown
agent-dump --interactive --format json,markdown,raw # 交互式多格式导出
agent-dump --interactive -output ./my-sessions  # 指定输出目录

# 兼容说明
# md 仍可作为 markdown 的别名使用，例如：--format md,raw
# --head 是 URI 发现模式，不能替代 --format print，也不能与 --format/--summary 组合。
```

### 交给外部 agent 汇总

不配置大模型 API，也不依赖 skill，可以直接生成一份外部 agent 能执行的汇总提示词：

```bash
agent-dump --collect --emit-prompt \
  -since 20260824 -until 20260830 \
  --collect-mode pm --save ./reports/weekly.md

# 已有 collect shortcut 也可以临时启用
agent-dump --shortcut ob 20260831 --emit-prompt
```

上面的命令直接输出提示词。交给 agent 执行时，推荐**首次运行就把 stdout 和 stderr 分别保存到私有文件**，
避免候选清单被命令工具的输出上限截断。macOS/Linux 的 shortcut 示例（不需要新增 CLI 参数）：

```bash
(
  umask 077
  collect_task_dir=$(mktemp -d) || exit 1
  agent-dump --shortcut ob 20260831 --emit-prompt \
    > "$collect_task_dir/prompt.md" 2> "$collect_task_dir/diagnostics.txt"
  collect_exit_code=$?
  printf 'Exit: %s\nPrompt: %s\nDiagnostics: %s\n' \
    "$collect_exit_code" "$collect_task_dir/prompt.md" "$collect_task_dir/diagnostics.txt"
  exit "$collect_exit_code"
)
```

将返回的两个文件路径交给 agent，让它读取说明、用脚本校验完整清单并分批处理，不要再次把整个文件打印进工具输出。
其他平台也应使用私有临时目录、分别保存两个输出流，并检查退出码。

把提示词交给能在原本地环境中执行命令、读取会话和写文件的 agent。
它包含固定候选清单、逐会话读取命令、工作目录、时区、现有 `pm`/`insight` 报告要求和最终绝对路径。
读取命令使用生成时的原生程序，无需另外全局安装 `agent-dump`；需要保留原来的 provider 路径环境变量。
如果原运行程序已不可用，应先确认新的可用入口。

- stdout 只输出提示词，诊断走 stderr；`--save` 仍是**最终报告路径**，不是提示词文件路径。
- 不校验 AI 配置、不调用模型、不规划摘要 chunk、不创建 collect 日志或报告。内容查询仍可能读取正文并更新本地搜索索引。
- 复用 collect 的排除规则和查询筛选。日期两端均包含，按会话的**本地创建日期**筛选，不按单条消息时间裁剪；清单不是内容快照。
- 读取正文前，核对清单结束标记、候选数量、唯一 URI、JSON 长度和命令对应关系；JSON 能解析不等于清单完整。
  清单损坏时先使用已保存的完整文件；没有完整文件时，仅允许按原筛选条件重新生成一次提示词并直接保存输出。
  重生成是新候选清单，不是恢复旧快照；原条件不明或仍损坏时先询问，未经同意不交付残缺清单的部分日报。
- 外部 agent 将会话 stdout/stderr 分别落盘，分段读到结尾；导出成功不算完整阅读。
  只分析 user/assistant 可见文本，不切换到 JSON 核实工具结果；个别来源不可读时可带覆盖说明交付。
- 没有实质可见对话的来源直接忽略；审批或重复转录只有改变请求、决策或结果时才保留，当前汇总过程不作为被汇总的工作事项。
  覆盖已有报告需要用户明确同意；先完成并核验新内容，再替换旧报告。
- 仅支持 collect 模式，与 `--dry-run` 互斥。候选为空时不输出提示词，退出 `0`；无可用 provider 或准备失败时退出 `1`。
- 要让 shortcut 始终生成提示词，在它的 `args` 中加入 `"--emit-prompt"` 即可，无需其他调整。

模型指令及报告标题与内置 collect 一样使用中文，`--lang` 控制 CLI 帮助和诊断。
提示词包含本地标题和路径，分享时应按私有数据处理；外部处理受对应 agent 的数据传输策略约束，不等于离线处理。
提示词生成成功不代表报告已生成，也不会自动启动外部 agent。

### 完整参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `uri` | 用于直接查看的 Agent Session URI（如 `opencode://session-id`），或作用域查询 URI，如 `agents://.?q=refactor&providers=codex,claude&roles=user&limit=20` | - |
| `--interactive` | 进入交互式模式选择和导出会话 | - |
| `-d`, `-days`, `--days` | 查询最近 N 天的会话，N 必须为日历范围内的正整数。collect 模式下仅在未提供 `-since/-until` 时生效。 | collect 外默认 7；collect 内默认仅当天 |
| `-q`, `-query` | 查询过滤。关键词在归一化空白后作为一个不区分大小写的字面短语，在 Session 标题或逻辑 transcript 内匹配。支持 legacy `keyword` 或 `agent1,agent2:keyword`（如 `codex,kimi:报错`），也支持结构化条件如 `bug provider:codex role:user path:. limit:20`。`cwd:` 是 `path:` 的别名。`limit` 必须为有符号 64 位范围内的正整数。未知结构化 key 会被拒绝。不能与 `agents://...` 查询 URI 同时使用。 | - |
| `--head` | 仅 URI 模式。打印有界发现阶段已有的元数据，不重新读取完整正文；发现阶段完整扫描时消息数为精确值，否则明确显示“未知”。不导出文件也不打印正文。不能与 `--format` 或 `--summary` 组合。 | - |
| `--collect` | 按日期范围采集会话，可选通过 `-query` 或 `agents://...` 查询 URI 约束范围（两者互斥）。只总结 user/assistant 可见文本，排除 system/developer/tool 消息、reasoning、plan、工具调用和工具结果，投影后为空的会话直接忽略。PM 模式提取 requests、decisions 和 Agent 明确报告的 outcomes，再进行 session 归并和 tree reduction。多阶段进度显示在 stderr。 | - |
| `--collect-mode` | collect 输出模式：`pm` 生成项目管理视角总结，`insight` 生成作者洞察视角总结。 | `pm` |
| `--dry-run` | 与 `--collect` 搭配使用，预览 provider 分布、session 数、chunk 数、并发配置、日期范围和保存路径，跳过 AI 请求和文件写入。 | - |
| `--emit-prompt` | 与 `--collect` 搭配使用，输出交给外部 agent 的自包含任务提示词，不需要 AI 配置，不写报告。与 `--dry-run` 互斥；`--save` 指定最终报告位置。 | - |
| `--stats` | 显示最近 N 天会话使用统计，按 Agent 和时间分组。存在未知消息数时显示已知小计与未知会话数，不把部分和冒充总数。支持 `-days` 与 `-query`，推荐独立使用。 | - |
| `--providers`, `--capabilities` | 显示已注册 provider 的能力矩阵，包括 URI scheme、支持及不支持的导出格式、持久索引不可用时采用的存储级关键词回退，以及本地搜索路径是否存在。不扫描会话。 | - |
| `--search` | 基于 SQLite FTS5 的本地全文搜索，覆盖会话标题、消息内容、reasoning 和 tool state。按空白切分的 distinct term 均按字面量匹配（不解释 `AND`/`NEAR`/`*` 等 FTS5 操作符语法），所有 term 都必须存在，但可以分别落在不同 corpus 字段；CJK term 必须连续。FTS5 不可用或 tokenizer 无法等价表达时使用同一套进程内逻辑文本 matcher；索引错误会在 stderr 提示并给出 `--reindex` 建议。可与 `--list` 组合。 | - |
| `--reindex` | 强制重建全文搜索索引。索引损坏或手动修改会话数据后使用。 | - |
| `--lang` | 强制 CLI 文案语言（`en` 或 `zh`），覆盖基于 `LANG`/`LC_ALL` 的自动检测。 | 自动检测 |
| `--no-metadata-summary` | 在列表与交互视图中隐藏每个会话的元数据摘要行。 | 关闭 |
| `-v`, `--version` | 打印版本号后退出。 | - |
| `--shortcut` | 运行已配置的快捷预设。示例：`agent-dump --shortcut ob 20260408` | - |
| `-since`, `--since` | collect 开始日期，支持 `YYYY-MM-DD` 或 `YYYYMMDD` | - |
| `-until`, `--until` | collect 结束日期，支持 `YYYY-MM-DD` 或 `YYYYMMDD` | - |
| `--save` | collect 报告路径。支持绝对/相对目录或 `.md` 文件路径。未提供文件名时使用默认 collect 文件名。配合 `--emit-prompt` 时只把路径写入提示词，由外部 agent 生成报告。 | - |
| `-config`, `--config` | 配置管理：`view` 或 `edit` | - |
| `--list` | 仅列出会话不导出，并输出全部匹配会话（若指定 `-days` 或 `-query` 且未指定 `--interactive` 则自动启用） | - |
| `-format`, `--format` | 输出格式。支持逗号分隔多值：`json \\| markdown \\| raw \\| print`，兼容 `md` 别名。默认：URI 模式为 `print`，非 URI 模式为 `json`。URI 模式可混用 `print,json`；`--interactive` 不支持 `print`；`--list` 下会警告并忽略；`--head` 不能与此选项组合。Cursor URI 仅支持 `json` 和 `print`（不支持 `raw/markdown`）。 | - |
| `-summary`, `--summary` | 仅 URI 模式生效。开启后仅在 `--format` 包含 `json` 且 AI 配置完整时生成 summary；否则仅 warning 并继续导出（不启用 summary）。AI 请求期间会在 stderr 显示 loading 提示。不能与 `--head` 组合。 | - |
| `-p`, `-page-size`, `--page-size` | 为兼容保留，当前不生效 | 20 |
| `-output`, `--output` | 输出目录。`json/raw` 优先级：`--output` > `config.toml` `[export].output` > `./sessions`。相对路径从 agent-dump 执行目录解析。Markdown 仍使用 `./sessions`，除非显式传入 `--output`。`--list` 下会警告并忽略。 | `config export.output` 或 `./sessions` |
| `-h, --help` | 显示帮助信息 | - |

### Python API 迁移

Rust 版本只发布 CLI。通过子进程调用 `agent-dump`，使用 JSON 导出交换结构化数据。旧 Python API 保留在 Git 历史和已发布的 0.15.9 中；现有 API 使用方升级前应迁移到 CLI，或固定 `agent-dump==0.15.9`。

### collect 配置文件

部分会话读取或摘要失败时，collect 继续处理成功会话，并在保存的 Markdown 中固定注明读取失败数、摘要失败数和实际包含的会话数；全部失败时仍整体失败。

Provider 发现失败（含部分文件检查或解析失败）单独计数，因为遗漏会话数量未知。查询筛选阶段的读取失败也计入会话读取失败数。保存的报告和完成日志会保留这些缺口；`--emit-prompt` 将其写入任务元数据，且因失败而没有候选时返回失败。

Collect 在每个会话 12,000 字符的提取预算内保留可见消息正文（预算包含事件标签）。超出预算的正文会被省略，并向最终摘要传递截断标记。

PM 摘要只合并同一天、工作目录明确且相同的会话；工作目录未知的会话保留独立归属。

默认配置文件路径：

- macOS/Linux: `~/.config/agent-dump/config.toml`
- Windows: `%APPDATA%/agent-dump/config.toml`

配置示例：

```toml
[ai]
provider = "openai" # openai | anthropic
base_url = "https://api.openai.com/v1"
model = "gpt-4.1-mini"
api_key = "sk-..."

[collect]
summary_concurrency = 4

[export]
output = "../exports"

[shortcut.ob]
params = ["date"]
args = [
  "--collect",
  "--save", "~/Dropbox/OBSIDIAN/XingKaiXin/00_Inbox/{year}/{year_month}/agent-dump-collect-{date}.md",
  "--since", "{date}",
  "--until", "{date}",
]

[agent.claudecode]
deny = [
  "/Users/Kevin/workspace/projects/work/fin-agent/agent",
]
```

`[agent.<name>].deny` 仅对 `--collect` 生效。当会话 `cwd` 与配置路径匹配或位于该路径下时，collect 阶段会忽略该会话。

collect、`--collect --dry-run` 与 `--collect --emit-prompt` 均要求合法 TOML，且排除路径必须是非空路径字符串组成的数组。配置不可靠时，命令会在发现会话和发送 AI 请求前停止；collect 不会通过兼容解析静默取消排除规则。

`[export].output` 定义 `json/raw` 导出的全局默认输出根目录。接受绝对或相对路径。相对路径从 `agent-dump` 执行目录解析，而非配置文件所在目录。

`[shortcut.<name>]` 定义可复用的快捷预设。`params` 声明位置输入名称。`args` 声明展开的 CLI argv 模板。提供 `date` 时，`{year}` / `{month}` / `{year_month}` 会自动派生。

`agent-dump` 写入 `config.toml` 时会转义 TOML 特殊字符，并将文件权限限制为仅所有者可读写（`0600`），因为其中可能包含 API key。
为兼容旧版本，程序仍可读取不合法的 TOML；但由于无法保证未知字段无损往返，`--config edit` 会拒绝改写。请先手动修正无效转义或替换配置文件。

## 项目结构

```text
Cargo.toml      # Workspace, shared dependencies/lints and CLI release version
rustfmt.toml    # Stable Rustfmt, edition 2024, 80 columns
src/            # CLI workflows, Collect and terminal interaction
crates/agent-dump-core/ # Providers, sessions, queries and export engine
resources/      # Embedded locales and prompts
tests/cli/      # CLI contracts and external Python reference comparison
tests/tooling/  # Packaging, benchmark and documentation checks
scripts/        # Validated CLI benchmarks and paired release eval
packaging/      # Maturin builds and installation verification
npm/            # Node launcher and platform packages
docs/           # Architecture, migration and acceptance evidence
web/            # Landing page
```

## Development

Rust 是本分支的构建和运行实现，交互界面使用 Ratatui。旧 Python 应用已移出主树，差分验证在独立环境安装固定的 0.15.9 wheel。功能证据见 [P2](docs/rust-p2-completion.md)、[P3～P5](docs/rust-p3-p5-completion.md)；发布切换见 [P6 最终验收](docs/rust-p6-completion.md)，性能数据见[最终复测](docs/benchmarks/rust-p6.md)。

```bash
# 从仓库根直接运行 Cargo
cargo build --locked --release
cargo test --locked --workspace

# 完整本地 CI，包含独立的历史 Python 对照
# （Node.js 可用时包含 npm 测试，pnpm 可用时包含 landing page 检查）
just isok

# Check Rustfmt, strict Clippy and Ruff
just lint

# Auto-fix linting issues
just lint-fix

# Format code
just fmt

# Type checking
just check

# Testing
just test

# 构建当前平台原生二进制
just build-native

# 同步 npm 包版本
just build-npm

# 运行 npm wrapper 测试和 smoke 检查
just test-npm-smoke
```

两个 crate 统一继承 workspace lint：禁止 unsafe，Clippy all/pedantic 为 deny、nursery 为 warn；门禁以 `-D warnings` 执行。逐项例外及原因见[开发指南](docs/development-guide.md#rust-格式与-lint)。`tests/` 保留现有 CLI 差分和工具验收测试。

## 发布

```bash
# 1. 在单一位置更新版本号
$EDITOR Cargo.toml

# 2. 提交并合并到 main

# 3. 创建并推送发布标签
git tag v{version}
git push origin v{version}
```

- 标签发布工作流为 [`release.yml`](./.github/workflows/release.yml)
- 仅匹配 `vX.Y.Z` 的标签会触发统一发布流水线
- 发布包含 PyPI 制品、GitHub Release 资产和 `@agent-dump/cli` npm 包
- 同一版本的发布可以安全重试：字节一致的 registry 制品会跳过，已存在但内容不同则失败
- npm 发布会确认每个包已可下载且完整性校验一致后再继续，所有原生平台包就绪后才发布 CLI 主包
- npm CLI 包在 `npm`/`npx` 安装阶段会下载并校验匹配的原生二进制
- PyPI 发布使用 GitHub `release` 环境中的环境级 secret `UV_PUBLISH_TOKEN`
- 每个 `@agent-dump/*` npm 包均使用绑定到本仓库、`release.yml` 与 GitHub `release` 环境的
  Trusted Publisher/OIDC 发布，不使用 `NPM_TOKEN` secret

## 许可证

MIT
