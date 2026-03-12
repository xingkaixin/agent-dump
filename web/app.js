const translations = {
  en: {
    brandTag: "session export for AI coding tools",
    navInstall: "Install",
    navUsage: "Usage",
    navSkillsInstall: "Skills",
    themeLight: "Light",
    themeDark: "Dark",
    skipLink: "Skip to content",
    heroTitle: "Export AI coding sessions without touching the source flow.",
    heroDescription:
      "List, dump, export, and summarize Codex, Claude Code, Kimi, and OpenCode sessions from one CLI.",
    heroPrimary: "Install now",
    heroSecondary: "See examples",
    heroSkills: "Skills",
    supportedLabel: "Supported",
    terminalLabel: "live terminal flow",
    stageCardOneLabel: "URI dump",
    stageCardOneTitle: "Direct session text in your terminal",
    stageCardOneBody:
      "Run a session URI and read the full conversation flow without exporting a file first.",
    stageCardTwoLabel: "collect mode",
    stageCardTwoTitle: "Summary-first reports for time ranges",
    stageSignalOne: "per-session summary progress",
    stageSignalTwo: "final AI report output",
    stageSignalThree: "stderr loading hints",
    featuresEyebrow: "Why Agent Dump",
    featuresTitle: "Built for people who need the session, not a screenshot.",
    installEyebrow: "Installation matrix",
    installTitle: "Choose the lightest entry point for your workflow.",
    usageEyebrow: "Usage examples",
    usageTitle: "The commands that carry the main workflow.",
    skillsEyebrow: "Install as a skill",
    skillsTitle: "Keep the CLI close to your agent workflow.",
    skillsDescription:
      "Install the skill when you want an agent to stay on the supported `agent-dump` command surface for listing, URI dump, collect, and config flows.",
    skillsCommandLabel: "Skill install",
    copy: "Copy",
    copied: "Copied",
    footerCopy: "A terminal-first export surface for AI coding sessions.",
    footerInstall: "Installation",
    footerUsage: "Usage",
    footerSkills: "Skills",
  },
  zh: {
    brandTag: "面向 AI 编码工具的会话导出",
    navInstall: "安装",
    navUsage: "用法",
    navSkillsInstall: "Skills",
    themeLight: "亮色",
    themeDark: "暗色",
    skipLink: "跳到正文",
    heroTitle: "导出 AI 编码会话，不污染原始链路。",
    heroDescription:
      "一条 CLI 统一处理 Codex、Claude Code、Kimi 和 OpenCode 的列表、直读、导出与汇总。",
    heroPrimary: "立即安装",
    heroSecondary: "查看示例",
    heroSkills: "Skills",
    supportedLabel: "支持工具",
    terminalLabel: "终端实时流",
    stageCardOneLabel: "URI 直读",
    stageCardOneTitle: "不先导文件，也能直接在终端看完整会话",
    stageCardOneBody: "给一个 session URI，直接输出会话正文，适合先看再决定是否落盘。",
    stageCardTwoLabel: "collect 模式",
    stageCardTwoTitle: "按时间范围先总结 session，再生成最终报告",
    stageSignalOne: "逐条 session summary 进度",
    stageSignalTwo: "最终 AI 总结输出",
    stageSignalThree: "stderr loading 提示",
    featuresEyebrow: "为什么是 Agent Dump",
    featuresTitle: "你要的是会话本身，不是截图，也不是手工整理。",
    installEyebrow: "安装矩阵",
    installTitle: "按你的工作流，选最轻的一种入口。",
    usageEyebrow: "使用示例",
    usageTitle: "主流程里最常用的几条命令。",
    skillsEyebrow: "作为 Skill 安装",
    skillsTitle: "让 agent 始终站在受支持的 CLI 边界内工作。",
    skillsDescription:
      "当你希望 agent 只走 `agent-dump` 已支持的 list、URI dump、collect、config 等命令面时，直接安装这个 skill。",
    skillsCommandLabel: "Skill 安装",
    copy: "复制",
    copied: "已复制",
    footerCopy: "一个以终端为先的 AI 编码会话导出界面。",
    footerInstall: "安装",
    footerUsage: "用法",
    footerSkills: "Skill",
  },
};

