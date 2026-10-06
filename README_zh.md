![logo](https://raw.githubusercontent.com/xingkaixin/agent-dump/refs/heads/main/assets/logo.png)

# Agent Dump

面向个人开发者与 AI Agent 的本地 AI 会话工具。查找、读取、导出和复用已支持编码工具的历史对话，不修改会话源数据。

[使用说明](https://agent-dump.xingkaixin.me/zh/guides/)：导出 Codex 或 Claude Code 会话、搜索历史决策、交接 Agent 上下文、生成工作报告，以及保存到 Obsidian。

## 快速开始

[安装 CLI](#安装) 后，按任务选择入口。需要本机已有[支持工具](#支持的-ai-工具)保存的会话历史。自定义目录与内容覆盖限制见[路径发现](#路径发现)。

### 个人开发者

```bash
# 浏览最近一周活跃的会话
agent-dump browse --time-field updated --days 7

# 查找当前项目讨论过的问题
agent-dump search 'auth timeout' --query 'path:.' --days 30

# 使用结果中的 URI 导出会话
agent-dump export codex://SESSION_ID --format markdown --output ./sessions
```

将 `codex://SESSION_ID` 替换为列表或搜索结果中的真实 URI。搜索默认按创建时间筛选；查找最近活动时加 `--time-field updated`。需要勾选多个会话导出时，使用 `--interactive`。

### AI Agent

```bash
# 检查支持格式与来源路径，再查找候选会话
agent-dump providers --json
agent-dump list --time-field updated --days 7 --json

# 检查单条会话的元数据，再获取分页读取说明
agent-dump head codex://SESSION_ID --json
agent-dump read-prompt codex://SESSION_ID

# 将报告任务交给外部 Agent，无需配置 API
agent-dump collect --days 7 --emit-prompt --save ./reports/weekly.md
```

按生成的命令和游标继续读取，直到 `has_more=false` 才完成所选内容的覆盖。检查退出码与 `status`，不能将 partial 结果当成完整读取。`--emit-prompt` 只生成任务说明，不会生成报告。详见[机器可读输出](#机器可读输出)、[带来源的上下文导出](#消息定位与上下文)和 [Agent recipes](skills/agent-dump/references/cli-recipes.md)。

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

- **查找历史工作**：搜索标题、消息、思考和工具状态，按 Provider、项目路径、角色或最近活动筛选。
- **读取上下文**：在终端浏览，通过 Session URI 打开，或让 Agent 使用有界 JSON 分页和游标读取。
- **带来源复用**：将会话或选定上下文导出为支持的格式，上下文导出保留 URI 和消息定位信息。
- **汇总对话**：将所有符合规则的 user/assistant 正文分块处理，或交给外部 Agent 汇总；失败时明确标记不完整。
- **接入自动化**：通过 JSON 查询元数据、能力、搜索证据和统计，明确表示未知事实。

可用格式和消息细节取决于来源工具。标准化输出不包含每个私有字段或附件实体。可运行 `agent-dump --providers --json` 检查能力。

## 安装

Rust 版本提供 `agent-dump` CLI。使用 uv 安装：

```bash
uv tool install agent-dump
```

预构建包支持 macOS x64/arm64、Linux x64（glibc ≥ 2.17）和 Windows x64。wheel 安装无需 Rust 编译器。其他构建要求及旧接口迁移见[源码构建与 Python API 迁移](docs/cli-compatibility.md#源码构建与-python-api-迁移)。

### 其他命令入口

| 用途 | 命令 |
| --- | --- |
| 使用 pip 安装 | `pip install agent-dump` |
| 使用 uvx 运行 | `uvx agent-dump --help` |
| 使用 npx 运行 | `npx @agent-dump/cli --help` |
| 使用 bunx 运行 | `bunx @agent-dump/cli --help` |

后续示例统一使用 `agent-dump`。选择 uvx、npx 或 bunx 时，只替换命令前缀，参数保持一致。

`bunx`、`npx` 和 npm/pnpm/Bun 全局安装入口均需要 Node.js 22 或更高版本。npm 包装器沿用 registry、认证、代理和 CA 配置，并校验平台包 checksum。不支持的平台会收到诊断与 GitHub Releases 链接。

npm 当前支持的平台：

<!-- native-targets:start -->
- `darwin-x64`
- `darwin-arm64`
- `linux-x64`
- `win32-x64`
<!-- native-targets:end -->

### 原生安装：curl、Homebrew 与 Scoop

以下渠道从 v1.0.0 起提供支持，直接安装原生 CLI，无需 Python、Node.js 或 Rust。

**macOS / Linux 安装脚本**（macOS x64/arm64；Linux x64、glibc ≥ 2.17）：

```bash
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh
```

安装器校验 SHA-256 和可执行文件版本，成功后才替换旧版本。默认安装到 `~/.local/bin`，不使用 sudo、不修改 shell 配置；需要时会提示配置 PATH。再次运行即可更新。指定版本或目录时，将变量传给 `sh`：

```bash
curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | AGENT_DUMP_VERSION=1.1.1 AGENT_DUMP_INSTALL_DIR="$HOME/.local/bin" sh
```

默认位置的脚本安装可通过 `rm "$HOME/.local/bin/agent-dump"` 卸载。安装器不会覆盖包管理器的符号链接，这类安装请通过原包管理器更新。

**Homebrew**（macOS x64/arm64 和 Linux x64）：

```bash
brew install xingkaixin/tap/agent-dump
brew upgrade agent-dump
# 卸载：brew uninstall agent-dump
```

**Scoop**（Windows x64，需要已安装 Scoop）：

```powershell
scoop bucket add xingkaixin https://github.com/xingkaixin/scoop-bucket
scoop install xingkaixin/agent-dump
scoop update agent-dump
# 卸载：scoop uninstall agent-dump
```

目前没有 Linux ARM64、musl/Alpine 或 Windows ARM64 原生产物。切换安装渠道时，先卸载旧安装，或确认 PATH 当前选中的可执行文件。

### 安装为 Agent skill

```bash
npx skills add xingkaixin/agent-dump
```

## 使用方法

### 交互式导出

```bash
# 进入交互模式选择和导出会话
agent-dump --interactive
```

运行后会显示最近 7 天的会话列表，按时间分组显示（今天、昨天、本周、本月、更早）。使用空格选择/取消，回车确认导出。

不带参数运行 `agent-dump` 显示帮助。如果同时传入多个显式模式，agent-dump 会保留既有模式优先级，并告警列出被忽略的较低优先级参数。

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
| `0` | 命令做到了被要求的事——包括结果集本就为空（`--days` 窗口内没有会话、关键词或 `--search` 没有命中），以及交互式导出部分成功。 |
| `1` | 命令做不到被要求的事：本机不存在任何 provider 数据、URI 未能解析到会话、交互式导出全部失败、或参数组合非法。 |
| `2` | 参数用法错误，由 `argparse` 抛出（未知参数、非法的 `--format` 值）。 |

这样 `agent-dump --list && ...` 才有意义：列出了会话就成功，因为没有任何 provider
数据而无从列出则失败。

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

## 命令行参数

用 `agent-dump --help` 查看当前选项。以下示例补充[快速开始](#快速开始)中的常用流程。

### 命令

开头的命令是对应参数的简写，原有参数写法保持不变。

| 命令 | 等同于 |
| --- | --- |
| `list` | `--list` |
| `search <TERMS>` | `--search <TERMS>` |
| `browse` | `--browse` |
| `export <URI>` | 未指定 `--format` 时为 `<URI> --format json` |
| `export`（无 URI） | `--interactive` |
| `head <URI>` / `read <URI>` / `read-prompt <URI>` | `<URI> --head` / `--read` / `--read-prompt` |
| `collect` / `stats` / `providers` / `reindex` | `--collect` / `--stats` / `--providers` / `--reindex` |
| `config <view\|edit>` | `--config <view\|edit>` |
| `shortcut <NAME> [ARGS]` | `--shortcut <NAME> [ARGS]` |

直接传入 URI 仍在终端打印会话。

```bash
# 按 Provider、项目路径或消息角色筛选
agent-dump --list --query 'error provider:codex,kimi' --days 30
agent-dump --list --query 'bug path:"/Users/me/My Project"'
agent-dump --interactive --query 'role:user limit:20 refactor'
agent-dump --list 'agents://.?q=refactor&providers=codex,claude&roles=user&limit=20'

# 导出多种格式，或为 JSON 添加 AI 摘要
agent-dump --interactive --format json,markdown --output ./sessions
agent-dump codex://SESSION_ID --format print,json --output ./sessions
agent-dump codex://SESSION_ID --format json --summary --output ./sessions

# 搜索、查看统计或重建索引
agent-dump --search 'auth timeout' --days 30
agent-dump --stats --days 30
agent-dump --reindex

# 汇总报告或预览工作量
agent-dump --collect --days 7 --save ./reports
agent-dump --collect --since 2026-03-01 --until 2026-03-05 --save ./reports/weekly.md
agent-dump --collect --collect-mode insight --dry-run
agent-dump --shortcut ob 20260408

# 查看或编辑配置
agent-dump --config view
agent-dump --config edit
```

`--query` 与 `--search` 匹配语义相同：按空白拆分的字面 term 必须全部出现在标题或 transcript 中，位置不限。出现结构化字段（`provider`、`role`、`path`、`limit`）时启用结构化解析，带空格的值需要引号。`role` 限定参与匹配的消息，`limit` 限制最终全局结果数。`error:timeout` 仍是普通 term。列表输出全部匹配项，交互模式中的 Provider 计数反映筛选后的结果。

Collect 的日期优先级为显式 `--since`/`--until`、显式 `--days`，最后是当天。`--save` 接受目录或 `.md` 文件，可用绝对或相对路径。完整输入覆盖、排除规则、进度和不完整报告见 [collect 说明](#collect-配置文件)。

### 交给外部 agent 汇总

不配置大模型 API，也不依赖 skill，可以直接生成一份外部 agent 能执行的汇总提示词：

```bash
agent-dump --collect --emit-prompt \
  --since 20260824 --until 20260830 \
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
- 复用 collect 的排除规则和查询筛选。日期两端均包含，按可见文本段的**实际本地日期**筛选并逐日拆分。候选发现不按创建日期排除旧会话，生成清单时读取正文，仅保留含日期范围内活动的会话；外部 Agent 再根据读取页的 `text_spans` 筛选日期。清单不是内容快照。
- 读取正文前，核对清单结束标记、候选数量、唯一 URI、JSON 长度和命令对应关系；JSON 能解析不等于清单完整。
  清单损坏时先使用已保存的完整文件；没有完整文件时，仅允许按原筛选条件重新生成一次提示词并直接保存输出。
  重生成是新候选清单，不是恢复旧快照；原条件不明或仍损坏时先询问，未经同意不交付残缺清单的部分日报。
- 外部 agent 用 `--read --order asc --json` 逐页读取，再用 `--read --cursor <next_cursor> --json` 继续，直到 `has_more=false`。
  每页正文和诊断分别落盘，长消息的所有片段都要读完；单页成功不算完整阅读。只分析 user/assistant 的可见 text，不加 `--details`。
  `status=partial`、缺页或内容版本变化都必须说明覆盖缺口，不混合不同版本的事实笔记。
- 没有实质可见对话的来源直接忽略；审批或重复转录只有改变请求、决策或结果时才保留，当前汇总过程不作为被汇总的工作事项。
  覆盖已有报告需要用户明确同意；先完成并核验新内容，再替换旧报告。
- 仅支持 collect 模式，与 `--dry-run` 互斥。候选为空时不输出提示词，退出 `0`；无可用 provider 或准备失败时退出 `1`。
- 要让 shortcut 始终生成提示词，在它的 `args` 中加入 `"--emit-prompt"` 即可，无需其他调整。

模型指令及报告标题与内置 collect 一样使用中文，`--lang` 控制 CLI 帮助和诊断。
提示词包含本地标题和路径，分享时应按私有数据处理；外部处理受对应 agent 的数据传输策略约束，不等于离线处理。
提示词生成成功不代表报告已生成，也不会自动启动外部 agent。

<details>
<summary>兼容参数</summary>

已有调用仍支持 `-days`、`-query`、`-format`、`-output`、`-summary`、`-config`、`-since`、`-until`、`-page-size` 和 `-v`。`--capabilities`、`md`、`cwd:` 及旧 Provider 查询前缀也继续保留。标准写法见[兼容参考](docs/cli-compatibility.md#中文)。

</details>

### 完整参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `uri` | 用于直接查看的 Agent Session URI（如 `opencode://session-id`），或作用域查询 URI，如 `agents://.?q=refactor&providers=codex,claude&roles=user&limit=20` | - |
| `--interactive`, `-i` | 进入交互式模式选择和导出会话 | - |
| `--days`, `-d` | 查询最近 N 天的会话，N 必须为日历范围内的正整数。collect 模式下仅在未提供 `--since/--until` 时生效。 | collect 外默认 7；collect 内默认仅当天 |
| `--time-field` | 列表、搜索、浏览和交互模式中 `--days` 的时间依据：`created` 或 `updated`。 | `created` |
| `--query`, `-q` | 查询过滤。关键词与 `--search` 一样按空白拆分、不区分大小写，所有 term 都必须出现在 Session 标题或逻辑 transcript 中。支持普通关键词或结构化条件，如 `bug provider:codex role:user path:. limit:20`。`limit` 必须为有符号 64 位范围内的正整数。未知结构化 key 会被拒绝。不能与 `agents://...` 查询 URI 同时使用。 | - |
| `--head` | 仅 URI 模式。打印有界发现阶段已有的元数据，不重新读取完整正文；发现阶段完整扫描时消息数为精确值，否则明确显示“未知”。不导出文件也不打印正文。不能与 `--format` 或 `--summary` 组合。 | - |
| `--collect` | 按日期范围采集会话，可选通过 `--query` 或 `agents://...` 查询 URI 约束范围（两者互斥）。只总结 user/assistant 可见文本，排除 system/developer/tool 消息、reasoning、plan、工具调用和工具结果，投影后为空的会话直接忽略。PM 模式提取 requests、decisions 和 Agent 明确报告的 outcomes，再进行 session 归并和 tree reduction。多阶段进度显示在 stderr。 | - |
| `--collect-mode` | collect 输出模式：`pm` 生成项目管理视角总结，`insight` 生成作者洞察视角总结。 | `pm` |
| `--dry-run` | 与 `--collect` 搭配使用，预览 provider 分布、session 数、chunk 数、并发配置、日期范围和保存路径，跳过 AI 请求和文件写入。 | - |
| `--emit-prompt` | 与 `--collect` 搭配使用，输出交给外部 agent 的自包含任务提示词，不需要 AI 配置，不写报告。与 `--dry-run` 互斥；`--save` 指定最终报告位置。 | - |
| `--stats` | 显示最近 N 天会话使用统计，按 Agent 和时间分组。存在未知消息数时显示已知小计与未知会话数，不把部分和冒充总数。支持 `--days` 与 `--query`，推荐独立使用。 | - |
| `--providers` | 显示已注册 provider 的能力矩阵，包括 URI scheme、支持及不支持的导出格式、持久索引不可用时采用的存储级关键词回退，以及本地搜索路径是否存在。不扫描会话。 | - |
| `--search` | 基于 SQLite FTS5 的本地全文搜索，覆盖会话标题、消息内容、reasoning 和 tool state。按空白切分的 distinct term 均按字面量匹配（不解释 `AND`/`NEAR`/`*` 等 FTS5 操作符语法），所有 term 都必须存在，但可以分别落在不同 corpus 字段；CJK term 必须连续。FTS5 不可用或 tokenizer 无法等价表达时使用同一套进程内逻辑文本 matcher；索引错误会在 stderr 提示并给出 `--reindex` 建议。可与 `--list` 组合。 | - |
| `--reindex` | 强制重建全文搜索索引。索引损坏或手动修改会话数据后使用。 | - |
| `--lang` | 强制 CLI 文案语言（`en` 或 `zh`），覆盖基于 `LANG`/`LC_ALL` 的自动检测。 | 自动检测 |
| `--no-metadata-summary` | 在列表与交互视图中隐藏每个会话的元数据摘要行。 | 关闭 |
| `-v`, `--version` | 打印版本号后退出。 | - |
| `--shortcut` | 运行已配置的快捷预设。示例：`agent-dump --shortcut ob 20260408` | - |
| `--since` | collect 开始日期，支持 `YYYY-MM-DD` 或 `YYYYMMDD` | - |
| `--until` | collect 结束日期，支持 `YYYY-MM-DD` 或 `YYYYMMDD` | - |
| `--save` | collect 报告路径。支持绝对/相对目录或 `.md` 文件路径。未提供文件名时使用默认 collect 文件名。配合 `--emit-prompt` 时只把路径写入提示词，由外部 agent 生成报告。 | - |
| `--config` | 配置管理：`view` 或 `edit` | - |
| `--list` | 仅列出会话不导出，并输出全部匹配会话（若指定 `--days` 或 `--query` 且未指定 `--interactive` 则自动启用） | - |
| `--format` | 输出格式。支持逗号分隔多值：`json \\| markdown \\| raw \\| print`。默认：URI 模式为 `print`，非 URI 模式为 `json`。URI 模式可混用 `print,json`；`--interactive` 不支持 `print`；`--list` 下会警告并忽略；`--head` 不能与此选项组合。Cursor URI 仅支持 `json` 和 `print`（不支持 `raw/markdown`）。 | - |
| `--summary` | 仅 URI 模式生效。开启后仅在 `--format` 包含 `json` 且 AI 配置完整时生成 summary；否则仅 warning 并继续导出（不启用 summary）。AI 请求期间会在 stderr 显示 loading 提示。不能与 `--head` 组合。 | - |
| `--page-size`, `-p` | 仅兼容保留，不生效。读取分页使用 `--read` 与 `--limit` / `--max-chars`。 | 20 |
| `--output` | 输出目录。`json/raw` 优先级：`--output` > `config.toml` `[export].output` > `./sessions`。相对路径从 agent-dump 执行目录解析。Markdown 仍使用 `./sessions`，除非显式传入 `--output`。`--list` 下会警告并忽略。 | `config export.output` 或 `./sessions` |
| `-h, --help` | 显示帮助信息 | - |

### Python API 迁移

详见 [CLI 迁移与固定 Python 版本](docs/cli-compatibility.md#源码构建与-python-api-迁移)。

### collect 配置文件

部分会话读取或摘要失败时，collect 继续处理成功会话，并在保存的 Markdown 中固定注明读取失败数、摘要失败数和实际包含的会话数；全部失败时仍整体失败。

Provider 发现失败（含部分文件检查或解析失败）单独计数，因为遗漏会话数量未知。查询筛选阶段的读取失败也计入会话读取失败数。保存的报告和完成日志会保留这些缺口；`--emit-prompt` 将其写入任务元数据，且因失败而没有候选时返回失败。

Collect 发现候选时不按创建日期截断，只汇总请求日期范围内的 user/assistant 可见文本段。跨日会话在摘要前拆成每日单元；会话计数仍按唯一 URI 统计。没有可靠时间的文本会被排除，并在诊断及报告中标记日期覆盖不完整，包括无时间的 Kimi context 和使用推测时间的 Cursor 消息；不借用会话创建或更新时间。先按查询筛选候选，再按文本日期过滤，最后按 limit 限制唯一会话数。包括超长单条消息在内，事件按最多 3,200 个 Unicode 字符分块（含标签）。分块摘要每组最多八份逐层归并，较大的最终报告按来源分组分次生成。每次模型请求最多 64,000 个输入字符；超大的元数据或派生摘要会明确失败，不静默截断来源正文。部分成功报告列出遗漏会话 URI。完整输入覆盖不代表摘要逐字保留所有细节。

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

### 按最近活动查找会话

```bash
agent-dump --list --time-field updated -d 7 --json
agent-dump --search '数据库锁定' --time-field updated -d 7
agent-dump --browse --time-field updated -d 7
agent-dump --interactive --time-field updated -d 7
```

`--days` 默认按创建时间筛选。加 `--time-field updated` 可查找 Provider 记录的 `updated_at` 位于最近 N 天内的会话，包括很早创建、最近仍有活动的会话。`--time-field created` 显式选择既有默认行为。该参数只用于列表、搜索、浏览和交互模式；collect 日期和统计含义不变。

活动列表先按更新时间排序，再应用结果数量限制。文本列表和交互选择保留 Provider 分组；显示日期和“今天／昨天”等分组使用所选时间字段。全文搜索仍优先按相关性排序。JSON 保留原有创建时间和更新时间。为发现旧会话的新活动，可能需要扫描创建时间窗口之外的元数据；筛选沿用各 Provider 的 `updated_at` 事实，不额外按文件修改时间推断活动。各 Provider 的覆盖范围和发现不完整时的诊断规则不变。

### 机器可读输出

列表、搜索和统计可加 `--json`，将一个 JSON 对象输出到 stdout；诊断和进度输出到 stderr。现有 `--format json` 文件导出行为不变。

```bash
agent-dump --list --json
agent-dump --search 'timeout' --json --query 'provider:codex'
agent-dump --stats --json
agent-dump codex://SESSION_ID --head --json
agent-dump --providers --json
```

结果包含 `schema_version: 1`、`kind`（list/search/stats）、`status`（ok/partial/error）、`data`、`failed_providers`、`failed_sessions` 和 `error`。发现不完整或筛选读取失败时为 partial，健康结果仍可使用。列表和搜索的 data 为数组；统计为 total/by_provider/by_time 对象。未知目录、模型和消息数为 null；时间使用 UTC ISO 8601。统计中的 known_messages 只统计已知计数，unknown_message_count_sessions 单独记录未知会话数；时间桶按创建日期及本地日期计算。

无匹配返回空数组和退出码 0；没有可用来源且未指定 Provider 范围时返回 error 和退出码 1。参数或执行错误可能只在 stderr 输出诊断，调用方必须检查退出码。`--json` 也支持消息上下文、`--read` 分段读取、`--head` 和 `--providers`，其他模式不支持。

`agent-dump <URI> --head --json` 返回 `kind: "head"`，`data` 为单条会话元数据。字段与列表一致，并包含 `project`、`version`、`subtargets`。不请求完整正文；URI 使用规范形式，未知目录、模型和消息数保留为 null，可恢复的查找诊断产生 `status: "partial"`，详情在 stderr。

`agent-dump --providers --json`返回 `kind: "providers"`，`data` 为 Provider 数组。每项包含名称、显示名、scheme、标识符提示、可选 ID 前缀、支持的 `formats`，以及带 label/path/exists 的 `search_roots`。只检查能力和路径是否存在，不读取会话正文；路径存在不代表会话一定可读。两种结果均使用 `schema_version: 1`；失败时退出码非零，stdout 可能为空。


### 消息定位与上下文

```bash
agent-dump --search 'database locked' --locate --json --query 'provider:codex'
agent-dump codex://SESSION_ID --message 'REVISION:POSITION' --before 2 --after 3
agent-dump codex://SESSION_ID --message 'REVISION:POSITION' --json
agent-dump codex://SESSION_ID --message 'REVISION:POSITION' --before 2 --after 3 --format json,markdown --output excerpts
```

将搜索结果 `locations[].locator` 原样传给 `--message`。`position` 是标准化会话中的一基消息序号；定位符绑定会话正文快照，正文变化后需重新搜索。范围默认前后各 3 条，可用 0 只读目标；超出首尾自动截到边界。范围读取仍需解析源会话，不承诺局部磁盘读取。

`--locate` 仅用于 `--search`，返回包含任一搜索词的消息位置（各搜索词仍须在会话中全部命中），并遵守角色筛选。仅标题命中时 locations 为空；定位读取失败时为 null，结果标记 partial。未加 --locate 的搜索行为不变。

`--message` 不能与 `--head` 或 `--summary` 组合。不加 `--format` 时打印上下文；`--json` 将上下文对象写入 stdout，包含 kind=context、data.uri、locator、total_messages、start/end 和 messages；每项包含 position 与标准化 message。定位符过期或无效返回非零退出码，JSON 模式诊断仅进入 stderr。

加 `--format json,markdown` 可导出选定片段。文件位于输出目录的 Provider 子目录，名称为 `<id>.messages-<start>-<end>.json` / `.md`，不会覆盖整条会话导出。两种格式均保留规范化会话 URI、定位符（正文 revision 和目标位置）、原始消息范围及状态。JSON 保留标准化消息记录；Markdown 展示消息的可搜索文本。可恢复的来源诊断会把文件标记为 `partial`，具体诊断进入 stderr。定位符过期时不会创建文件。各 Provider 的格式限制仍生效；不接受 raw/print 文件格式，也不能同时使用 `--json` 与文件导出参数。`--output` 需要显式指定 `--format`，默认目录与整条会话导出规则一致。

### 按需读取与 Agent 读取提示词

把下面这一条命令交给 Agent，它就能获得分段读取该会话的说明和可执行命令，无需安装 skill 或配置 MCP：

```bash
agent-dump codex://SESSION_ID --read-prompt
```

`--read-prompt` 支持所有已注册的 Provider（包括 Claude Code、OpenCode、ZCode、Kimi、Cursor、Pi、DeepChat、Cherry Studio 和 MiniMax Code），只校验 URI 格式，不发现来源、读取正文、调用模型或创建文件。它输出的命令使用当前原生可执行文件的绝对路径，保留相同的 Provider 路径环境变量后可直接执行。提示词随 `--lang en|zh` 本地化；成功生成说明不代表会话存在或已经读完。

也可以直接读取：

```bash
agent-dump codex://SESSION_ID --read --json
agent-dump codex://SESSION_ID --read --cursor '上一页的 data.next_cursor' --json
agent-dump claude://SESSION_ID --read --role user --match '数据库迁移' --limit 10 --json
agent-dump opencode://SESSION_ID --read --order asc --max-chars 4000 --details --json
```

| 参数 | 行为 |
| --- | --- |
| `--read` | 分页读取指定会话；默认文本输出，`--json` 输出结构化结果 |
| `--read-prompt` | 生成自包含的 Agent 读取说明，与 `--read`、`--json` 互斥 |
| `--limit` | 每页最多 1～100 条消息，默认 20；分页单位不是对话轮次 |
| `--max-chars` | 每页正文最多 1～100000 个 Unicode 字符，默认 12000；不计 JSON 包装与游标 |
| `--order` | `desc`（默认）按原始消息位置从后往前，`asc` 从前往后 |
| `--cursor` | 原样传入续读游标；游标保存原筛选、排序和预算，不能同时重设这些选项 |
| `--role` | 筛选一种标准化角色，忽略参数首尾空白及大小写 |
| `--match` | 对所选文本视图逐消息匹配字面短语，不区分大小写并归一化空白；先筛选再分页 |
| `--details` | 加入 reasoning、plan 和结构化工具状态的可读投影；默认只取文本部分 |

这些读取参数仅用于 `--read`，不能与列表、搜索、collect、导出、`--head`、`--summary` 或 `--message` 混用。原有 URI 全文打印、`--search` 和 `--query` 的语义不变。匹配不是正则、语义搜索或跨消息检索；搜索工具详情需显式加 `--details`。两种视图均跳过无可读文本的消息，不读取附件实体，也不承诺包含全部 Provider 原始字段。`--role` / `--match` 必须非空，分别最多 100 / 4096 个 UTF-8 字节；读取 URI 最多 4096 字节。

JSON 包含 `schema_version: 1`、`kind: read`、`status`、`has_more` 和 `data`。data 中有 URI、revision、筛选前的 total_messages、options、messages 和 next_cursor。每个片段保留原会话一基 position、可用于 `--message` 的 locator、role、text、total_chars，以及从零开始的 Unicode 字符区间 start/end（左闭右开）。`truncated` 表示这一项只是消息的一部分；长消息通过游标从下一字符继续，消息内始终正序读取。

`has_more=false` 表示已读完所选视图中符合条件的内容；预算分段不会把 status 标为 partial。源读取存在可恢复诊断时为 partial，详情进入 stderr。无匹配成功返回空数组；无效、跨会话或过期游标非零退出且 stdout 为空。正文变化后需重新开始，不能把不同 revision 拼成一个快照；游标不保存历史快照。

分段输出减少返回给 Agent 的内容，内部仍可能解析完整源会话，不承诺局部磁盘读取。只读 Provider 来源，遵守各来源既有支持范围和平台限制。

不加 `--details` 时，消息的 `text_spans` 给出实际本地 `date`（未知或推测时间为 null）及消息内 Unicode `start/end` 区间。区间裁剪到本页片段；切取片段 text 时减去片段 start。文本段间分隔空行不归属日期，外部汇总按这些区间筛选日期。

### TUI 会话阅读器

```bash
agent-dump --browse
agent-dump --browse --query 'provider:codex path:.' --days 30
agent-dump --browse 'agents://.?providers=codex,claude'
agent-dump --browse --search "database lock" --format json,markdown --output ./exports
```

`--browse` 需要真实交互式终端，默认选择最近 7 天创建的会话，按更新时间排序；加 `--time-field updated` 改为按最近活动筛选。支持现有查询条件和 agents:// 查询 URI；只读取当前选择的会话正文（内容筛选本身仍可能读取多个会话）。宽终端显示列表和正文两栏；窄于 90 列时通过 Tab 切换单栏。阅读器只读 Provider 来源，不自动刷新活动会话；重新打开可获取新列表。

- ↑/↓ 或 j/k：在当前区域移动或滚动；Enter/→ 进入正文，← 返回列表。
- Tab：切换区域；PageUp/PageDown 翻页；Home/End 跳到首尾。
- `s`：在当前来源、目录、日期、角色和数量上限内搜索会话，要求所有词都匹配；指定角色时，要求所有词出现在该角色的同一消息中。命中导航会遍历包含任一搜索词的消息。`--browse --search "database lock"` 可直接进入该搜索，按相关性排序。顶部显示范围和搜索模式；`?` 查看完整范围与帮助；`c` 清空搜索词，保留范围。
- `/` 输入当前会话的字面搜索词，Enter 搜索，Esc 取消输入；n/N 跳到下一个/上一个命中消息。搜索自动展开工具详情。
- `t`：展开或折叠工具详情；`y`：发送 URI 复制请求，需要终端支持 OSC 52。
- `x`：预览当前命中消息及其前后各 3 条消息；`+`/`-` 调整上下文条数，n/N 切换命中。预览时 `e` 仅导出该范围，支持 JSON、Markdown，保留来源 URI 和消息位置。来源在预览后变化时拒绝导出。`x` 或 Esc 返回完整会话。
- 完整会话视图中 `e`：导出当前会话，遵守 --format、--output 和现有 Provider 格式能力，默认 JSON；不支持 print 格式。
- q/Esc/Ctrl-C：关闭阅读器并恢复终端，正常关闭返回 0。

搜索为空时仍可用 `s` 修改搜索、`c` 清空词。来源、目录、日期、角色和数量上限在阅读期间固定，需修改 CLI 参数后重新打开来扩大范围；不可用来源或非终端输入返回失败。单个会话读取失败会显示诊断，仍可切换其他会话。原有 --interactive 批量选择导出保持不变。

## 项目结构

```text
Cargo.toml      # Workspace, shared dependencies/lints and CLI release version
rustfmt.toml    # Stable Rustfmt, edition 2024, 80 columns
src/            # CLI workflows, Collect and terminal interaction
crates/agent-dump-core/ # Providers, sessions, queries and export engine
resources/      # Embedded locales and prompts
tests/cli/      # Rust CLI contracts and optional historical comparisons
tests/tooling/  # Packaging, benchmark and documentation checks
scripts/        # Validated CLI benchmarks and paired release eval
packaging/      # Maturin builds and installation verification
npm/            # Node launcher and platform packages
docs/           # Architecture, migration and acceptance evidence
web/            # Landing page
```

## Development

从 v1.0.0 起，Rust 是构建和运行实现，交互界面使用 Ratatui。旧 Python 应用已移出主树。CI 和 `just isok` 验证 Rust 行为契约，不依赖历史 Python CLI；需要历史差分验证时，`just test-differential` 在独立环境安装固定的 0.15.9 wheel。功能证据见 [P2](docs/rust-p2-completion.md)、[P3～P5](docs/rust-p3-p5-completion.md)；发布切换见 [P6 最终验收](docs/rust-p6-completion.md)，性能数据见[最终复测](docs/benchmarks/rust-p6.md)。

```bash
# 从仓库根直接运行 Cargo
cargo build --locked --release
cargo test --locked --workspace

# 完整本地 CI，不依赖历史 Python 对照
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
- 原生安装附件复用同一批已验证二进制。发布成功后，`distribution.yml` 使用仓库 secret `DISTRIBUTION_TOKEN` 同步 Homebrew 与 Scoop；可针对最新稳定版单独重试。
- 同一版本的发布可以安全重试：字节一致的 registry 制品会跳过，已存在但内容不同则失败
- npm 发布会确认每个包已可下载且完整性校验一致后再继续，所有原生平台包就绪后才发布 CLI 主包
- npm CLI 包在 `npm`/`npx` 安装阶段会下载并校验匹配的原生二进制
- PyPI 发布使用 GitHub `release` 环境中的环境级 secret `UV_PUBLISH_TOKEN`
- 每个 `@agent-dump/*` npm 包均使用绑定到本仓库、`release.yml` 与 GitHub `release` 环境的
  Trusted Publisher/OIDC 发布，不使用 `NPM_TOKEN` secret

## 许可证

MIT
