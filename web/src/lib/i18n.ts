export const LOCALES = ["en", "zh", "ja"] as const;
export type Locale = (typeof LOCALES)[number];

export const localeLabels = {
  en: "EN",
  zh: "中文",
  ja: "日本語",
} satisfies Record<Locale, string>;

export const site = {
  origin: "https://agent-dump.xingkaixin.me",
  paths: { en: "/", zh: "/zh/", ja: "/ja/" } as Record<Locale, string>,
  author: { name: "xingkaixin", url: "https://github.com/xingkaixin" },
  repo: "https://github.com/xingkaixin/agent-dump",
  license: "https://github.com/xingkaixin/agent-dump/blob/main/LICENSE",
  downloadUrls: [
    "https://www.npmjs.com/package/@agent-dump/cli",
    "https://pypi.org/project/agent-dump/",
  ],
  npm: "https://www.npmjs.com/package/@agent-dump/cli",
  pypi: "https://pypi.org/project/agent-dump/",
  logo: "/assets/logo.png",
  ogImage: { path: "/assets/og-image.png", width: 1200, height: 631 },
  changelogUrl: {
    en: "https://github.com/xingkaixin/agent-dump/blob/main/CHANGELOG.md",
    zh: "https://github.com/xingkaixin/agent-dump/blob/main/docs/zh/CHANGELOG.md",
    ja: "https://github.com/xingkaixin/agent-dump/blob/main/CHANGELOG.md",
  } as Record<Locale, string>,
  skillCommand: "npx skills add xingkaixin/agent-dump",
};

// Session IDs are illustrative; schemes match the Provider registry.
export const providers = [
  { name: "Codex", example: "codex://threads/a1b2c3" },
  { name: "Claude Code", example: "claude://a1b2c3d4" },
  { name: "ZCode", example: "zcode://sess-9f8e7d" },
  { name: "Kimi", example: "kimi://k-7a3f21" },
  { name: "OpenCode", example: "opencode://5c4b3a" },
  { name: "Cursor", example: "cursor://req-8821" },
  { name: "Pi", example: "pi://019e7978-b2ec" },
  { name: "DeepChat", example: "deepchat://session-123" },
  { name: "Cherry Studio", example: "cherry://topic-123" },
  { name: "MiniMax Code", example: "minimax://session-123" },
] as const;

export type OutputTone = "dim" | "text" | "ok" | "scheme";
export type TerminalScene = {
  command: string;
  output: { text: string; tone: OutputTone }[];
};

// Representative CLI sessions rendered under each typed command. This is a truthful
// preview of what agent-dump prints, not a fabricated dashboard: the prompts, field
// labels and default output path below are the ones the CLI actually produces.
// tests/test_docs_sync.py checks the invariants that would silently rot here.
export const terminalScenes: TerminalScene[] = [
  {
    command: "agent-dump --interactive",
    output: [
      // 交互导出是两阶段的：先选 Provider，再选那个 Provider 的会话
      { text: "Select Agent Tool to export:", tone: "dim" },
      { text: "> Codex         24 sessions", tone: "text" },
      { text: "  Claude Code   12 sessions", tone: "text" },
      { text: "", tone: "dim" },
      { text: "Available sessions:", tone: "dim" },
      { text: "1. api (2026-07-28 13:04)", tone: "text" },
      { text: "   cwd=work/api | msgs=2 | uri=codex://019c213e", tone: "dim" },
    ],
  },
  {
    command: "agent-dump codex://019c213e --format markdown",
    output: [
      { text: "Exported session [markdown] to:", tone: "dim" },
      { text: "sessions/codex/019c213e.md", tone: "ok" },
    ],
  },
  {
    command: 'agent-dump --search "auth timeout"',
    output: [
      { text: "Search results from last 7 days matching 'auth timeout':", tone: "dim" },
      { text: "1. api (2026-07-28 13:04)", tone: "text" },
      { text: "   Provider: Codex", tone: "dim" },
      { text: "   URI: codex://019c213e", tone: "scheme" },
      { text: "   Snippet: ...the **auth** **timeout** in the retry guard...", tone: "text" },
    ],
  },
];
export type UpdateItem = {
  version: string;
  date: string;
  isLatest?: boolean;
  title: string;
  description: string;
  command?: string;
  tags: string[];
};

