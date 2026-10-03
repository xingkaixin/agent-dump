import type { Locale } from "./i18n";

export interface Guide {
  locale: "en" | "zh";
  slug: string;
  title: string;
  description: string;
  category: "export" | "search" | "handoff" | "reports";
  order: number;
  updated: string;
}

async function entries() {
  const modules = import.meta.glob<{ frontmatter: Guide }>(
    "../pages/**/guides/*.md",
  );
  const pages = await Promise.all(Object.values(modules).map((load) => load()));
  return pages.map((page) => page.frontmatter);
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
  return (await entries())
    .filter((entry) => entry.locale === (locale === "ja" ? "en" : locale))
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
    contents: "On this page",
    related: "Continue reading",
    updated: "Updated",
    home: "Home",
    filter: "Filter guides",
    empty: "No guides match. Try another keyword.",
    search: "Search guides",
    note: "Start with a task. Leave with a command.",
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
    contents: "本文目录",
    related: "继续阅读",
    updated: "更新于",
    home: "首页",
    filter: "筛选指南",
    empty: "没有匹配的指南，试试其他关键词。",
    search: "搜索指南",
    note: "找到你的场景，直接开始操作。",
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
      "AIとの対話の検索、エクスポート、引き継ぎを実際のコマンドで解説します。記事は英語で提供しています。",
    all: "すべてのガイド",
    read: "ガイドを読む（英語）",
    contents: "目次",
    related: "関連ガイド",
    updated: "更新日",
    home: "ホーム",
    filter: "ガイドを絞り込む",
    empty: "一致するガイドはありません。別のキーワードをお試しください。",
    search: "ガイドを検索",
    note: "目的に合うガイドから始めましょう。記事は英語です。",
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
};
export const codexGuideLinks = {
  en: { href: codexGuidePaths.en, label: "Export a Codex session to Markdown" },
  zh: { href: codexGuidePaths.zh, label: "将 Codex 会话导出为 Markdown" },
  ja: {
    href: codexGuidePaths.en,
    label: "CodexセッションをMarkdownにエクスポート（英語）",
  },
};
