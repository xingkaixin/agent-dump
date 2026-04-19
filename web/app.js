const translations = {
  en: {
    skipLink: "Skip to content",
    eyebrow: "CLI · AI Session Export",
    heroTitle: "Export AI coding sessions.",
    heroDescription:
      "List, dump, export, summarize, and search sessions from Codex, Claude Code, Kimi, OpenCode, and Cursor.",
    versionLabel: "Version",
    installHeading: "Install",
    installGlobalLabel: "Install globally",
    installRunLabel: "Run without installing",
    skillNote: "Or add as an agent skill:",
    footerGithub: "GitHub",
    copy: "Copy",
    copied: "Copied",
  },
  zh: {
    skipLink: "跳到正文",
    eyebrow: "CLI · AI 会话导出",
    heroTitle: "导出 AI 编码会话。",
    heroDescription:
      "一条 CLI 统一处理 Codex、Claude Code、Kimi、OpenCode 和 Cursor 的列表、直读、导出、汇总、搜索与统计。",
    versionLabel: "当前版本",
    installHeading: "安装",
    installGlobalLabel: "全局安装",
    installRunLabel: "免安装运行",
    skillNote: "或作为 agent skill 添加：",
    footerGithub: "GitHub",
    copy: "复制",
    copied: "已复制",
  },
};

const content = {
  install: {
    en: [
      {
        label: "Install globally",
        labelKey: "installGlobalLabel",
        tabs: [
          { label: "uv", code: "uv tool install agent-dump" },
          { label: "npm", code: "npm install -g @agent-dump/cli" },
          { label: "pnpm", code: "pnpm add -g @agent-dump/cli" },
          { label: "bun", code: "bun add -g @agent-dump/cli" },
        ],
      },
      {
        label: "Run without installing",
        labelKey: "installRunLabel",
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
        labelKey: "installGlobalLabel",
        tabs: [
          { label: "uv", code: "uv tool install agent-dump" },
          { label: "npm", code: "npm install -g @agent-dump/cli" },
          { label: "pnpm", code: "pnpm add -g @agent-dump/cli" },
          { label: "bun", code: "bun add -g @agent-dump/cli" },
        ],
      },
      {
        label: "免安装运行",
        labelKey: "installRunLabel",
        tabs: [
          { label: "uvx", code: "uvx agent-dump --help" },
          { label: "npx", code: "npx @agent-dump/cli --help" },
          { label: "bunx", code: "bunx @agent-dump/cli --help" },
        ],
      },
    ],
  },
};

const TYPING_COMMANDS = [
  "agent-dump --interactive",
  "agent-dump codex://threads/abc123 --format json",
  "agent-dump --search \"auth timeout\"",
  "agent-dump --stats -days 30",
  "agent-dump --collect --since 2026-03-01",
];

const TYPING_SPEED = 55;
const DELETE_SPEED = 28;
const PAUSE_AFTER_TYPE = 2200;
const PAUSE_AFTER_DELETE = 400;
const webData = window.AGENT_DUMP_WEB_DATA ?? {
  version: "0.0.0",
  changelogUrl: {
    en: "https://github.com/xingkaixin/agent-dump/blob/main/CHANGELOG.md",
    zh: "https://github.com/xingkaixin/agent-dump/blob/main/docs/zh/CHANGELOG.md",
  },
};

class TypeWriter {
  constructor(element) {
    this.element = element;
    this.commands = TYPING_COMMANDS;
    this.index = 0;
    this.charIndex = 0;
    this.isDeleting = false;
    this.timeoutId = null;
  }

  start() {
    this.tick();
  }

  stop() {
    clearTimeout(this.timeoutId);
  }

  reset() {
    this.stop();
    this.index = 0;
    this.charIndex = 0;
    this.isDeleting = false;
    this.element.textContent = "";
    this.timeoutId = setTimeout(() => this.tick(), 300);
  }

  tick() {
    const current = this.commands[this.index];

    if (!this.isDeleting) {
      this.charIndex++;
      this.element.textContent = current.slice(0, this.charIndex);

      if (this.charIndex >= current.length) {
        this.isDeleting = true;
        this.timeoutId = setTimeout(() => this.tick(), PAUSE_AFTER_TYPE);
        return;
      }
      this.timeoutId = setTimeout(() => this.tick(), TYPING_SPEED);
    } else {
      this.charIndex--;
      this.element.textContent = current.slice(0, this.charIndex);

      if (this.charIndex <= 0) {
        this.isDeleting = false;
        this.index = (this.index + 1) % this.commands.length;
        this.timeoutId = setTimeout(() => this.tick(), PAUSE_AFTER_DELETE);
        return;
      }
      this.timeoutId = setTimeout(() => this.tick(), DELETE_SPEED);
    }
  }
}