const content = {
  features: {
    en: [
      {
        kicker: "Multi-agent scan",
        title: "One CLI for Codex, Claude Code, Kimi, and OpenCode",
        body:
          "Scan multiple session roots and keep the output surface aligned with the existing CLI modes instead of inventing a second workflow.",
      },
      {
        kicker: "URI first",
        title: "Open a session by URI when you only need the conversation text",
        body:
          "Use `opencode://`, `codex://`, `kimi://`, or `claude://` to print content directly in the terminal before deciding whether to export.",
      },
      {
        kicker: "Export shape",
        title: "Write JSON, Markdown, raw data, or mixed URI output without changing the source session",
        body:
          "The CLI supports multi-format export and keeps the session detail, tool calls, token stats, and summary path on the export side.",
      },
    ],
    zh: [
      {
        kicker: "多 agent 扫描",
        title: "一条 CLI，覆盖 Codex、Claude Code、Kimi 和 OpenCode",
        body:
          "统一扫描多个工具的会话根目录，把能力收口在现有 CLI 模式里，而不是另起一套工作流。",
      },
      {
        kicker: "URI 优先",
        title: "只想看正文时，直接用 URI 打开会话",
        body:
          "支持 `opencode://`、`codex://`、`kimi://`、`claude://`，先在终端里看内容，再决定要不要导出。",
      },
      {
        kicker: "导出边界",
        title: "JSON、Markdown、raw 与混合输出都只落在导出侧",
        body:
          "多格式导出保留消息详情、工具调用、token 统计和 summary 路径，不去改动原始 session 数据。",
      },
    ],
  },
  install: {
    en: [
      {
        kicker: "Recommended",
        title: "Install globally with your package manager",
        body:
          "Use the persistent path when you want `agent-dump` available as a normal command on the machine.",
        tabs: [
          { label: "uv", code: "uv tool install agent-dump" },
          { label: "npm", code: "npm install -g @agent-dump/cli" },
          { label: "pnpm", code: "pnpm add -g @agent-dump/cli" },
          { label: "bun", code: "bun add -g @agent-dump/cli" },
        ],
      },
      {
        kicker: "No install",
        title: "Run without installing globally",
        body:
          "Use the zero-setup path for quick access, or when you want the npm wrapper without a Python install path.",
        tabs: [
          { label: "uvx", code: "uvx agent-dump --help" },
          { label: "bunx", code: "bunx @agent-dump/cli --help" },
          { label: "npx", code: "npx @agent-dump/cli --help" },
        ],
      },
    ],
    zh: [
      {
        kicker: "推荐",
        title: "用包管理器全局安装",
        body: "如果你希望机器上直接长期可用 `agent-dump` 命令，这条路径最直接。",
        tabs: [
          { label: "uv", code: "uv tool install agent-dump" },
          { label: "npm", code: "npm install -g @agent-dump/cli" },
          { label: "pnpm", code: "pnpm add -g @agent-dump/cli" },
          { label: "bun", code: "bun add -g @agent-dump/cli" },
        ],
      },
      {
        kicker: "免安装",
        title: "不全局安装，直接运行",
        body: "临时使用就走这一条；如果不想碰 Python 安装，也可以直接走 npm wrapper。",
        tabs: [
          { label: "uvx", code: "uvx agent-dump --help" },
          { label: "bunx", code: "bunx @agent-dump/cli --help" },
          { label: "npx", code: "npx @agent-dump/cli --help" },
        ],
      },
    ],
  },
  usage: {
    en: [
      {
        kicker: "Interactive export",
        title: "Select sessions from the recent window",
        body: "Grouped terminal selection with the default 7-day window and explicit export confirmation.",
        code: "agent-dump --interactive",
      },
      {
        kicker: "URI dump",
        title: "Print a session directly from its URI",
        body: "Open session text on demand, or mix `print` with file export formats in URI mode.",
        code: "agent-dump codex://<session-id>",
      },
      {
        kicker: "Collect and config",
        title: "Summarize a date range and inspect local config",
        body:
          "Collect first writes per-session summaries, then generates one final report. Config flows stay on the CLI surface.",
        code: "agent-dump --collect -since 2026-03-01 -until 2026-03-05",
      },
    ],
    zh: [
      {
        kicker: "交互导出",
        title: "从最近时间窗里勾选会话再导出",
        body: "终端分组选择，默认 7 天窗口，确认后显式导出。",
        code: "agent-dump --interactive",
      },
      {
        kicker: "URI 直读",
        title: "给一个 URI，直接打印指定会话",
        body: "需要时直接看正文；在 URI 模式下也可以混用 `print` 和文件导出格式。",
        code: "agent-dump codex://<session-id>",
      },
      {
        kicker: "Collect 与配置",
        title: "按日期范围汇总，再查看本地配置",
        body: "collect 会先逐条生成 session summary，再产出一份最终报告；配置也保持在 CLI 边界内。",
        code: "agent-dump --collect -since 2026-03-01 -until 2026-03-05",
      },
    ],
  },
};

