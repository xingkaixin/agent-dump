import type { Locale } from "./i18n";

export const codexGuidePaths = {
  en: "/guides/export-codex-session/",
  zh: "/zh/guides/export-codex-session/",
};

export const codexGuideLinks = {
  en: { href: codexGuidePaths.en, label: "Export a Codex session to Markdown" },
  zh: { href: codexGuidePaths.zh, label: "将 Codex 会话导出为 Markdown" },
  ja: { href: codexGuidePaths.en, label: "CodexセッションをMarkdownにエクスポート（英語）" },
} satisfies Record<Locale, { href: string; label: string }>;
