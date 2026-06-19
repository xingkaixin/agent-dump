import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { LOCALES, site, locales, TYPING_COMMANDS } from "./i18n.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const versionFile = path.resolve(repoRoot, "src", "agent_dump", "__about__.py");

function esc(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function readVersion() {
  const source = await readFile(versionFile, "utf8");
  const match = source.match(/__version__\s*=\s*"([^"]+)"/);
  if (!match) throw new Error("Could not read version from src/agent_dump/__about__.py");
  return match[1];
}

function url(pathname) {
  return `${site.origin}${pathname}`;
}

function renderInstall(groups, copyLabel) {
  return groups
    .map((group) => {
      const tabs = group.tabs
        .map((tab, i) => {
          const selected = i === 0 ? "true" : "false";
          return `            <button type="button" class="tab-button" role="tab" aria-selected="${selected}">${esc(tab.label)}</button>`;
        })
        .join("\n");
      const panels = group.tabs
        .map((tab, i) => {
          const hidden = i === 0 ? "" : " hidden";
          return `          <div class="tab-panel"${hidden}>
            <div class="command-line">
              <span class="prompt" aria-hidden="true">$</span>
              <pre class="command-code">${esc(tab.code)}</pre>
              <button type="button" class="copy-button" data-copy-inline="${esc(tab.code)}" aria-label="${esc(copyLabel)}" title="${esc(copyLabel)}">
                <span class="button-icon-stack" aria-hidden="true"><span class="copy-icon"></span><span class="check-icon"></span></span>
              </button>
            </div>
          </div>`;
        })
        .join("\n");
      return `        <div class="install-group">
          <p class="install-group-label">${esc(group.label)}</p>
          <div>
            <div class="tab-list" role="tablist">
${tabs}
            </div>
${panels}
          </div>
        </div>`;
    })
    .join("\n");
}

function renderHreflang() {
  const links = LOCALES.map(
    (loc) =>
      `    <link rel="alternate" hreflang="${locales[loc].htmlLang}" href="${url(site.paths[loc])}" />`,
  );
  links.push(`    <link rel="alternate" hreflang="x-default" href="${url(site.paths.en)}" />`);
  return links.join("\n");
}

function renderLangSwitch(activeLang) {
  return LOCALES.map((loc) => {
    const label = loc === "en" ? "EN" : "中文";
    const current = loc === activeLang;
    const aria = current ? ' aria-current="page"' : "";
    return `        <a class="segmented-button" href="${site.paths[loc]}" data-lang="${loc}" aria-pressed="${current}"${aria}>${label}</a>`;
  }).join("\n");
}

function renderJsonLd(lang, version) {
  const t = locales[lang];
  const base = url(site.paths[lang]);
  const graph = [
    {
      "@type": "Person",
      "@id": `${site.origin}/#author`,
      name: site.author.name,
      url: site.author.url,
      sameAs: [site.author.url],
    },
    {
      "@type": "WebSite",
      "@id": `${base}#website`,
      name: "Agent Dump",
      url: base,
      inLanguage: t.htmlLang,
      description: t.websiteDescription,
      publisher: { "@id": `${site.origin}/#author` },
    },
    {
      "@type": "SoftwareApplication",
      "@id": `${site.origin}/#software`,
      name: "Agent Dump",
      applicationCategory: "DeveloperApplication",
      applicationSubCategory: "Command-line developer tool",
      operatingSystem: "macOS, Linux, Windows",
      description: t.softwareDescription,
      inLanguage: t.htmlLang,
      url: base,
      downloadUrl: site.downloadUrls,
      softwareVersion: version,
      offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
      author: { "@id": `${site.origin}/#author` },
      codeRepository: site.repo,
      license: site.license,
    },
    {
      "@type": "FAQPage",
      "@id": `${base}#faq`,
      inLanguage: t.htmlLang,
      mainEntity: t.faq.map((item) => ({
        "@type": "Question",
        name: item.question,
        acceptedAnswer: { "@type": "Answer", text: item.answer },
      })),
    },
  ];
  return JSON.stringify({ "@context": "https://schema.org", "@graph": graph }, null, 2);
}