const commandPreviews = {
  en: [
    "agent-dump --interactive",
    "agent-dump codex://thread/session-id --format print,json",
    "agent-dump --collect -since 20260301 -until 20260305",
    "npx skills add xingkaixin/agent-dump",
  ],
  zh: [
    "agent-dump --interactive",
    "agent-dump codex://thread/session-id --format print,json",
    "agent-dump --collect -since 20260301 -until 20260305",
    "npx skills add xingkaixin/agent-dump",
  ],
};

const root = document.documentElement;
const themeButtons = Array.from(document.querySelectorAll("[data-theme-toggle]"));
const langButtons = Array.from(document.querySelectorAll("[data-lang-toggle]"));
const i18nNodes = Array.from(document.querySelectorAll("[data-i18n]"));
const featureGrid = document.querySelector("[data-feature-grid]");
const installGrid = document.querySelector("[data-install-grid]");
const usageGrid = document.querySelector("[data-usage-grid]");
const copyButtons = Array.from(document.querySelectorAll("[data-copy-target]"));
const commandPreview = document.querySelector("[data-command-preview]");

const media = window.matchMedia("(prefers-color-scheme: dark)");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let currentLang = localStorage.getItem("agent-dump-lang") || "en";
let currentTheme = localStorage.getItem("agent-dump-theme") || "system";
let commandTimer = null;

function applyTheme(theme) {
  const effectiveTheme = theme === "system" ? (media.matches ? "dark" : "light") : theme;
  root.dataset.theme = effectiveTheme;
  document
    .querySelector('meta[name="theme-color"]')
    .setAttribute("content", effectiveTheme === "dark" ? "#111615" : "#f4f1ea");
  themeButtons.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.themeToggle === effectiveTheme));
  });
}

function setTheme(theme, persist = true) {
  currentTheme = theme;
  applyTheme(theme);
  if (persist) {
    localStorage.setItem("agent-dump-theme", theme);
  }
}

function renderCards(target, items, cardClass) {
  target.textContent = "";
  items.forEach((item, index) => {
    const article = document.createElement("article");
    article.className = `${cardClass} reveal`;
    article.style.transitionDelay = `${index * 90}ms`;

    const kicker = document.createElement("p");
    kicker.className = cardClass.replace("-card", "-kicker").replace("-item", "-kicker");
    kicker.textContent = item.kicker;

    const title = document.createElement("h3");
    title.textContent = item.title;

    const body = document.createElement("p");
    body.textContent = item.body;

    article.append(kicker, title, body);

    if (item.code) {
      article.append(createCodeBlock(item.code));
    }

    if (item.tabs) {
      article.append(createTabbedCodeBlock(item.tabs));
    }

    target.append(article);
  });
}

function createCodeBlock(code) {
  const block = document.createElement("div");
  block.className = "code-block";

  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy-button copy-button-icon";
  button.dataset.copyInline = code;
  button.dataset.copyTitle = "true";
  button.innerHTML =
    '<span class="button-icon-stack" aria-hidden="true"><span class="copy-icon"></span><span class="check-icon"></span></span><span class="sr-only"></span>';
  button.addEventListener("click", handleCopy);
  updateCopyButtonText(button);

  const commandShell = document.createElement("div");
  commandShell.className = "command-shell";

  const prompt = document.createElement("span");
  prompt.className = "command-prompt";
  prompt.setAttribute("aria-hidden", "true");
  prompt.textContent = "$";

  const pre = document.createElement("pre");
  pre.className = "command-code";
  pre.textContent = code;

  commandShell.append(prompt, pre);
  block.append(button, commandShell);
  return block;
}

