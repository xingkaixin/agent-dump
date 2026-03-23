const translations = {
  en: {
    brandTag: "session export for AI coding tools",
    navInstall: "Install",
    navCommands: "Commands",
    navSafety: "Safety",
    skipLink: "Skip to content",
    heroBrand: "Agent Dump",
    heroTitle: "Export AI coding sessions without touching the source flow.",
    heroDescription:
      "List, dump, export, and summarize Codex, Claude Code, Kimi, and OpenCode sessions from one CLI.",
    heroPrimary: "Install now",
    heroSecondary: "Install Skill",
    heroCardLabel: "Install",
    commandEyebrow: "Command demos",
    commandTitle: "Input exactly this, and see exactly this output shape.",
    commandDescription:
      "Focus on the three actions used most in daily work: select, inspect, and collect.",
    commandInput: "Input",
    commandOutput: "Output",
    safetyEyebrow: "Safety boundary",
    safetyTitle: "Read from source sessions, write only to export outputs.",
    safetyDescription:
      "Keep the source chain untouched while retaining full traceability in exports.",
    safetyNote:
      "This narrow, explicit command surface is why agents can run reliably without crossing into unsupported behavior.",
    skillNote: "Your agent learns install, inspect, export, and collect workflows.",
    copy: "Copy",
    copied: "Copied",
  },
  zh: {
    brandTag: "面向 AI 编码工具的会话导出",
    navInstall: "安装",
    navCommands: "命令",
    navSafety: "边界",
    skipLink: "跳到正文",
    heroBrand: "Agent Dump",
    heroTitle: "导出 AI 编码会话，不污染原始链路。",
    heroDescription:
      "一条 CLI 统一处理 Codex、Claude Code、Kimi 和 OpenCode 的列表、直读、导出与汇总。",
    heroPrimary: "立即安装",
    heroSecondary: "安装 Skill",
    heroCardLabel: "安装入口",
    commandEyebrow: "命令演示",
    commandTitle: "输入什么命令，就看到什么输出形态。",
    commandDescription: "聚焦最常用的三步：选择、检查、汇总。",
    commandInput: "输入",
    commandOutput: "输出",
    safetyEyebrow: "安全边界",
    safetyTitle: "读取源会话，写入只发生在导出侧。",
    safetyDescription: "原始链路保持不动，同时保留导出结果的可追踪性。",
    safetyNote: "命令面越清晰，agent 越容易稳定执行，而不会越界到不受支持行为。",
    skillNote: "让你的 agent 学会安装、检查、导出和汇总这套稳定工作流。",
    copy: "复制",
    copied: "已复制",
  },
};