type UiStrings = {
  htmlLang: string;
  ogLocale: string;
  dir: "ltr";
  title: string;
  description: string;
  softwareDescription: string;
  websiteDescription: string;
  keywords: string;
  ogImageAlt: string;
  skipLink: string;
  langLabel: string;
  themeLabel: string;
  themeLight: string;
  themeDark: string;
  eyebrow: string;
  heroTitle: string;
  heroTitleAccent: string;
  heroDescription: string;
  terminalLabel: string;
  answerSummary: string;
  ctaInstall: string;
  ctaSource: string;
  providersHeading: string;
  providersNote: string;
  moreTools: { title: string; note: string };
  capabilitiesHeading: string;
  capabilities: { title: string; body: string; command: string }[];
  updatesHeading: string;
  updatesSubheading: string;
  viewFullChangelog: string;
  updates: UpdateItem[];
  installHeading: string;
  installNote: string;
  skillNote: string;
  copy: string;
  copied: string;
  faqHeading: string;
  faq: { question: string; answer: string }[];
  versionLabel: string;
  changelogLabel: string;
  footerTagline: string;
  footerGithub: string;
};

export const install = {
  nativeLabel: { en: "Native installation", zh: "原生安装", ja: "ネイティブインストール" },
  native: [
    {
      label: "curl",
      code: "curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh",
      note: {
        en: "macOS Intel / Apple Silicon · Linux x64 (glibc 2.17+). Installs to ~/.local/bin; run again to update.",
        zh: "macOS Intel / Apple Silicon · Linux x64（glibc 2.17+）。安装到 ~/.local/bin，再次运行即可更新。",
        ja: "macOS Intel / Apple Silicon・Linux x64（glibc 2.17以降）。~/.local/bin にインストール。再実行で更新できます。",
      },
    },
    {
      label: "Homebrew",
      code: "brew install xingkaixin/tap/agent-dump",
      note: {
        en: "macOS Intel / Apple Silicon · Linux x64. Update with brew upgrade agent-dump.",
        zh: "macOS Intel / Apple Silicon · Linux x64。通过 brew upgrade agent-dump 更新。",
        ja: "macOS Intel / Apple Silicon・Linux x64。brew upgrade agent-dump で更新できます。",
      },
    },
    {
      label: "Scoop",
      code: "scoop bucket add xingkaixin https://github.com/xingkaixin/scoop-bucket\nscoop install xingkaixin/agent-dump",
      note: {
        en: "Windows x64 with Scoop installed. Run in PowerShell; update with scoop update agent-dump.",
        zh: "Windows x64，需要已安装 Scoop。在 PowerShell 中运行，通过 scoop update agent-dump 更新。",
        ja: "Scoop を導入済みの Windows x64。PowerShell で実行し、scoop update agent-dump で更新できます。",
      },
    },
  ],
  globalLabel: { en: "Install globally", zh: "全局安装", ja: "グローバルにインストール" } as Record<
    Locale,
    string
  >,
  runLabel: { en: "Run without installing", zh: "免安装运行", ja: "インストールせずに実行" } as Record<
    Locale,
    string
  >,
  global: [
    { label: "uv", code: "uv tool install agent-dump" },
    { label: "npm", code: "npm install -g @agent-dump/cli" },
    { label: "pnpm", code: "pnpm add -g @agent-dump/cli" },
    { label: "bun", code: "bun add -g @agent-dump/cli" },
  ],
  run: [
    { label: "uvx", code: "uvx agent-dump --help" },
    { label: "npx", code: "npx @agent-dump/cli --help" },
    { label: "bunx", code: "bunx @agent-dump/cli --help" },
  ],
};