function createTabbedCodeBlock(tabs) {
  const shell = document.createElement("div");
  shell.className = "tab-shell";

  const tabList = document.createElement("div");
  tabList.className = "tab-list";
  tabList.setAttribute("role", "tablist");

  const panelWrap = document.createElement("div");
  const tabButtons = [];
  const panels = [];

  tabs.forEach((tab, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tab-button";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(index === 0));
    button.textContent = tab.label;

    const panel = createCodeBlock(tab.code);
    panel.classList.add("tab-panel");
    panel.hidden = index !== 0;

    button.addEventListener("click", () => {
      tabButtons.forEach((item, buttonIndex) => {
        item.setAttribute("aria-selected", String(buttonIndex === index));
      });
      panels.forEach((item, panelIndex) => {
        item.hidden = panelIndex !== index;
      });
    });

    tabButtons.push(button);
    panels.push(panel);
    tabList.append(button);
    panelWrap.append(panel);
  });

  shell.append(tabList, panelWrap);
  return shell;
}

function applyLanguage(lang) {
  currentLang = lang;
  root.lang = lang === "zh" ? "zh-CN" : "en";
  document.title = lang === "zh" ? "Agent Dump | AI 编码会话导出工具" : "Agent Dump | Session Export for AI Coding Tools";
  i18nNodes.forEach((node) => {
    node.textContent = translations[lang][node.dataset.i18n];
  });
  langButtons.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.langToggle === lang));
  });
  renderCards(featureGrid, content.features[lang], "feature-item");
  renderCards(installGrid, content.install[lang], "install-card");
  renderCards(usageGrid, content.usage[lang], "usage-card");
  document.querySelectorAll(".copy-button").forEach(updateCopyButtonText);
  startCommandPreview();
  localStorage.setItem("agent-dump-lang", lang);
  observeReveals();
}

function updateCopyButtonText(button) {
  const label = button.querySelector(".sr-only");
  if (label) {
    label.textContent = translations[currentLang].copy;
  }
  if ("copyTitle" in button.dataset) {
    button.setAttribute("aria-label", translations[currentLang].copy);
    button.setAttribute("title", translations[currentLang].copy);
  }
}

async function handleCopy(event) {
  const button = event.currentTarget;
  const targetId = button.dataset.copyTarget;
  const text = targetId
    ? document.getElementById(targetId)?.textContent?.trim() || ""
    : button.dataset.copyInline || "";

  try {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      fallbackCopyText(text);
    }
    const label = button.querySelector(".sr-only");
    button.dataset.copied = "true";
    button.setAttribute("aria-label", translations[currentLang].copied);
    button.setAttribute("title", translations[currentLang].copied);
    if (label) {
      label.textContent = translations[currentLang].copied;
    }
    window.setTimeout(() => {
      button.dataset.copied = "false";
      updateCopyButtonText(button);
    }, 2000);
  } catch {
    button.dataset.copied = "false";
    updateCopyButtonText(button);
  }
}

function fallbackCopyText(text) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "absolute";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.append(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function observeReveals() {
  const revealNodes = document.querySelectorAll(".reveal");
  if (reducedMotion || !("IntersectionObserver" in window)) {
    revealNodes.forEach((node) => node.classList.add("is-visible"));
    return;
  }

  const observer = new IntersectionObserver(
    (entries, instance) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          instance.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.16 }
  );

  revealNodes.forEach((node) => {
    if (!node.classList.contains("is-visible")) {
      observer.observe(node);
    }
  });
}

function startCommandPreview() {
  if (!commandPreview) {
    return;
  }

  if (commandTimer) {
    window.clearInterval(commandTimer);
  }

  const previews = commandPreviews[currentLang];
  let index = 0;
  commandPreview.textContent = previews[index];

  if (reducedMotion) {
    return;
  }

  commandTimer = window.setInterval(() => {
    index = (index + 1) % previews.length;
    commandPreview.textContent = previews[index];
  }, 2400);
}

themeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setTheme(button.dataset.themeToggle);
  });
});

langButtons.forEach((button) => {
  button.addEventListener("click", () => {
    applyLanguage(button.dataset.langToggle);
  });
});

copyButtons.forEach((button) => button.addEventListener("click", handleCopy));
if (typeof media.addEventListener === "function") {
  media.addEventListener("change", () => {
    if (currentTheme === "system") {
      applyTheme("system");
    }
  });
} else if (typeof media.addListener === "function") {
  media.addListener(() => {
    if (currentTheme === "system") {
      applyTheme("system");
    }
  });
}

setTheme(currentTheme, false);
applyLanguage(currentLang);
