const translations = {
  en: {
    brandTag: "session export for AI coding tools",
    navSupport: "Support",
    navDetail: "Workflow",
    navSkillsInstall: "Skills",
    skipLink: "Skip to content",
    heroBrand: "Agent Dump",
    heroTitle: "Export AI coding sessions without touching the source flow.",
    heroDescription:
      "List, dump, export, and summarize Codex, Claude Code, Kimi, and OpenCode sessions from one CLI.",
    heroPrimary: "Start with install",
    heroSecondary: "See workflow",
    heroBadgeLabel: "Supported",
    heroBadgeValue: "4 agents",
    terminalLabel: "CLI workflow",
    stageCardOneLabel: "Quick read",
    stageCardOneTitle: "Open a session by URI before exporting anything.",
    stageCardOneBody:
      "Print the conversation text directly in your terminal when you only need the session itself.",
    stageCardTwoLabel: "Report path",
    stageCardTwoTitle: "Collect summaries, then write one final report.",
    stageSignalOne: "per-session summary progress",
    stageSignalTwo: "final AI report output",
    stageSignalThree: "stderr loading hints",
    featuresEyebrow: "Capability index",
    featuresTitle: "The CLI stays narrow, but the session coverage is wide.",
    featuresDescription:
      "Read, export, and summarize on the export side only, with the original session flow left untouched.",
    supportIndexOne: "01 read by URI",
    supportIndexTwo: "02 export by format",
    supportIndexThree: "03 collect by range",
    detailEyebrow: "Workflow",
    detailTitle: "Start light, then move into the commands that do real work.",
    installEyebrow: "Install paths",
    installTitle: "Choose the smallest entry point for the machine you are on.",
    usageEyebrow: "Working commands",
    usageTitle: "Keep the main workflow to three moves.",
    skillsEyebrow: "Install as a skill",
    skillsTitle: "Keep your agent on the supported command surface.",
    skillsDescription:
      "Install the skill when you want an agent to stay on the supported `agent-dump` command surface for listing, URI dump, collect, and config flows.",
    skillsCommandLabel: "Skill install",
    finalPrimary: "View GitHub",
    finalSecondary: "See commands",
    copy: "Copy",
    copied: "Copied",
  },
  zh: {
    brandTag: "面向 AI 编码工具的会话导出",
    navSupport: "能力",
    navDetail: "流程",
    navSkillsInstall: "Skills",
    skipLink: "跳到正文",
    heroBrand: "Agent Dump",
    heroTitle: "导出 AI 编码会话，不污染原始链路。",
    heroDescription:
      "一条 CLI 统一处理 Codex、Claude Code、Kimi 和 OpenCode 的列表、直读、导出与汇总。",
    heroPrimary: "先看安装",
    heroSecondary: "查看流程",
    heroBadgeLabel: "支持",
    heroBadgeValue: "4 个 agent",
    terminalLabel: "CLI 工作流",
    stageCardOneLabel: "先直读",
    stageCardOneTitle: "先用 URI 打开会话，再决定要不要导出。",
    stageCardOneBody: "如果你只想看正文，直接在终端打印会话内容，不必先落任何文件。",
    stageCardTwoLabel: "报告路径",
    stageCardTwoTitle: "先 collect 汇总，再生成最终报告。",
    stageSignalOne: "逐条 session summary 进度",
    stageSignalTwo: "最终 AI 报告输出",
    stageSignalThree: "stderr loading 提示",
    featuresEyebrow: "能力索引",
    featuresTitle: "CLI 的边界很窄，但会话覆盖面足够宽。",
    featuresDescription:
      "直读、导出、汇总都落在导出侧，原始 session 链路保持不动。",
    supportIndexOne: "01 通过 URI 直读",
    supportIndexTwo: "02 按格式导出",
    supportIndexThree: "03 按时间范围 collect",
    detailEyebrow: "工作流",
    detailTitle: "先用最轻入口跑通，再进入真正做事的命令面。",
    installEyebrow: "安装路径",
    installTitle: "按你当前机器的环境，选最小的一种入口。",
    usageEyebrow: "主流程命令",
    usageTitle: "把主工作流收在三步里。",
    skillsEyebrow: "作为 Skill 安装",
    skillsTitle: "让 agent 始终停在受支持的命令边界内。",
    skillsDescription:
      "当你希望 agent 只走 `agent-dump` 已支持的 list、URI dump、collect、config 等命令面时，直接安装这个 skill。",
    skillsCommandLabel: "Skill 安装",
    finalPrimary: "查看 GitHub",
    finalSecondary: "查看命令",
    copy: "复制",
    copied: "已复制",
  },
};