const content = {
  features: {
    en: [
      {
        kicker: "Read only",
        title: "Never mutate source sessions while inspecting and exporting",
        body: "All reads happen on existing session stores; writes are isolated to your export output.",
      },
      {
        kicker: "Traceable",
        title: "Every command keeps an explicit input and output boundary",
        body:
          "URI inspect, format export, and collect summary all stay in a transparent command surface.",
      },
      {
        kicker: "Agent-safe",
        title: "A narrow command contract keeps automation stable",
        body: "Agents can follow supported commands reliably instead of guessing hidden workflows.",
      },
    ],
    zh: [
      {
        kicker: "只读源数据",
        title: "检查和导出都不改动原始 session",
        body: "读取发生在现有会话存储，写入仅发生在你的导出结果目录。",
      },
      {
        kicker: "可追踪",
        title: "每条命令都有明确输入和输出边界",
        body: "URI 检查、格式导出、collect 汇总都在透明的命令面内完成。",
      },
      {
        kicker: "对 agent 友好",
        title: "命令契约越窄，自动化执行越稳定",
        body: "agent 不需要猜测隐藏流程，只按受支持命令即可稳定运行。",
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
  commands: {
    en: [
      {
        kicker: "Select",
        title: "Pick recent sessions from the terminal",
        input: "agent-dump --interactive",
        output: [
          "Interactive checklist of recent sessions",
          "Pick one or multiple sessions",
          "Export files are written to output directory",
        ],
      },
      {
        kicker: "Inspect",
        title: "Open a single session directly by URI",
        input: "agent-dump codex://thread/session-id --format print,json",
        output: [
          "Conversation text prints to terminal",
          "JSON export is saved side-by-side",
          "No mutation on original source session",
        ],
      },
      {
        kicker: "Summarize",
        title: "Collect summaries over a date range",
        input: "agent-dump --collect -since 2026-03-01 -until 2026-03-05",
        output: [
          "Per-session summary progress in terminal",
          "One final merged report file",
          "stderr hints when loading or parsing",
        ],
      },
    ],
    zh: [
      {
        kicker: "选择",
        title: "从终端里勾选最近会话",
        input: "agent-dump --interactive",
        output: ["显示最近会话多选列表", "可一次勾选多条会话", "导出文件写入指定输出目录"],
      },
      {
        kicker: "检查",
        title: "给一个 URI，直接打开单条会话",
        input: "agent-dump codex://thread/session-id --format print,json",
        output: ["终端直接打印正文", "同时落地 JSON 导出文件", "原始 session 不会被改动"],
      },
      {
        kicker: "汇总",
        title: "按日期范围 collect summary",
        input: "agent-dump --collect -since 2026-03-01 -until 2026-03-05",
        output: ["终端显示逐条 summary 进度", "最终输出一份合并报告", "加载和解析过程会给出 stderr 提示"],
      },
    ],
  },
};

const root = document.documentElement;
const langButtons = Array.from(document.querySelectorAll("[data-lang-toggle]"));
const i18nNodes = Array.from(document.querySelectorAll("[data-i18n]"));
const featureGrid = document.querySelector("[data-feature-grid]");
const installGrid = document.querySelector("[data-install-grid]");
const commandGrid = document.querySelector("[data-command-grid]");
const copyButtons = Array.from(document.querySelectorAll("[data-copy-target]"));
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let currentLang = localStorage.getItem("agent-dump-lang") || "en";

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

function renderCommandDemos(target, items) {
  target.textContent = "";
  items.forEach((item, index) => {
    const article = document.createElement("article");
    article.className = "command-item reveal";
    article.style.transitionDelay = `${index * 90}ms`;

    const heading = document.createElement("div");
    heading.className = "command-item-heading";

    const kicker = document.createElement("p");
    kicker.className = "detail-kicker";
    kicker.textContent = item.kicker;

    const title = document.createElement("h3");
    title.textContent = item.title;
    heading.append(kicker, title);

    const io = document.createElement("div");
    io.className = "command-io";

    const inputBox = document.createElement("section");
    inputBox.className = "command-io-panel";
    const inputLabel = document.createElement("p");
    inputLabel.className = "command-io-label";
    inputLabel.textContent = translations[currentLang].commandInput;
    const inputCode = createCodeBlock(item.input);
    inputBox.append(inputLabel, inputCode);

    const outputBox = document.createElement("section");
    outputBox.className = "command-io-panel";
    const outputLabel = document.createElement("p");
    outputLabel.className = "command-io-label";
    outputLabel.textContent = translations[currentLang].commandOutput;
    const outputList = document.createElement("ul");
    outputList.className = "screen-list";
    item.output.forEach((line) => {
      const li = document.createElement("li");
      li.textContent = line;
      outputList.append(li);
    });
    outputBox.append(outputLabel, outputList);

    io.append(inputBox, outputBox);
    article.append(heading, io);
    target.append(article);
  });
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
  renderCommandDemos(commandGrid, content.commands[lang]);
  document.querySelectorAll(".copy-button").forEach(updateCopyButtonText);
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

langButtons.forEach((button) => {
  button.addEventListener("click", () => {
    applyLanguage(button.dataset.langToggle);
  });
});

copyButtons.forEach((button) => button.addEventListener("click", handleCopy));

applyLanguage(currentLang);
