import type { Locale } from "./i18n";

export interface GuideFaq {
  question: string;
  answer: string;
}

export interface Guide {
  locale: Locale;
  slug: string;
  title: string;
  description: string;
  category: "export" | "search" | "handoff" | "reports";
  order: number;
  updated: string;
  faq?: GuideFaq[];
}

function parseFrontmatter(raw: string): Guide {
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  const data: Record<string, string> = {};
  if (match) {
    for (const line of match[1].split(/\r?\n/)) {
      if (!line || /^\s/.test(line)) continue;
      const idx = line.indexOf(":");
      if (idx <= 0) continue;
      const key = line.slice(0, idx).trim();
      let value = line.slice(idx + 1).trim();
      if (!value) continue;
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      data[key] = value;
    }
  }
  return {
    locale: data.locale as Locale,
    slug: data.slug,
    title: data.title,
    description: data.description,
    category: data.category as Guide["category"],
    order: Number(data.order),
    updated: data.updated,
  };
}

const rawGuides = import.meta.glob<string>("../pages/**/guides/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
});

const allGuides: Guide[] = Object.values(rawGuides).map(parseFrontmatter);

async function entries() {
  return allGuides;
}

export const guideIndexPaths = {
  en: "/guides/",
  zh: "/zh/guides/",
  ja: "/ja/guides/",
};

export async function guidePaths(
  slug: string,
): Promise<Partial<Record<Locale, string>>> {
  return Object.fromEntries(
    (await entries())
      .filter((entry) => entry.slug === slug)
      .map((entry) => [
        entry.locale,
        `${guideIndexPaths[entry.locale]}${slug}/`,
      ]),
  );
}

export async function getGuides(locale: Locale) {
  const all = await entries();
  const bySlug = new Map<string, Guide>();
  for (const entry of all) {
    if (entry.locale === "en" && !bySlug.has(entry.slug)) {
      bySlug.set(entry.slug, entry);
    }
    if (entry.locale === locale) {
      bySlug.set(entry.slug, entry);
    }
  }
  return [...bySlug.values()]
    .filter((entry) => entry.locale === locale || locale === "ja")
    .sort((a, b) => a.order - b.order)
    .map((entry) => ({
      ...entry,
      href: `${guideIndexPaths[entry.locale]}${entry.slug}/`,
    }));
}

export const guideUi = {
  en: {
    label: "Guides",
    seoTitle: "AI Session Export, Search & Handoff Guides",
    title: "Make your history useful.",
    description:
      "Practical guides to finding, exporting, and reusing your AI coding conversations. Real commands, from the first search to the next project.",
    all: "All guides",
    read: "Read guide",
    readFallback: "Read guide",
    contents: "On this page",
    related: "Continue reading",
    updated: "Updated",
    home: "Home",
    filter: "Filter guides",
    empty: "No guides match. Try another keyword.",
    search: "Search guides",
    note: "Start with a task. Leave with a command.",
    count: "{count} guides",
    found: "{count} of {total} guides",
    clear: "Clear search and filters",
    faqHeading: "Common questions",
    quickInstallTitle: "Install Agent Dump",
    quickInstallNote: "Free, open-source, read-only local CLI. Source session files are never modified.",
    allInstallOptions: "All install options",
    providerGuideLabel: "Guide",
    categories: {
      export: "Export & archive",
      search: "Search & read",
      handoff: "Agent handoff",
      reports: "Work reports",
    },
  },
  zh: {
    label: "使用说明",
    seoTitle: "AI 会话导出、搜索与上下文交接指南",
    title: "让历史对话，继续有用。",
    description:
      "从找回一次讨论，到导出记录、交接上下文和整理周报。每篇指南都从具体场景出发，提供可以照着操作的命令。",
    all: "全部指南",
    read: "阅读指南",
    readFallback: "阅读指南",
    contents: "本文目录",
    related: "继续阅读",
    updated: "更新于",
    home: "首页",
    filter: "筛选指南",
    empty: "没有匹配的指南，试试其他关键词。",
    search: "搜索指南",
    note: "找到你的场景，直接开始操作。",
    count: "共 {count} 篇指南",
    found: "找到 {count} / {total} 篇指南",
    clear: "清除搜索与筛选",
    faqHeading: "常见问题",
    quickInstallTitle: "安装 Agent Dump",
    quickInstallNote: "免费开源、本地只读 CLI，不会修改任何源会话文件。",
    allInstallOptions: "全部安装方式",
    providerGuideLabel: "指南",
    categories: {
      export: "导出与归档",
      search: "搜索与阅读",
      handoff: "Agent 交接",
      reports: "工作报告",
    },
  },
  ja: {
    label: "使い方",
    seoTitle: "AIセッションのエクスポート・検索・引き継ぎガイド",
    title: "対話の履歴を、次の仕事へ。",
    description:
      "AIとの対話の検索、エクスポート、引き継ぎを実際のコマンドで解説します。主要ガイドは日本語で読めます。",
    all: "すべてのガイド",
    read: "ガイドを読む",
    readFallback: "ガイドを読む（英語）",
    contents: "目次",
    related: "関連ガイド",
    updated: "更新日",
    home: "ホーム",
    filter: "ガイドを絞り込む",
    empty: "一致するガイドはありません。別のキーワードをお試しください。",
    search: "ガイドを検索",
    note: "目的に合うガイドから始めましょう。未翻訳の記事は英語で提供しています。",
    count: "全 {count} 件のガイド",
    found: "{total} 件中 {count} 件のガイド",
    clear: "検索と絞り込みをクリア",
    faqHeading: "よくある質問",
    quickInstallTitle: "Agent Dump をインストール",
    quickInstallNote: "無料のオープンソース CLI。ローカルの元セッションは変更しません。",
    allInstallOptions: "すべてのインストール方法",
    providerGuideLabel: "ガイド",
    categories: {
      export: "エクスポート",
      search: "検索と閲覧",
      handoff: "Agentへの引き継ぎ",
      reports: "作業レポート",
    },
  },
};

export const codexGuidePaths = {
  en: "/guides/export-codex-session/",
  zh: "/zh/guides/export-codex-session/",
  ja: "/ja/guides/export-codex-session/",
};
export const codexGuideLinks = {
  en: { href: codexGuidePaths.en, label: "Export Codex Sessions to Markdown and JSON" },
  zh: { href: codexGuidePaths.zh, label: "将 Codex 会话导出为 Markdown" },
  ja: {
    href: codexGuidePaths.ja,
    label: "Codex セッションを Markdown・JSON にエクスポート",
  },
};

export const providerGuideSlugs: Record<string, string> = {
  Codex: "export-codex-session",
  "Claude Code": "export-claude-code-conversations",
  Cursor: "export-cursor-chat-history",
  "Gemini CLI": "export-gemini-cli-sessions",
  OpenCode: "export-opencode-sessions",
  "Cherry Studio": "export-cherry-studio-conversations",
};

export async function providerGuideMap(locale: Locale): Promise<Record<string, string>> {
  const guides = await getGuides(locale);
  const bySlug = new Map(guides.map((guide) => [guide.slug, guide.href]));
  const result: Record<string, string> = {};
  for (const [provider, slug] of Object.entries(providerGuideSlugs)) {
    const href = bySlug.get(slug);
    if (href) result[provider] = href;
  }
  return result;
}