const content = {
  features: {
    en: [
      {
        kicker: "Scan roots",
        title: "One CLI surface for Codex, Claude Code, Kimi, and OpenCode",
        body:
          "Keep multiple session stores behind one command surface instead of building separate export flows per tool.",
      },
      {
        kicker: "Read first",
        title: "Use URI dump when you only need the conversation text",
        body:
          "Open `codex://`, `claude://`, `kimi://`, or `opencode://` directly in the terminal before deciding whether a file export is worth it.",
      },
      {
        kicker: "Export side only",
        title: "Write JSON, Markdown, raw data, or mixed output without mutating source sessions",
        body:
          "Session detail, tool calls, token stats, and summary paths stay on the export side where they belong.",
      },
    ],
    zh: [
      {
        kicker: "扫描根目录",
        title: "一条 CLI 统一覆盖 Codex、Claude Code、Kimi 和 OpenCode",
        body: "多个工具的 session 存储收口到同一条命令面里，不再为每个工具各起一套导出流程。",
      },
      {
        kicker: "先读正文",
        title: "只想看内容时，直接走 URI dump",
        body:
          "支持 `codex://`、`claude://`、`kimi://`、`opencode://`，先在终端直读，再决定是否值得导出文件。",
      },
      {
        kicker: "只落在导出侧",
        title: "JSON、Markdown、raw 和混合输出都不去改动原始 session",
        body: "消息详情、工具调用、token 统计和 summary 路径都保留在导出层，而不是回写源数据。",
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
        kicker: "Zero setup",
        title: "Run without installing globally",
        body: "Use this path for quick access or when you only want the wrapper command once.",
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
        body: "如果你希望机器上长期可用 `agent-dump` 命令，这条路径最直接。",
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
        body: "临时使用就走这一条；如果只想要一层 wrapper，也可以直接用它。",
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
        kicker: "Select",
        title: "Pick recent sessions from the terminal",
        body: "Default to the recent window, review the titles, then export only what you need.",
        code: "agent-dump --interactive",
      },
      {
        kicker: "Inspect",
        title: "Open a single session directly by URI",
        body: "Print first when you need context fast, or mix `print` with file formats in URI mode.",
        code: "agent-dump codex://<session-id>",
      },
      {
        kicker: "Summarize",
        title: "Collect summaries over a date range",
        body: "Generate per-session summaries first, then one final report that can be reviewed as a batch.",
        code: "agent-dump --collect -since 2026-03-01 -until 2026-03-05",
      },
    ],
    zh: [
      {
        kicker: "选择",
        title: "从终端里勾选最近会话",
        body: "先用最近时间窗快速过一遍标题，再只导出真正需要的会话。",
        code: "agent-dump --interactive",
      },
      {
        kicker: "检查",
        title: "给一个 URI，直接打开单条会话",
        body: "要快速补上下文时先 print；在 URI 模式下也可以混用 `print` 和文件格式。",
        code: "agent-dump codex://<session-id>",
      },
      {
        kicker: "汇总",
        title: "按日期范围 collect summary",
        body: "先产出逐条 session 的 summary，再合成一份可整体审阅的最终报告。",
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
const langButtons = Array.from(document.querySelectorAll("[data-lang-toggle]"));
const i18nNodes = Array.from(document.querySelectorAll("[data-i18n]"));
const featureGrid = document.querySelector("[data-feature-grid]");
const installGrid = document.querySelector("[data-install-grid]");
const usageGrid = document.querySelector("[data-usage-grid]");
const copyButtons = Array.from(document.querySelectorAll("[data-copy-target]"));
const commandPreview = document.querySelector("[data-command-preview]");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let currentLang = localStorage.getItem("agent-dump-lang") || "en";
let commandTimer = null;

function renderCards(target, items, cardClass, kickerClass) {
  target.textContent = "";
  items.forEach((item, index) => {
    const article = document.createElement("article");
    article.className = `${cardClass} reveal`;
    article.style.transitionDelay = `${index * 90}ms`;

    const kicker = document.createElement("p");
    kicker.className = kickerClass;
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
  block.className = "command-wrap";

  const commandShell = document.createElement("div");
  commandShell.className = "command-shell";

  const prompt = document.createElement("span");
  prompt.className = "command-prompt";
  prompt.setAttribute("aria-hidden", "true");
  prompt.textContent = "$";

  const pre = document.createElement("pre");
  pre.className = "command-code";
  pre.textContent = code;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy-button copy-button-icon";
  button.dataset.copyInline = code;
  button.dataset.copyTitle = "true";
  button.innerHTML =
    '<span class="button-icon-stack" aria-hidden="true"><span class="copy-icon"></span><span class="check-icon"></span></span><span class="sr-only"></span>';
  button.addEventListener("click", handleCopy);
  updateCopyButtonText(button);

  commandShell.append(prompt, pre);
  block.append(commandShell, button);
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
  document.title =
    lang === "zh" ? "Agent Dump | AI 编码会话导出工具" : "Agent Dump | Session Export for AI Coding Tools";
  i18nNodes.forEach((node) => {
    node.textContent = translations[lang][node.dataset.i18n];
  });
  langButtons.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.langToggle === lang));
  });
  renderCards(featureGrid, content.features[lang], "support-item", "support-kicker");
  renderCards(installGrid, content.install[lang], "detail-card", "detail-kicker");
  renderCards(usageGrid, content.usage[lang], "detail-card", "detail-kicker");
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

langButtons.forEach((button) => {
  button.addEventListener("click", () => {
    applyLanguage(button.dataset.langToggle);
  });
});

copyButtons.forEach((button) => button.addEventListener("click", handleCopy));

applyLanguage(currentLang);
