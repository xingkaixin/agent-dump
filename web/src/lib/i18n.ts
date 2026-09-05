// Single source of truth for landing-page content, typed and shared across locales.
// SEO-critical strings (title / description / keywords / FAQ) are kept stable to
// preserve existing search ranking.

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

// Every supported provider shown with its real URI scheme (see agent_registry.py).
// The scheme prefixes are accurate; session ids are illustrative placeholders.
export const providers = [
  { name: "Codex", example: "codex://threads/a1b2c3" },
  { name: "Claude Code", example: "claude://a1b2c3d4" },
  { name: "ZCode", example: "zcode://sess-9f8e7d" },
  { name: "Kimi", example: "kimi://k-7a3f21" },
  { name: "OpenCode", example: "opencode://5c4b3a" },
  { name: "Cursor", example: "cursor://req-8821" },
  { name: "Pi", example: "pi://019e7978-b2ec" },
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
    title: "Agent Dump | Export AI Coding Sessions from CLI",
    description:
      "Agent Dump is a CLI for listing, exporting, searching, and summarizing AI coding sessions from Codex, Claude Code, ZCode, Kimi, OpenCode, Cursor, and Pi.",
    softwareDescription:
      "Agent Dump is a CLI for listing, exporting, searching, and summarizing AI coding sessions from Codex, Claude Code, ZCode, Kimi, OpenCode, Cursor, and Pi.",
    websiteDescription:
      "Agent Dump is a CLI for listing, exporting, searching, and summarizing AI coding sessions.",
    keywords:
      "agent-dump, AI session export, Claude Code sessions, Codex sessions, ZCode sessions, Cursor sessions, Pi sessions, AI coding tool, session dump, CLI export, collect prompt, agent handoff, full-text search, developer tool",
    ogImageAlt: "Agent Dump CLI exporting AI coding sessions to readable files",
    skipLink: "Skip to content",
    langLabel: "Language",
    themeLabel: "Toggle theme",
    themeLight: "Light",
    themeDark: "Dark",
    eyebrow: "CLI · AI session export",
    heroTitle: "Export your AI coding",
    heroTitleAccent: "sessions.",
    heroDescription:
      "One command lists, dumps, searches, and summarizes sessions across seven AI coding tools.",
    terminalLabel: "Terminal demo running agent-dump commands",
    answerSummary:
      "Agent Dump gives developers one command-line interface for local AI coding session history across seven tools. It turns provider-specific session stores into readable exports, direct URI views, search results, stats, and collection reports.",
    ctaInstall: "Install",
    ctaSource: "GitHub",
    providersHeading: "Seven tools, one URI grammar",
    providersNote:
      "Every session is addressable by its provider scheme. Point agent-dump at a URI and read it anywhere.",
    moreTools: { title: "More tools", note: "PRs welcome" },
    capabilitiesHeading: "What it does",
    capabilities: [
      {
        title: "Reads every local session",
        body: "Codex, Claude Code, ZCode, Kimi, OpenCode, Cursor, and Pi, from their native stores.",
        command: "agent-dump --interactive",
      },
      {
        title: "Exports in your format",
        body: "JSON, Markdown, raw files, or straight to the terminal for piping.",
        command: "agent-dump <uri> --format markdown",
      },
      {
        title: "Searches and filters",
        body: "Full-text search across titles, messages, and reasoning; filter by provider, role, or path.",
        command: 'agent-dump --search "auth timeout"',
      },
      {
        title: "Collects summaries",
        body: "High-signal session digests for project management and insight reports.",
        command: "agent-dump --collect",
      },
    ],
    updatesHeading: "What's New",
    updatesSubheading:
      "Continuous evolution towards seamless multi-agent coding workflows, deep search, and high-signal session memory.",
    viewFullChangelog: "View full changelog on GitHub",
    updates: [
      {
        version: "v0.15.5",
        date: "2026-09-05",
        isLatest: true,
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
    installNote: "Works with uv, npm, pnpm, and bun. JavaScript package wrappers require Node.js 22+.",
    skillNote: "Or add it as an agent skill",
    copy: "Copy",
    copied: "Copied",
    faqHeading: "FAQ",
    faq: [
      {
        question: "What is Agent Dump?",
        answer:
          "Agent Dump is a command-line tool for listing, exporting, searching, and summarizing local AI coding sessions. It supports Codex, Claude Code, ZCode, Kimi, OpenCode, Cursor, and Pi so developers can inspect session history from one CLI.",
      },
      {
        question: "Which AI coding tools does Agent Dump support?",
        answer:
          "Agent Dump supports Codex, Claude Code, ZCode, Kimi, OpenCode, Cursor, and Pi. It reads local session sources for each provider and exposes a shared CLI for listing sessions, direct URI viewing, exporting, search, stats, and collection workflows.",
      },
      {
        question: "How do you install Agent Dump?",
        answer:
          "Install Agent Dump globally with uv tool install agent-dump or npm install -g @agent-dump/cli. You can also run it directly with uvx agent-dump --help, npx @agent-dump/cli --help, or bunx @agent-dump/cli --help.",
      },
    ],
    versionLabel: "Version",
    changelogLabel: "Changelog",
    footerTagline: "Export AI coding sessions from the CLI.",
    footerGithub: "GitHub",
  },
  zh: {
    htmlLang: "zh-Hans",
    ogLocale: "zh_CN",
    dir: "ltr",
    title: "Agent Dump | AI 编码会话导出工具",
    description:
      "Agent Dump 是一个命令行工具，用于列出、导出、搜索和汇总 Codex、Claude Code、ZCode、Kimi、OpenCode、Cursor 和 Pi 的 AI 编码会话。",
    softwareDescription:
      "Agent Dump 是一个命令行工具，用于列出、导出、搜索和汇总 Codex、Claude Code、ZCode、Kimi、OpenCode、Cursor 和 Pi 的 AI 编码会话。",
    websiteDescription:
      "Agent Dump 是一个用于列出、导出、搜索和汇总 AI 编码会话的命令行工具。",
    keywords:
      "agent-dump, AI 会话导出, Claude Code 会话, Codex 会话, ZCode 会话, Cursor 会话, Pi 会话, AI 编码工具, 会话导出, CLI 工具, 会话收集, 外部 Agent 交接, 全文搜索, 开发者工具",
    ogImageAlt: "Agent Dump CLI 将 AI 编码会话导出为可读文件",
    skipLink: "跳到正文",
    langLabel: "语言",
    themeLabel: "切换主题",
    themeLight: "浅色",
    themeDark: "深色",
    eyebrow: "CLI · AI 会话导出",
    heroTitle: "导出你的 AI 编码",
    heroTitleAccent: "会话。",
    heroDescription:
      "一条命令，列出、直读、导出、搜索并汇总七款 AI 编码工具的会话。",
    terminalLabel: "运行 agent-dump 命令的终端演示",
    answerSummary:
      "Agent Dump 为开发者提供一个统一的命令行入口，读取七类 AI 编码工具的本地会话历史，并输出可读导出、URI 直读、搜索结果、统计和汇总报告。",
    ctaInstall: "安装",
    ctaSource: "GitHub",
    providersHeading: "七款工具，一套 URI 语法",
    providersNote:
      "每个会话都能用它的 provider scheme 寻址。把 agent-dump 指向一个 URI，就能在任何地方读取它。",
    moreTools: { title: "更多工具", note: "欢迎 PR" },
    capabilitiesHeading: "它能做什么",
    capabilities: [
      {
        title: "读取每一个本地会话",
        body: "从 Codex、Claude Code、ZCode、Kimi、OpenCode、Cursor 和 Pi 的原生存储中读取。",
        command: "agent-dump --interactive",
      },
      {
        title: "按你的格式导出",
        body: "JSON、Markdown、raw 文件，或直接打印到终端以便管道处理。",
        command: "agent-dump <uri> --format markdown",
      },
      {
        title: "搜索与过滤",
        body: "对标题、消息与推理做全文搜索；按 provider、role 或 path 过滤。",
        command: 'agent-dump --search "auth timeout"',
      },
      {
        title: "汇总摘要",
        body: "高信号会话摘要，用于项目管理和洞察报告。",
        command: "agent-dump --collect",
      },
    ],
    updatesHeading: "最新动态",
    updatesSubheading:
      "持续演进，打通多 AI 编程助手的会话连接、本地深度检索与自主摘要工作流。",
    viewFullChangelog: "在 GitHub 查看完整更新日志",
    updates: [
      {
        version: "v0.15.5",
        date: "2026-09-05",
        isLatest: true,
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
    installNote: "支持 uv、npm、pnpm 和 bun；JavaScript 包装器需要 Node.js 22+。",
    skillNote: "或作为 agent skill 添加",
    copy: "复制",
    copied: "已复制",
    faqHeading: "常见问题",
    faq: [
      {
        question: "Agent Dump 是什么？",
        answer:
          "Agent Dump 是一个用于列出、导出、搜索和汇总本地 AI 编码会话的命令行工具。它支持 Codex、Claude Code、ZCode、Kimi、OpenCode、Cursor 和 Pi，让开发者用一个 CLI 查看会话历史。",
      },
      {
        question: "Agent Dump 支持哪些 AI 编码工具？",
        answer:
          "Agent Dump 支持 Codex、Claude Code、ZCode、Kimi、OpenCode、Cursor 和 Pi。它读取每个 provider 的本地会话源，并提供列表、URI 直读、导出、搜索、统计和 collect 工作流。",
      },
      {
        question: "如何安装 Agent Dump？",
        answer:
          "可以用 uv tool install agent-dump 或 npm install -g @agent-dump/cli 全局安装 Agent Dump。也可以直接运行 uvx agent-dump --help、npx @agent-dump/cli --help 或 bunx @agent-dump/cli --help。",
      },
    ],
    versionLabel: "版本",
    changelogLabel: "更新日志",
    footerTagline: "在命令行里导出 AI 编码会话。",
    footerGithub: "GitHub",
  },
  ja: {
    htmlLang: "ja",
    ogLocale: "ja_JP",
    dir: "ltr",
    title: "Agent Dump | AIコーディングセッションをCLIからエクスポート",
    description:
      "Agent Dumpは、Codex、Claude Code、ZCode、Kimi、OpenCode、Cursor、PiのAIコーディングセッションを一覧表示、エクスポート、検索、要約するCLIです。",
    softwareDescription:
      "Agent Dumpは、Codex、Claude Code、ZCode、Kimi、OpenCode、Cursor、PiのAIコーディングセッションを一覧表示、エクスポート、検索、要約するCLIです。",
    websiteDescription:
      "Agent Dumpは、AIコーディングセッションを一覧表示、エクスポート、検索、要約するCLIです。",
    keywords:
      "agent-dump, AIセッションのエクスポート, Claude Codeセッション, Codexセッション, ZCodeセッション, Cursorセッション, Piセッション, AIコーディングツール, セッション出力, CLIツール, プロンプト生成, 全文検索, 開発者ツール",
    ogImageAlt: "AIコーディングセッションを読みやすいファイルに出力するAgent Dump CLI",
    skipLink: "本文へ移動",
    langLabel: "言語",
    themeLabel: "テーマを切り替える",
    themeLight: "ライト",
    themeDark: "ダーク",
    eyebrow: "CLI · AIセッションのエクスポート",
    heroTitle: "AIコーディングの",
    heroTitleAccent: "セッションを書き出す。",
    heroDescription:
      "1つのコマンドで、7つのAIコーディングツールのセッションを一覧表示、閲覧、エクスポート、検索、要約できます。",
    terminalLabel: "agent-dumpコマンドを実行するターミナルのデモ",
    answerSummary:
      "Agent Dumpは、7つのAIコーディングツールに保存されたローカルセッション履歴を、1つのコマンドラインインターフェースから扱えるようにします。各ツール固有の保存形式を、読みやすいエクスポート、URIによる直接表示、検索結果、統計、収集レポートへ変換します。",
    ctaInstall: "インストール",
    ctaSource: "GitHub",
    providersHeading: "7つのツール、1つのURI構文",
    providersNote:
      "各セッションはツールごとのスキームで指定できます。agent-dumpにURIを渡せば、どこからでも内容を確認できます。",
    moreTools: { title: "その他のツール", note: "PRを歓迎します" },
    capabilitiesHeading: "できること",
    capabilities: [
      {
        title: "すべてのローカルセッションを読み込む",
        body: "Codex、Claude Code、ZCode、Kimi、OpenCode、Cursor、Piのネイティブストレージから読み込みます。",
        command: "agent-dump --interactive",
      },
      {
        title: "必要な形式でエクスポートする",
        body: "JSON、Markdown、rawファイルに出力でき、パイプ処理のためにターミナルへ直接表示することもできます。",
        command: "agent-dump <uri> --format markdown",
      },
      {
        title: "検索して絞り込む",
        body: "タイトル、メッセージ、推論を全文検索し、provider、role、pathで絞り込めます。",
        command: 'agent-dump --search "auth timeout"',
      },
      {
        title: "セッションを要約する",
        body: "プロジェクト管理やインサイトレポートに使える、重要度の高いセッション要約を生成します。",
        command: "agent-dump --collect",
      },
    ],
    updatesHeading: "更新履歴とロードマップ",
    updatesSubheading:
      "複数のAIコーディングツールのセッション統合、高速検索、自動要約に向けて進化し続けています。",
    viewFullChangelog: "GitHubで完全な変更履歴を表示",
    updates: [
      {
        version: "v0.15.5",
        date: "2026-09-05",
        isLatest: true,
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
      "uv、npm、pnpm、bunに対応しています。JavaScriptパッケージのラッパーにはNode.js 22以降が必要です。",
    skillNote: "またはagent skillとして追加",
    copy: "コピー",
    copied: "コピーしました",
    faqHeading: "よくある質問",
    faq: [
      {
        question: "Agent Dumpとは何ですか？",
        answer:
          "Agent Dumpは、ローカルのAIコーディングセッションを一覧表示、エクスポート、検索、要約するコマンドラインツールです。Codex、Claude Code、ZCode、Kimi、OpenCode、Cursor、Piに対応し、1つのCLIからセッション履歴を確認できます。",
      },
      {
        question: "Agent DumpはどのAIコーディングツールに対応していますか？",
        answer:
          "Agent Dumpは、Codex、Claude Code、ZCode、Kimi、OpenCode、Cursor、Piに対応しています。各ツールのローカルセッションを読み込み、一覧表示、URIによる直接表示、エクスポート、検索、統計、収集ワークフローを共通のCLIで提供します。",
      },
      {
        question: "Agent Dumpをインストールするには？",
        answer:
          "uv tool install agent-dumpまたはnpm install -g @agent-dump/cliでグローバルにインストールできます。uvx agent-dump --help、npx @agent-dump/cli --help、bunx @agent-dump/cli --helpで直接実行することもできます。",
      },
    ],
    versionLabel: "バージョン",
    changelogLabel: "変更履歴",
    footerTagline: "AIコーディングセッションをCLIからエクスポート。",
    footerGithub: "GitHub",
  },
};