function renderPage(lang, version) {
  const t = locales[lang];
  const ui = t.ui;
  const canonical = url(site.paths[lang]);
  const ogImage = url(site.ogImage.path);
  const capabilities = ui.capabilities
    .map((item) => `          <li>${esc(item)}</li>`)
    .join("\n");
  const faq = t.faq
    .map(
      (item) => `          <article>
            <h3>${esc(item.question)}</h3>
            <p>${esc(item.answer)}</p>
          </article>`,
    )
    .join("\n");
  const commandsAttr = esc(JSON.stringify(TYPING_COMMANDS));

  return `<!DOCTYPE html>
<html lang="${t.htmlLang}">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="theme-color" content="#fdfcfc" />
    <meta name="description" content="${esc(t.description)}" />
    <meta name="keywords" content="${esc(t.keywords)}" />
    <meta name="author" content="${esc(site.author.name)}" />
    <meta name="robots" content="index, follow" />
    <title>${esc(t.title)}</title>
    <link rel="canonical" href="${canonical}" />
${renderHreflang()}
    <link rel="icon" type="image/png" href="${site.logo}" />
    <link rel="apple-touch-icon" href="${site.logo}" />

    <!-- Open Graph -->
    <meta property="og:type" content="website" />
    <meta property="og:url" content="${canonical}" />
    <meta property="og:site_name" content="Agent Dump" />
    <meta property="og:title" content="${esc(t.title)}" />
    <meta property="og:description" content="${esc(t.description)}" />
    <meta property="og:image" content="${ogImage}" />
    <meta property="og:image:width" content="${site.ogImage.width}" />
    <meta property="og:image:height" content="${site.ogImage.height}" />
    <meta property="og:image:alt" content="${esc(t.ogImageAlt)}" />
    <meta property="og:locale" content="${t.ogLocale}" />

    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="${esc(t.title)}" />
    <meta name="twitter:description" content="${esc(t.description)}" />
    <meta name="twitter:image" content="${ogImage}" />
    <meta name="twitter:image:alt" content="${esc(t.ogImageAlt)}" />

    <!-- JSON-LD Structured Data -->
    <script type="application/ld+json">
${renderJsonLd(lang, version)}
    </script>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&display=swap"
      rel="stylesheet"
    />
    <link rel="stylesheet" href="/styles.css" />
    <script
      defer
      src="https://static.cloudflareinsights.com/beacon.min.js"
      data-cf-beacon='{"token": "004af8c09ea3455ea8a2b53f0a913be2"}'
    ></script>
    <script src="/app.js" defer></script>
  </head>
  <body data-copy="${esc(ui.copy)}" data-copied="${esc(ui.copied)}">
    <a class="skip-link" href="#main">${esc(ui.skipLink)}</a>

    <header class="topbar">
      <a class="brand" href="${site.paths[lang]}" aria-label="Agent Dump home">
        <img src="${site.logo}" alt="" width="32" height="32" />
        <strong>Agent Dump</strong>
      </a>

      <div class="segmented-control" role="group" aria-label="${esc(ui.langLabel)}">
${renderLangSwitch(lang)}
      </div>
    </header>

    <main id="main">
      <section id="hero" class="hero">
        <p class="eyebrow">${esc(ui.eyebrow)}</p>
        <h1>${esc(ui.heroTitle)}</h1>
        <p class="description">${esc(ui.heroDescription)}</p>
        <p class="answer-summary">${esc(ui.answerSummary)}</p>
        <p class="release-meta">
          <span>${esc(ui.versionLabel)}</span>
          <a
            class="release-link"
            href="${site.changelogUrl[lang]}"
            target="_blank"
            rel="noopener noreferrer"
          >
            <span>v${esc(version)}</span>
          </a>
        </p>

        <div class="terminal" aria-label="Terminal showing example agent-dump commands">
          <div class="terminal-bar" aria-hidden="true">
            <span class="terminal-dot"></span>
            <span class="terminal-dot"></span>
            <span class="terminal-dot"></span>
          </div>
          <div class="terminal-body">
            <div class="terminal-line">
              <span class="prompt" aria-hidden="true">$</span>
              <span id="typed-text" class="typed-text" aria-live="off" data-commands="${commandsAttr}"></span><span class="cursor" aria-hidden="true"></span>
            </div>
          </div>
        </div>
      </section>

      <section id="install" class="install-section">
        <h2>${esc(ui.installHeading)}</h2>
        <div class="install-groups">
${renderInstall(t.install, ui.copy)}
        </div>
        <div class="skill-block">
          <p class="skill-label">${esc(ui.skillNote)}</p>
          <div class="command-line">
            <span class="prompt" aria-hidden="true">$</span>
            <pre id="skill-install" class="command-code">npx skills add xingkaixin/agent-dump</pre>
            <button
              type="button"
              class="copy-button"
              data-copy-target="skill-install"
              aria-label="${esc(ui.copy)}"
              title="${esc(ui.copy)}"
            >
              <span class="button-icon-stack" aria-hidden="true">
                <span class="copy-icon"></span>
                <span class="check-icon"></span>
              </span>
            </button>
          </div>
        </div>
      </section>

      <section id="capabilities" class="content-section">
        <h2>${esc(ui.capabilitiesHeading)}</h2>
        <ul class="feature-list" aria-label="${esc(ui.capabilitiesAria)}">
${capabilities}
        </ul>
      </section>

      <section id="faq" class="content-section">
        <h2>${esc(ui.faqHeading)}</h2>
        <div class="faq-list">
${faq}
        </div>
      </section>
    </main>

    <footer class="footer">
      <span>Agent Dump</span>
      <a href="${site.repo}" target="_blank" rel="noopener noreferrer">${esc(ui.footerGithub)}</a>
    </footer>
  </body>
</html>
`;
}

function renderSitemap() {
  const today = new Date().toISOString().slice(0, 10);
  const entries = LOCALES.map((lang) => {
    const alternates = LOCALES.map(
      (loc) =>
        `    <xhtml:link rel="alternate" hreflang="${locales[loc].htmlLang}" href="${url(site.paths[loc])}" />`,
    );
    alternates.push(
      `    <xhtml:link rel="alternate" hreflang="x-default" href="${url(site.paths.en)}" />`,
    );
    return `  <url>
    <loc>${url(site.paths[lang])}</loc>
${alternates.join("\n")}
    <lastmod>${today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>${lang === "en" ? "1.0" : "0.8"}</priority>
  </url>`;
  });
  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
${entries.join("\n")}
</urlset>
`;
}

export { readVersion };

// Maps repo-relative output paths to their rendered content.
export function buildFiles(version) {
  return new Map([
    ["web/index.html", renderPage("en", version)],
    ["web/zh/index.html", renderPage("zh", version)],
    ["web/sitemap.xml", renderSitemap()],
  ]);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const version = await readVersion();
  for (const [relPath, content] of buildFiles(version)) {
    const target = path.resolve(repoRoot, relPath);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, content, "utf8");
  }
  console.log(`Built web/index.html, web/zh/index.html, web/sitemap.xml for v${version}`);
}
