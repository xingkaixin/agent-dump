import { useState } from "react";
import { MagnifyingGlassIcon, ArrowUpRightIcon } from "@phosphor-icons/react";
import { Tabs } from "@base-ui/react/tabs";
import { CopyButton } from "./CopyButton";
import type { Locale } from "../lib/i18n";

const samples = [
  {
    provider: "Codex",
    scheme: "codex",
    title: "Fix the auth timeout",
    user: "Why does the session expire during a long request?",
    assistant:
      "The refresh token expires before the retry completes. Refresh it before retrying, then test the timeout boundary.",
  },
  {
    provider: "Claude Code",
    scheme: "claude",
    title: "Plan the database migration",
    user: "How can we migrate without dropping existing records?",
    assistant:
      "Add the new column first, backfill existing rows, then switch reads. Keep the old column until the next release.",
  },
  {
    provider: "OpenCode",
    scheme: "opencode",
    title: "Review the search index",
    user: "Can we skip indexing sessions that have not changed?",
    assistant:
      "Compare the source revision with the cached revision. Rebuild only changed records and remove entries for missing sources.",
  },
];

const labels = {
  en: {
    sample: "Interactive sample",
    search: "Search sample sessions",
    placeholder: "Try “auth” or “database”",
    empty: "No matching sessions. Try “auth”.",
    note: "Fictional sessions, simplified output. Runs in your browser.",
    copy: "Copy",
    copied: "Copied",
    guide: "Use this with your sessions",
    format: "Sample output format",
    sessions: "Sample sessions",
  },
  zh: {
    sample: "交互示例",
    search: "搜索示例会话",
    placeholder: "试试 auth 或 database",
    empty: "没有匹配的会话，试试 auth。",
    note: "虚构会话与简化输出，仅在浏览器内演示。",
    copy: "复制",
    copied: "已复制",
    guide: "用到自己的会话中",
    format: "示例输出格式",
    sessions: "示例会话",
  },
  ja: {
    sample: "操作できるサンプル",
    search: "サンプルを検索",
    placeholder: "auth や database を検索",
    empty: "一致する履歴がありません。auth をお試しください。",
    note: "架空の対話と簡略化した出力です。ブラウザー内で動作します。",
    copy: "コピー",
    copied: "コピーしました",
    guide: "自分の履歴で使う（英語）",
    format: "サンプルの出力形式",
    sessions: "サンプルの対話",
  },
};

export function SessionExplorer({ locale }: { locale: Locale }) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(samples[0]);
  const t = labels[locale];
  const matches = samples.filter((sample) =>
    `${sample.provider} ${sample.title} ${sample.user} ${sample.assistant}`
      .toLowerCase()
      .includes(query.toLowerCase().trim()),
  );
  const session = matches.includes(selected) ? selected : matches[0];
  const messages = session
    ? [
        { role: "user", text: session.user },
        { role: "assistant", text: session.assistant },
      ]
    : [];
  const markdown = session
    ? `# ${session.title}\n\n## User\n\n${session.user}\n\n## Assistant\n\n${session.assistant}`
    : "";
  const json = JSON.stringify({ title: session?.title, messages }, null, 2);

  return (
    <div className="session-explorer">
      <div className="explorer-top">
        <span>{t.sample}</span>
        <span>agent-dump</span>
      </div>
      <div className="explorer-workspace">
        <div className="explorer-sidebar">
          <label className="explorer-search">
            <MagnifyingGlassIcon size={18} aria-hidden="true" />
            <span className="sr-only">{t.search}</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t.placeholder}
            />
          </label>
          <div
            className="explorer-sessions"
            role="group"
            aria-label={t.sessions}
          >
            {matches.map((sample) => (
              <button
                type="button"
                key={sample.provider}
                aria-pressed={session === sample}
                onClick={() => setSelected(sample)}
              >
                <span>{sample.provider}</span>
                <strong>{sample.title}</strong>
              </button>
            ))}
          </div>
        </div>
        <div className="explorer-document">
          {session ? (
            <Tabs.Root defaultValue="markdown">
              <div className="explorer-toolbar">
                <Tabs.List aria-label={t.format} className="explorer-tabs">
                  <Tabs.Tab value="markdown">Markdown</Tabs.Tab>
                  <Tabs.Tab value="json">JSON</Tabs.Tab>
                </Tabs.List>
                <span className="explorer-file">{session.scheme}/session</span>
              </div>
              {[
                { format: "markdown", content: markdown },
                { format: "json", content: json },
              ].map(({ format, content }) => (
                <Tabs.Panel
                  key={format}
                  value={format}
                  className="explorer-output"
                >
                  <div className="explorer-copy">
                    <CopyButton
                      key={content}
                      text={content}
                      copyLabel={t.copy}
                      copiedLabel={t.copied}
                    />
                  </div>
                  <pre tabIndex={0}>
                    <code>{content}</code>
                  </pre>
                </Tabs.Panel>
              ))}
            </Tabs.Root>
          ) : (
            <p className="explorer-empty" role="status">
              {t.empty}
            </p>
          )}
        </div>
      </div>
      <div className="explorer-bottom">
        <p>{t.note}</p>
        <a
          href={`${locale === "zh" ? "/zh" : ""}/guides/search-ai-coding-history/`}
        >
          {t.guide}
          <ArrowUpRightIcon size={16} aria-hidden="true" />
        </a>
      </div>
    </div>
  );
}
