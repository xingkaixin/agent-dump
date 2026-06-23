// Single source of truth for the landing page content.
// Consumed at build time by build-site.mjs to pre-render one static HTML per locale.

export const LOCALES = ["en", "zh"];

export const site = {
  origin: "https://agent-dump.xingkaixin.me",
  paths: { en: "/", zh: "/zh/" },
  author: { name: "xingkaixin", url: "https://github.com/xingkaixin" },
  repo: "https://github.com/xingkaixin/agent-dump",
  license: "https://github.com/xingkaixin/agent-dump/blob/main/LICENSE",
  downloadUrls: [
    "https://www.npmjs.com/package/@agent-dump/cli",
    "https://pypi.org/project/agent-dump/",
  ],
  logo: "/assets/logo.png",
  ogImage: { path: "/assets/og-image.png", width: 1200, height: 631 },
  changelogUrl: {
    en: "https://github.com/xingkaixin/agent-dump/blob/main/CHANGELOG.md",
    zh: "https://github.com/xingkaixin/agent-dump/blob/main/docs/zh/CHANGELOG.md",
  },
};

const installGroups = {
  en: [
    {
      label: "Install globally",
      tabs: [
        { label: "uv", code: "uv tool install agent-dump" },
        { label: "npm", code: "npm install -g @agent-dump/cli" },
        { label: "pnpm", code: "pnpm add -g @agent-dump/cli" },
        { label: "bun", code: "bun add -g @agent-dump/cli" },
      ],
    },
    {
      label: "Run without installing",
      tabs: [
        { label: "uvx", code: "uvx agent-dump --help" },
        { label: "npx", code: "npx @agent-dump/cli --help" },
        { label: "bunx", code: "bunx @agent-dump/cli --help" },
      ],
    },
  ],
  zh: [
    {
      label: "全局安装",
      tabs: [
        { label: "uv", code: "uv tool install agent-dump" },
        { label: "npm", code: "npm install -g @agent-dump/cli" },
        { label: "pnpm", code: "pnpm add -g @agent-dump/cli" },
        { label: "bun", code: "bun add -g @agent-dump/cli" },
      ],
    },
    {
      label: "免安装运行",
      tabs: [
        { label: "uvx", code: "uvx agent-dump --help" },
        { label: "npx", code: "npx @agent-dump/cli --help" },
        { label: "bunx", code: "bunx @agent-dump/cli --help" },
      ],
    },
  ],
};

export const TYPING_COMMANDS = [
  "agent-dump --interactive",
  "agent-dump zcode://sess-abc123 --format json",
  "agent-dump codex://threads/abc123 --format json",
  "agent-dump pi://019e7978-b2ec --head",
  'agent-dump --search "auth timeout"',
  "agent-dump --stats -days 30",
  "agent-dump --collect --dry-run",
];

export const locales = {
  en: {
    htmlLang: "en",
    ogLocale: "en_US",
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
    install: installGroups.en,
    ui: {
      skipLink: "Skip to content",
      langLabel: "Language switch",
      eyebrow: "CLI · AI Session Export",
      heroTitle: "Export AI coding sessions.",
      heroDescription:
        "List, dump, export, summarize, and search sessions from Codex, Claude Code, ZCode, Kimi, OpenCode, Cursor, and Pi.",
      answerSummary:
        "Agent Dump gives developers one command-line interface for local AI coding session history across seven tools. It turns provider-specific session stores into readable exports, direct URI views, search results, stats, and collection reports.",
      versionLabel: "Version",
      installHeading: "Install",
      skillNote: "Or add as an agent skill:",
      capabilitiesHeading: "What Agent Dump does",
      capabilities: [
        "Reads local sessions from Codex, Claude Code, ZCode, Kimi, OpenCode, Cursor, and Pi.",
        "Exports sessions as JSON, Markdown, raw files, or direct terminal output.",
        "Searches recent session history and filters by provider, role, path, or query URI.",
        "Collects high-signal session summaries for project management and insight reports.",
      ],
      capabilitiesAria: "Agent Dump capabilities",
      faqHeading: "Agent Dump FAQ",
      footerGithub: "GitHub",
      copy: "Copy",
      copied: "Copied",
    },
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
  },
  zh: {
    htmlLang: "zh-Hans",
    ogLocale: "zh_CN",
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
    install: installGroups.zh,
    ui: {
      skipLink: "跳到正文",
      langLabel: "语言切换",
      eyebrow: "CLI · AI 会话导出",
      heroTitle: "导出 AI 编码会话。",
      heroDescription:
        "一条 CLI 统一处理 Codex、Claude Code、ZCode、Kimi、OpenCode、Cursor 和 Pi 的列表、直读、导出、汇总、搜索与统计。",
      answerSummary:
        "Agent Dump 为开发者提供一个统一的命令行入口，读取七类 AI 编码工具的本地会话历史，并输出可读导出、URI 直读、搜索结果、统计和汇总报告。",
      versionLabel: "当前版本",
      installHeading: "安装",
      skillNote: "或作为 agent skill 添加：",
      capabilitiesHeading: "Agent Dump 能做什么",
      capabilities: [
        "读取 Codex、Claude Code、ZCode、Kimi、OpenCode、Cursor 和 Pi 的本地会话。",
        "导出 JSON、Markdown、raw 文件，或直接在终端打印会话内容。",
        "搜索近期会话历史，并按 provider、role、path 或 query URI 过滤。",
        "收集高信号会话摘要，生成项目管理和洞察报告。",
      ],
      capabilitiesAria: "Agent Dump 能力",
      faqHeading: "Agent Dump 常见问题",
      footerGithub: "GitHub",
      copy: "复制",
      copied: "已复制",
    },
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
  },
};