export const ui: Record<Locale, UiStrings> = {
  en: {
    htmlLang: "en",
    ogLocale: "en_US",
    dir: "ltr",
    title: "Agent Dump | Find, Read and Export AI Coding Sessions",
    description:
      "A local AI session CLI for individual developers and AI Agents. Search coding history, read conversations, export context with sources, and prepare reports.",
    softwareDescription:
      "A local AI session CLI for individual developers and AI Agents. Search coding history, read conversations, export context with sources, and prepare reports.",
    websiteDescription: "Find, read, export, and reuse local AI coding sessions with Agent Dump.",
    keywords:
      "agent-dump, AI session export, Claude Code sessions, Codex sessions, ZCode sessions, Cursor sessions, Pi sessions, AI coding tool, session dump, CLI export, collect prompt, agent handoff, full-text search, developer tool",
    ogImageAlt: "Agent Dump CLI exporting AI coding sessions to readable files",
    skipLink: "Skip to content",
    langLabel: "Language",
    themeLabel: "Toggle theme",
    themeLight: "Light",
    themeDark: "Dark",
    eyebrow: "CLI · Local AI session history",
    heroTitle: "Find your AI coding",
    heroTitleAccent: "history.",
    heroDescription:
      "Find past work across Codex, Claude Code, and other supported tools. Read it in your terminal, export it, or pass the context to an AI Agent. Source sessions stay read-only.",
    terminalLabel: "Terminal demo running agent-dump commands",
    answerSummary:
      "Agent Dump helps individual developers and AI Agents reuse locally saved conversations. Browse recent work, search decisions, read in bounded pages, and export sessions or cited context from one CLI.",
    ctaInstall: "Install",
    ctaSource: "GitHub",
    providersHeading: `${providers.length} tools, one URI grammar`,
    providersNote:
      "Use a session URI to read history saved on this machine. Available formats and content depend on the source tool.",
    moreTools: { title: "More tools", note: "PRs welcome" },
    capabilitiesHeading: "What it does",
    capabilities: [
      {
        title: "Find past work",
        body: "Search conversations and filter by project, Provider, role, or recent activity.",
        command: 'agent-dump --search "auth timeout"',
      },
      {
        title: "Read and hand off context",
        body: "Browse in the terminal, or give an Agent JSON pages with continuation cursors.",
        command: "agent-dump --browse",
      },
      {
        title: "Export with sources",
        body: "Export a session, or selected context with its URI and message locator. Supported formats vary by tool.",
        command: "agent-dump <uri> --format markdown",
      },
      {
        title: "Collect complete input",
        body: "Process all eligible user/assistant text in chunks. Failed reads or summaries are marked incomplete.",
        command: "agent-dump --collect",
      },
    ],
    updatesHeading: "What's New",
    updatesSubheading: "Release notes for session reading, search, export, and collect.",
    viewFullChangelog: "View full changelog on GitHub",
    updates: [
      {
        version: "v1.1.0",
        date: "2026-09-30",
        isLatest: true,
        title: "Browse Sessions and Read Search Results in Context",
        description:
          "Browse Codex, Claude Code, Cursor, Kimi, OpenCode, ZCode, Pi, and other supported AI sessions in your terminal. Search within a conversation, inspect tool details, and export the selected session. Full-text search can now return message locators for reading nearby context, while JSON query output lets scripts and agents use results directly. Source sessions remain read-only.",
        command: "npx @agent-dump/cli@1.1.0 --browse",
        tags: ["Session Reader", "Full-Text Search", "JSON Output"],
      },
      {
        version: "v1.0.0",
        date: "2026-09-25",
        title: "Native Rust CLI for AI Session Workflows",
        description:
          "v1.0.0 brings a native Rust CLI to AI session export, full-text search, AI collect, and prompt handoff for Codex, Claude Code, Cursor, and other supported tools. Keep your CLI workflows with improved startup and export performance. Install the same v1.0.0 with curl, Homebrew, or Scoop, without Python or Node.js. Python imports and python -m agent_dump are removed; API users can pin 0.15.9.",
        command: "npx @agent-dump/cli@1.0.0 --help",
        tags: ["Rust CLI", "Session Export", "Full-Text Search"],
      },
      {
        version: "v0.15.9",
        date: "2026-09-24",
        title: "Export and Search OpenCode 2.x Sessions",
        description:
          "Keep using AI session export, full-text search, and AI collect after upgrading to OpenCode 2.x. Save conversations as Markdown or JSON, access legacy-only sessions alongside newer ones, and select a custom or channel database with OPENCODE_DB. Session data stays unchanged.",
        command: 'agent-dump --list -days 30 -query "provider:opencode"',
        tags: ["OpenCode 2.x", "Session Export", "Full-Text Search"],
      },
      {
        version: "v0.15.8",
        date: "2026-09-21",
        title: "Export and Search MiniMax Code Sessions",
        description:
          "Bring your MiniMax Code CLI conversations, child tasks, and archived sessions into AI session export, full-text search, and AI collect workflows. Save Markdown or JSON without changing source data. Long installation commands now wrap on narrow screens for easier reading and copying.",
        command: 'agent-dump --list -days 30 -query "provider:minimax"',
        tags: ["MiniMax Code", "Session Export", "Full-Text Search"],
      },
      {
        version: "v0.15.7",
        date: "2026-09-19",
        title: "Export and Search DeepChat and Cherry Studio Sessions",
        description:
          "Bring saved DeepChat conversations and Cherry Studio 2.x chats and agent sessions into your AI session export, full-text search, and AI collect workflows. Export Markdown or JSON while keeping source data unchanged. New English and Chinese guides walk you through exporting Codex sessions.",
        command: 'agent-dump --list -days 30 -query "provider:deepchat,cherry"',
        tags: ["DeepChat", "Cherry Studio", "Codex Export Guides"],
      },
      {
        version: "v0.15.6",
        date: "2026-09-13",
        title: "More Reliable Collect and Up-to-Date Session Reads",
        description:
          "Keep more visible dialogue in AI collect summaries, apply query filters consistently, and see when unreadable sessions leave gaps. OpenCode and ZCode session reads and full-text search now refresh after database changes. The landing page also loads faster.",
        command: 'agent-dump --collect -days 7 -query "provider:codex path:. limit:20" --dry-run',
        tags: ["AI Collect", "Session Reliability", "Faster Loading"],
      },
      {
        version: "v0.15.5",
        date: "2026-09-05",
        title: "Resilient Collect, Provider Pre-Scoping & Visual Redesign",
        description:
          "Collect workflows now gracefully preserve partial session successes during batch failures and isolate unknown projects cleanly. Scope providers upfront before discovery to accelerate queries, paired with an all-new WebGL landing visual experience.",
        command: "agent-dump --collect --agent codex --days 7",
        tags: ["Resilient Collect", "Provider Scoping", "Visual Redesign"],
      },
      {
        version: "v0.15.4",
        date: "2026-09-01",
        title: "External Agent Handoff & Visible Dialogue Summaries",
        description:
          "Generate self-contained prompts with safe read-only URI commands using `--emit-prompt`, allowing external AI agents to autonomously collect sessions and author reports without local API configuration. Session summarization now strictly filters for visible human/assistant dialogue.",
        command: "agent-dump --collect --emit-prompt --save ./reports/weekly.md",
        tags: ["Agent Handoff", "AI Collect", "Dialogue Filter"],
      },
      {
        version: "v0.15.0",
        date: "2026-08-18",
        title: "Full-Text Search & Unified Relevance Ranking",
        description:
          "Fast SQLite FTS5 full-text indexing with intelligent CJK boundary segmentation. Search titles, transcripts, and reasoning across all seven AI coding tools with unified corpus scoring and literal phrase matching.",
        command: 'agent-dump --search "auth timeout" --days 30',
        tags: ["Full-Text Search", "FTS5", "Multi-Provider"],
      },
    ],
    installHeading: "Install",
    installNote: "Install with curl, Homebrew, or Scoop without Python or Node.js. uv and JavaScript packages remain available; JavaScript wrappers require Node.js 22+.",
    skillNote: "Or add it as an agent skill",
    copy: "Copy",
    copied: "Copied",
    faqHeading: "FAQ",
    faq: [
      {
        question: "What is Agent Dump?",
        answer:
          "Agent Dump is a local session tool for individual developers and AI Agents. Use it to find previous work, browse or page through conversations, export context with sources, and summarize eligible user/assistant text. It reads saved sessions without modifying their source data.",
      },
      {
        question: "Which AI coding tools does Agent Dump support?",
        answer:
          `Agent Dump supports ${providers.map((provider) => provider.name).join(", ")}. Formats, storage versions, and readable content vary by tool. Run agent-dump --providers --json to inspect capabilities and source paths.`,
      },
      {
        question: "How do you install Agent Dump?",
        answer:
          "Use the curl installer or Homebrew on macOS and Linux x64, or Scoop on Windows x64. These install the native CLI without Python or Node.js. You can also install with uv or npm, or run directly with uvx, npx, or bunx. See the installation section for commands and platform requirements.",
      },
    ],
    versionLabel: "Version",
    changelogLabel: "Changelog",
    footerTagline: "Find, read, and reuse local AI coding sessions.",
    footerGithub: "GitHub",
  },
  zh: {
    htmlLang: "zh-Hans",
    ogLocale: "zh_CN",
    dir: "ltr",
    title: "Agent Dump | 查找、读取与导出 AI 编码会话",
    description: "面向个人开发者与 AI Agent 的本地会话 CLI。查找编码历史、读取对话、导出带来源的上下文并生成汇总报告。",
    softwareDescription: "面向个人开发者与 AI Agent 的本地会话 CLI。查找编码历史、读取对话、导出带来源的上下文并生成汇总报告。",
    websiteDescription: "使用 Agent Dump 查找、读取、导出和复用本地 AI 编码会话。",
    keywords:
      "agent-dump, AI 会话导出, Claude Code 会话, Codex 会话, ZCode 会话, Cursor 会话, Pi 会话, AI 编码工具, 会话导出, CLI 工具, 会话收集, 外部 Agent 交接, 全文搜索, 开发者工具",
    ogImageAlt: "Agent Dump CLI 将 AI 编码会话导出为可读文件",
    skipLink: "跳到正文",
    langLabel: "语言",
    themeLabel: "切换主题",
    themeLight: "浅色",
    themeDark: "深色",
    eyebrow: "CLI · 本地 AI 会话历史",
    heroTitle: "复用你的",
    heroTitleAccent: "AI 会话。",
    heroDescription: "查找 Codex、Claude Code 等支持工具中的历史工作。在终端阅读、导出，或将上下文交给 AI Agent。会话源始终只读。",
    terminalLabel: "运行 agent-dump 命令的终端演示",
    answerSummary: "Agent Dump 帮助个人开发者与 AI Agent 复用本机保存的对话。通过一个 CLI 浏览最近工作、搜索决策、分页读取，并导出完整会话或带来源的上下文。",
    ctaInstall: "安装",
    ctaSource: "GitHub",
    providersHeading: `${providers.length} 款工具，一套 URI 语法`,
    providersNote: "通过会话 URI 读取本机保存的历史。可用格式和内容范围取决于来源工具。",
    moreTools: { title: "更多工具", note: "欢迎 PR" },
    capabilitiesHeading: "它能做什么",
    capabilities: [
      {
        title: "查找历史工作",
        body: "搜索对话，按项目、Provider、角色或最近活动筛选。",
        command: 'agent-dump --search "auth timeout"',
      },
      {
        title: "阅读与交接上下文",
        body: "在终端浏览，或让 Agent 使用 JSON 分页和游标读取。",
        command: "agent-dump --browse",
      },
      {
        title: "带来源导出",
        body: "导出会话，或保留 URI 与消息定位信息的上下文片段。可用格式取决于来源工具。",
        command: "agent-dump <uri> --format markdown",
      },
      {
        title: "完整覆盖汇总输入",
        body: "分块处理所有符合规则的 user/assistant 正文，读取或摘要失败时明确标记不完整。",
        command: "agent-dump --collect",
      },
    ],
    updatesHeading: "最新动态",
    updatesSubheading: "会话读取、搜索、导出与 collect 的版本更新。",
    viewFullChangelog: "在 GitHub 查看完整更新日志",
    updates: [
      {
        version: "v1.1.0",
        date: "2026-09-30",
        isLatest: true,
        title: "终端浏览会话，定位搜索结果的上下文",
        description:
          "在终端浏览 Codex、Claude Code、Cursor、Kimi、OpenCode、ZCode、Pi 等工具的 AI 会话，搜索对话正文、查看工具详情并导出选中的会话。全文搜索可返回消息定位符，直接读取命中位置附近的上下文；JSON 查询输出让脚本和 Agent 直接使用结果。源会话保持只读。",
        command: "npx @agent-dump/cli@1.1.0 --browse",
        tags: ["会话阅读器", "全文搜索", "JSON 输出"],
      },
      {
        version: "v1.0.0",
        date: "2026-09-25",
        title: "原生 Rust CLI：会话工作流迈入 v1.0.0",
        description:
          "v1.0.0 使用原生 Rust CLI，保留 Codex、Claude Code、Cursor 等工具的 AI 会话导出、全文搜索、AI collect 和提示词交接，改善启动与导出性能。现有 v1.0.0 也可通过 curl、Homebrew 或 Scoop 安装，无需 Python 或 Node.js。Python 导入 API 和 python -m agent_dump 已移除；旧 API 使用方可固定 0.15.9。",
        command: "npx @agent-dump/cli@1.0.0 --help",
        tags: ["Rust CLI", "会话导出", "全文搜索"],
      },
      {
        version: "v0.15.9",
        date: "2026-09-24",
        title: "导出与搜索 OpenCode 2.x 会话",
        description:
          "升级到 OpenCode 2.x 后，继续使用 AI 会话导出、全文搜索和 AI collect。可将对话保存为 Markdown 或 JSON，同时读取新版会话与旧版独有会话，并通过 OPENCODE_DB 选择自定义或 channel 数据库。源会话数据保持不变。",
        command: 'agent-dump --list -days 30 -query "provider:opencode"',
        tags: ["OpenCode 2.x", "会话导出", "全文搜索"],
      },
      {
        version: "v0.15.8",
        date: "2026-09-21",
        title: "导出与搜索 MiniMax Code 会话",
        description:
          "MiniMax Code CLI 的可见对话、子任务与归档会话现已支持统一导出、全文搜索和 AI collect。可保存为 Markdown 或 JSON，源数据保持不变。落地页的长安装命令在窄屏下自动换行，方便阅读与复制。",
        command: 'agent-dump --list -days 30 -query "provider:minimax"',
        tags: ["MiniMax Code", "会话导出", "全文搜索"],
      },
      {
        version: "v0.15.7",
        date: "2026-09-19",
        title: "导出与搜索 DeepChat、Cherry Studio 会话",
        description:
          "DeepChat 已保存对话、Cherry Studio 2.x 普通聊天与 Agent 会话现已支持统一导出、全文搜索和 AI collect。可导出为 Markdown 或 JSON，源数据保持不变。新增中英文 Codex 导出教程，从查找会话到保存文件逐步说明。",
        command: 'agent-dump --list -days 30 -query "provider:deepchat,cherry"',
        tags: ["DeepChat", "Cherry Studio", "Codex 导出教程"],
      },
      {
        version: "v0.15.6",
        date: "2026-09-13",
        title: "会话收集更可靠，读取与搜索及时更新",
        description:
          "AI collect 在预算内保留更多可见对话，一致应用查询筛选，并明确报告无法读取的会话。OpenCode 与 ZCode 数据库变化后，会话读取和全文搜索会刷新缓存内容。落地页加载也得到改善。",
        command: 'agent-dump --collect -days 7 -query "provider:codex path:. limit:20" --dry-run',
        tags: ["AI 会话收集", "会话可靠性", "加载优化"],
      },
      {
        version: "v0.15.5",
        date: "2026-09-05",
        title: "会话收集容错保留、Provider 预剪裁与全新落地页视效",
        description:
          "批量会话收集全面支持部分失败保留，单会话读取异常不再中断全局任务，未识别项目独立安全归组；按 Provider 查询时提前剪裁扫描范围。落地页全新重塑，带来多层会话聚合与激光检索视效。",
        command: "agent-dump --collect --agent codex --days 7",
        tags: ["Collect 容错", "Provider 剪裁", "视效升级"],
      },
      {
        version: "v0.15.4",
        date: "2026-09-01",
        title: "外部 Agent 提示词交接与纯净对话提取",
        description:
          "新增 `--emit-prompt` 选项，输出自包含的外部 Agent 提示词与只读 URI 指令，无需配置本地 API Key 即可交由外部 AI 独立完成会话收集与报告编写。会话摘要精准过滤工具执行与推理轨迹，仅保留用户与助手对话正文。",
        command: "agent-dump --collect --emit-prompt --save ./reports/weekly.md",
        tags: ["外部 Agent 交接", "AI 收集", "纯净对话提取"],
      },
      {
        version: "v0.15.0",
        date: "2026-08-18",
        title: "本地全文搜索与跨 Provider 统一检索",
        description:
          "内置 SQLite FTS5 全文搜索与中英文智能分词，支持跨七款 AI 编码工具秒级检索标题、正文对话与推理过程，提供全局一致的相关度打分与精确字面量匹配。",
        command: 'agent-dump --search "auth timeout" --days 30',
        tags: ["全文搜索", "FTS5", "多 Provider 检索"],
      },
    ],
    installHeading: "安装",
    installNote: "curl、Homebrew 和 Scoop 安装无需 Python 或 Node.js。也可继续使用 uv 或 JavaScript 包；JavaScript 包装器需要 Node.js 22+。",
    skillNote: "或作为 agent skill 添加",
    copy: "复制",
    copied: "已复制",
    faqHeading: "常见问题",
    faq: [
      {
        question: "Agent Dump 是什么？",
        answer:
          "Agent Dump 是面向个人开发者与 AI Agent 的本地会话工具。可查找历史工作、浏览或分页读取对话、导出带来源的上下文，以及汇总符合规则的 user/assistant 正文。读取已保存的会话，不修改源数据。",
      },
      {
        question: "Agent Dump 支持哪些 AI 编码工具？",
        answer:
          `Agent Dump 支持 ${providers.map((provider) => provider.name).join("、")}。各工具支持的格式、存储版本和内容范围有所不同。运行 agent-dump --providers --json 可检查能力与来源路径。`,
      },
      {
        question: "如何安装 Agent Dump？",
        answer:
          "macOS 和 Linux x64 可通过 curl 或 Homebrew 安装，Windows x64 可通过 Scoop 安装，均无需 Python 或 Node.js。也可继续使用 uv 或 npm 安装，或通过 uvx、npx、bunx 直接运行。具体命令和平台要求见安装区域。",
      },
    ],
    versionLabel: "版本",
    changelogLabel: "更新日志",
    footerTagline: "查找、读取和复用本地 AI 编码会话。",
    footerGithub: "GitHub",
  },
  ja: {
    htmlLang: "ja",
    ogLocale: "ja_JP",
    dir: "ltr",
    title: "Agent Dump | AIコーディング履歴を検索・閲覧・エクスポート",
    description: "個人開発者と AI Agent のためのローカルセッション CLI。履歴の検索、対話の閲覧、出典付きの文脈のエクスポート、レポート作成に対応します。",
    softwareDescription: "個人開発者と AI Agent のためのローカルセッション CLI。履歴の検索、対話の閲覧、出典付きの文脈のエクスポート、レポート作成に対応します。",
    websiteDescription: "Agent Dump でローカルの AI コーディング履歴を検索・閲覧・エクスポートして再利用。",
    keywords:
      "agent-dump, AIセッションのエクスポート, Claude Codeセッション, Codexセッション, ZCodeセッション, Cursorセッション, Piセッション, AIコーディングツール, セッション出力, CLIツール, プロンプト生成, 全文検索, 開発者ツール",
    ogImageAlt: "AIコーディングセッションを読みやすいファイルに出力するAgent Dump CLI",
    skipLink: "本文へ移動",
    langLabel: "言語",
    themeLabel: "テーマを切り替える",
    themeLight: "ライト",
    themeDark: "ダーク",
    eyebrow: "CLI · ローカルの AI セッション履歴",
    heroTitle: "AI 対話を",
    heroTitleAccent: "再利用。",
    heroDescription:
      "Codex、Claude Code などの対応ツールから過去の作業を検索。ターミナルで読む、エクスポートする、AI Agent に文脈を渡す。元のセッションは読み取り専用です。",
    terminalLabel: "agent-dumpコマンドを実行するターミナルのデモ",
    answerSummary:
      "Agent Dump は、個人開発者と AI Agent がローカルに保存した対話を再利用するための CLI です。最近の作業の閲覧、過去の判断の検索、ページ単位の読み取り、セッションや出典付きの文脈のエクスポートに対応します。",
    ctaInstall: "インストール",
    ctaSource: "GitHub",
    providersHeading: `${providers.length} のツール、1 つの URI 構文`,
    providersNote: "セッション URI で、このマシンに保存された履歴を読み取ります。利用できる形式と内容はツールによって異なります。",
    moreTools: { title: "その他のツール", note: "PRを歓迎します" },
    capabilitiesHeading: "できること",
    capabilities: [
      {
        title: "過去の作業を探す",
        body: "対話を検索し、プロジェクト、Provider、ロール、最近の更新で絞り込みます。",
        command: 'agent-dump --search "auth timeout"',
      },
      {
        title: "文脈を読んで引き継ぐ",
        body: "ターミナルで閲覧。Agent は JSON ページとカーソルで順に読み取れます。",
        command: "agent-dump --browse",
      },
      {
        title: "出典とともに書き出す",
        body: "セッション全体、または URI とメッセージ位置を含む文脈をエクスポート。形式はツールによって異なります。",
        command: "agent-dump <uri> --format markdown",
      },
      {
        title: "対象本文をすべて要約に渡す",
        body: "対象の user/assistant 本文を分割して処理。読み取りや要約の失敗は不完全として明示します。",
        command: "agent-dump --collect",
      },
    ],
    updatesHeading: "更新履歴とロードマップ",
    updatesSubheading: "セッションの閲覧、検索、エクスポート、collect の更新履歴。",
    viewFullChangelog: "GitHubで完全な変更履歴を表示",
    updates: [
      {
        version: "v1.1.0",
        date: "2026-09-30",
        isLatest: true,
        title: "ターミナルでセッションを閲覧し、検索結果の文脈を読む",
        description:
          "Codex、Claude Code、Cursor、Kimi、OpenCode、ZCode、Pi などの AI セッションをターミナルで閲覧。会話内を検索し、ツールの詳細を確認して、選択したセッションをエクスポートできます。全文検索で得たメッセージの位置から前後の文脈を読み、JSON クエリ出力をスクリプトやエージェントで直接利用できます。元のセッションは読み取り専用です。",
        command: "npx @agent-dump/cli@1.1.0 --browse",
        tags: ["セッション閲覧", "全文検索", "JSON 出力"],
      },
      {
        version: "v1.0.0",
        date: "2026-09-25",
        title: "AI セッションのワークフローをネイティブ Rust CLI で",
        description:
          "v1.0.0 はネイティブ Rust CLI に移行。Codex、Claude Code、Cursor などの AI セッションエクスポート、全文検索、AI collect、プロンプト引き継ぎを維持し、起動とエクスポートの性能を改善します。同じ v1.0.0 を curl・Homebrew・Scoop で導入でき、Python や Node.js は不要です。Python API と python -m agent_dump は削除されるため、旧 API が必要な場合は 0.15.9 に固定できます。",
        command: "npx @agent-dump/cli@1.0.0 --help",
        tags: ["Rust CLI", "セッションエクスポート", "全文検索"],
      },
      {
        version: "v0.15.9",
        date: "2026-09-24",
        title: "OpenCode 2.x のセッションをエクスポート・検索",
        description:
          "OpenCode 2.x へのアップグレード後も、AIセッションのエクスポート、全文検索、AI collect を利用できます。対話を Markdown や JSON に保存し、新しいセッションと旧形式にのみ残るセッションをまとめて参照。OPENCODE_DB でカスタム・チャネル別データベースを選択でき、元のセッションデータは変更しません。",
        command: 'agent-dump --list -days 30 -query "provider:opencode"',
        tags: ["OpenCode 2.x", "セッションエクスポート", "全文検索"],
      },
      {
        version: "v0.15.8",
        date: "2026-09-21",
        title: "MiniMax Code のセッションをエクスポート・検索",
        description:
          "MiniMax Code CLI の表示可能な対話、子タスク、アーカイブ済みセッションで、AIセッションのエクスポート、全文検索、AI collect が利用可能に。元データを変更せず Markdown や JSON に保存できます。長いインストールコマンドは狭い画面でも折り返され、読み取りやコピーがしやすくなりました。",
        command: 'agent-dump --list -days 30 -query "provider:minimax"',
        tags: ["MiniMax Code", "セッションエクスポート", "全文検索"],
      },
      {
        version: "v0.15.7",
        date: "2026-09-19",
        title: "DeepChat・Cherry Studio のセッションをエクスポート・検索",
        description:
          "DeepChat の保存済み対話と Cherry Studio 2.x のチャット・エージェントセッションで、AIセッションのエクスポート、全文検索、AI collect が利用可能に。元データを変更せず Markdown や JSON に保存できます。Codex のセッションをエクスポートする手順を解説した英語・中国語ガイドも追加しました。",
        command: 'agent-dump --list -days 30 -query "provider:deepchat,cherry"',
        tags: ["DeepChat", "Cherry Studio", "Codex エクスポートガイド"],
      },
      {
        version: "v0.15.6",
        date: "2026-09-13",
        title: "より確実なセッション収集と最新データの読み取り",
        description:
          "AI collect は文字数の上限内で対話を保持し、検索条件を一貫して適用。読み取れないセッションも明示します。OpenCode と ZCode のデータベース更新後は、セッション読み取りと全文検索のキャッシュを更新。ランディングページの読み込みも改善しました。",
        command: 'agent-dump --collect -days 7 -query "provider:codex path:. limit:20" --dry-run',
        tags: ["AIセッション収集", "セッションの信頼性", "読み込み改善"],
      },
      {
        version: "v0.15.5",
        date: "2026-09-05",
        title: "セッション収集のエラー耐性強化とProvider事前絞り込み",
        description:
          "セッション一括収集時に一部の取得失敗があっても成功分を確実に保持し、未知プロジェクトを安全に分離。Provider指定時のスキャン範囲を事前剪定して高速化。製品ランディングページのデザインとビジュアルも全面刷新。",
        command: "agent-dump --collect --agent codex --days 7",
        tags: ["収集エラー耐性", "Provider絞り込み", "デザイン刷新"],
      },
      {
        version: "v0.15.4",
        date: "2026-09-01",
        title: "外部Agentへのプロンプト引き継ぎと対話抽出",
        description:
          "`--emit-prompt`により、API設定なしで外部AIエージェントにセッション収集とレポート作成を委譲できるプロンプトを生成可能に。セッション要约時に対話本文のみを正確に抽出し、ノイズを排除します。",
        command: "agent-dump --collect --emit-prompt --save ./reports/weekly.md",
        tags: ["Agent引き継ぎ", "AI要約", "対話抽出"],
      },
      {
        version: "v0.15.0",
        date: "2026-08-18",
        title: "ローカル全文検索とプロバイダー横断スコアリング",
        description:
          "SQLite FTS5による高速な全文検索を搭載。7つのAIツールのタイトル、対話、推論履歴を横断して瞬時に検索し、一貫したスコアで関連セッションを見つけ出せます。",
        command: 'agent-dump --search "auth timeout" --days 30',
        tags: ["全文検索", "FTS5", "マルチプロバイダー"],
      },
    ],
    installHeading: "インストール",
    installNote:
      "curl、Homebrew、Scoop なら Python や Node.js は不要です。uv と JavaScript パッケージも利用できます。JavaScript ラッパーには Node.js 22 以降が必要です。",
    skillNote: "またはagent skillとして追加",
    copy: "コピー",
    copied: "コピーしました",
    faqHeading: "よくある質問",
    faq: [
      {
        question: "Agent Dumpとは何ですか？",
        answer:
          "Agent Dump は、個人開発者と AI Agent のためのローカルセッションツールです。過去の作業を検索し、対話を閲覧またはページ単位で読み取り、出典付きの文脈をエクスポートし、対象の user/assistant 本文を要約できます。保存済みのセッションを読み取り、元データは変更しません。",
      },
      {
        question: "Agent DumpはどのAIコーディングツールに対応していますか？",
        answer:
          `Agent Dump は ${providers.map((provider) => provider.name).join("、")} に対応しています。形式、ストレージのバージョン、読み取れる内容はツールによって異なります。agent-dump --providers --json で機能と読み取り元のパスを確認できます。`,
      },
      {
        question: "Agent Dumpをインストールするには？",
        answer:
          "macOS と Linux x64 では curl または Homebrew、Windows x64 では Scoop でインストールできます。Python や Node.js は不要です。uv や npm によるインストール、uvx・npx・bunx による直接実行も利用できます。コマンドと対応環境はインストール欄をご覧ください。",
      },
    ],
    versionLabel: "バージョン",
    changelogLabel: "変更履歴",
    footerTagline: "ローカルの AI コーディング履歴を検索・閲覧・再利用。",
    footerGithub: "GitHub",
  },
};
