// Single source of truth for landing-page content, typed and shared across locales.
// SEO-critical strings (title / description / keywords / FAQ) are kept stable to
// preserve existing search ranking.

export const LOCALES = ["en", "zh"] as const;
export type Locale = (typeof LOCALES)[number];

export const site = {
  origin: "https://agent-dump.xingkaixin.me",
  paths: { en: "/", zh: "/zh/" } as Record<Locale, string>,
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
  } as Record<Locale, string>,
  cfBeaconToken: "004af8c09ea3455ea8a2b53f0a913be2",
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

// Commands the CLI actually accepts; used by the hero terminal typewriter.
export const typingCommands = [
  "agent-dump --interactive",
  "agent-dump zcode://sess-abc123 --format json",
  "agent-dump codex://threads/abc123 --format json",
  "agent-dump pi://019e7978-b2ec --head",
  'agent-dump --search "auth timeout"',
  "agent-dump --stats --days 30",
  "agent-dump --collect --dry-run",
];

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
  answerSummary: string;
  ctaInstall: string;
  ctaSource: string;
  providersHeading: string;
  providersNote: string;
  capabilitiesHeading: string;
  capabilities: { title: string; body: string; command: string }[];
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
  globalLabel: { en: "Install globally", zh: "全局安装" } as Record<Locale, string>,
  runLabel: { en: "Run without installing", zh: "免安装运行" } as Record<Locale, string>,
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
      "agent-dump, AI session export, Claude Code sessions, Codex sessions, ZCode sessions, Cursor sessions, Pi sessions, AI coding tool, session dump, CLI export, developer tool",
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
    answerSummary:
      "Agent Dump gives developers one command-line interface for local AI coding session history across seven tools. It turns provider-specific session stores into readable exports, direct URI views, search results, stats, and collection reports.",
    ctaInstall: "Install",
    ctaSource: "GitHub",
    providersHeading: "Seven tools, one URI grammar",
    providersNote:
      "Every session is addressable by its provider scheme. Point agent-dump at a URI and read it anywhere.",
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
    installHeading: "Install",
    installNote: "Works with uv, npm, pnpm, and bun.",
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
      "agent-dump, AI 会话导出, Claude Code 会话, Codex 会话, ZCode 会话, Cursor 会话, Pi 会话, AI 编码工具, 会话导出, CLI 工具, 开发者工具",
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
    answerSummary:
      "Agent Dump 为开发者提供一个统一的命令行入口，读取七类 AI 编码工具的本地会话历史，并输出可读导出、URI 直读、搜索结果、统计和汇总报告。",
    ctaInstall: "安装",
    ctaSource: "GitHub",
    providersHeading: "七款工具，一套 URI 语法",
    providersNote:
      "每个会话都能用它的 provider scheme 寻址。把 agent-dump 指向一个 URI，就能在任何地方读取它。",
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
    installHeading: "安装",
    installNote: "支持 uv、npm、pnpm 和 bun。",
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
};

export function otherLocale(locale: Locale): Locale {
  return locale === "en" ? "zh" : "en";
}