// DOM refs
const langButtons = Array.from(document.querySelectorAll("[data-lang-toggle]"));
const i18nNodes = Array.from(document.querySelectorAll("[data-i18n]"));
const installGrid = document.querySelector("[data-install-grid]");
const copyButtons = Array.from(document.querySelectorAll("[data-copy-target]"));
const typedText = document.getElementById("typed-text");
const releaseVersion = document.getElementById("release-version");
const releaseLink = document.getElementById("release-link");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let currentLang = localStorage.getItem("agent-dump-lang") || "en";
let typeWriter = null;

function getChangelogUrl(lang) {
  return webData.changelogUrl[lang] ?? webData.changelogUrl.en;
}

function renderInstall(lang) {
  installGrid.textContent = "";
  content.install[lang].forEach((group) => {
    const div = document.createElement("div");
    div.className = "install-group";

    const label = document.createElement("p");
    label.className = "install-group-label";
    label.textContent = translations[lang][group.labelKey];

    div.append(label, createTabbedCodeBlock(group.tabs));
    installGrid.append(div);
  });
}

function createTabbedCodeBlock(tabs) {
  const shell = document.createElement("div");

  const tabList = document.createElement("div");
  tabList.className = "tab-list";
  tabList.setAttribute("role", "tablist");

  const panels = [];
  const tabButtons = [];

  tabs.forEach((tab, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tab-button";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(index === 0));
    button.textContent = tab.label;

    const panel = document.createElement("div");
    panel.classList.add("tab-panel");
    panel.hidden = index !== 0;
    panel.append(createCommandLine(tab.code));

    button.addEventListener("click", () => {
      tabButtons.forEach((b, i) => b.setAttribute("aria-selected", String(i === index)));
      panels.forEach((p, i) => { p.hidden = i !== index; });
    });

    tabButtons.push(button);
    panels.push(panel);
    tabList.append(button);
  });

  shell.append(tabList);
  panels.forEach((p) => shell.append(p));
  return shell;
}

function createCommandLine(code) {
  const line = document.createElement("div");
  line.className = "command-line";

  const prompt = document.createElement("span");
  prompt.className = "prompt";
  prompt.setAttribute("aria-hidden", "true");
  prompt.textContent = "$";

  const pre = document.createElement("pre");
  pre.className = "command-code";
  pre.textContent = code;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy-button";
  button.dataset.copyInline = code;
  button.setAttribute("aria-label", translations[currentLang].copy);
  button.innerHTML =
    '<span class="button-icon-stack" aria-hidden="true"><span class="copy-icon"></span><span class="check-icon"></span></span>';
  button.addEventListener("click", handleCopy);

  line.append(prompt, pre, button);
  return line;
}

function applyLanguage(lang) {
  currentLang = lang;
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  document.title =
    lang === "zh"
      ? "Agent Dump | AI 编码会话导出工具"
      : "Agent Dump | Session Export for AI Coding Tools";

  i18nNodes.forEach((node) => {
    const key = node.dataset.i18n;
    if (translations[lang][key] !== undefined) {
      node.textContent = translations[lang][key];
    }
  });

  langButtons.forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.langToggle === lang));
  });

  renderInstall(lang);

  if (releaseVersion) {
    releaseVersion.textContent = `v${webData.version}`;
  }

  if (releaseLink) {
    releaseLink.href = getChangelogUrl(lang);
  }

  document.querySelectorAll(".copy-button").forEach((btn) => {
    btn.setAttribute("aria-label", translations[lang].copy);
    btn.setAttribute("title", translations[lang].copy);
  });

  localStorage.setItem("agent-dump-lang", lang);
}

async function handleCopy(event) {
  const button = event.currentTarget;
  const targetId = button.dataset.copyTarget;
  const text = targetId
    ? document.getElementById(targetId)?.textContent?.trim() ?? ""
    : button.dataset.copyInline ?? "";

  try {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      fallbackCopyText(text);
    }
    button.dataset.copied = "true";
    button.setAttribute("aria-label", translations[currentLang].copied);
    button.setAttribute("title", translations[currentLang].copied);
    window.setTimeout(() => {
      button.dataset.copied = "false";
      button.setAttribute("aria-label", translations[currentLang].copy);
      button.setAttribute("title", translations[currentLang].copy);
    }, 2000);
  } catch {
    button.dataset.copied = "false";
  }
}

function fallbackCopyText(text) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.cssText = "position:absolute;opacity:0;pointer-events:none";
  document.body.append(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

// Init
langButtons.forEach((btn) => {
  btn.addEventListener("click", () => applyLanguage(btn.dataset.langToggle));
});

if (releaseLink) {
  releaseLink.addEventListener("click", () => {
    releaseLink.href = getChangelogUrl(currentLang);
  });
}

copyButtons.forEach((btn) => btn.addEventListener("click", handleCopy));

applyLanguage(currentLang);

// Start typing animation
if (typedText) {
  if (reducedMotion) {
    typedText.textContent = TYPING_COMMANDS[0];
  } else {
    typeWriter = new TypeWriter(typedText);
    typeWriter.start();
  }
}
