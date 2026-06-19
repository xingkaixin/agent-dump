// Behavior layer only. All text and version content is pre-rendered at build time
// (see build-site.mjs + i18n.mjs); this script only drives interactions.

const TYPING_SPEED = 55;
const DELETE_SPEED = 28;
const PAUSE_AFTER_TYPE = 2200;
const PAUSE_AFTER_DELETE = 400;

const copyLabel = document.body.dataset.copy ?? "Copy";
const copiedLabel = document.body.dataset.copied ?? "Copied";

class TypeWriter {
  constructor(element, commands) {
    this.element = element;
    this.commands = commands;
    this.index = 0;
    this.charIndex = 0;
    this.isDeleting = false;
    this.timeoutId = null;
  }

  start() {
    this.tick();
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

function setupTabs() {
  document.querySelectorAll(".tab-list").forEach((tabList) => {
    const shell = tabList.parentElement;
    const buttons = Array.from(tabList.querySelectorAll(".tab-button"));
    const panels = Array.from(shell.querySelectorAll(".tab-panel"));
    buttons.forEach((button, index) => {
      button.addEventListener("click", () => {
        buttons.forEach((b, i) => b.setAttribute("aria-selected", String(i === index)));
        panels.forEach((p, i) => { p.hidden = i !== index; });
      });
    });
  });
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
    button.setAttribute("aria-label", copiedLabel);
    button.setAttribute("title", copiedLabel);
    window.setTimeout(() => {
      button.dataset.copied = "false";
      button.setAttribute("aria-label", copyLabel);
      button.setAttribute("title", copyLabel);
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

setupTabs();
document.querySelectorAll(".copy-button").forEach((btn) => btn.addEventListener("click", handleCopy));

const typedText = document.getElementById("typed-text");
if (typedText) {
  const commands = JSON.parse(typedText.dataset.commands ?? "[]");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (commands.length) {
    if (reducedMotion) {
      typedText.textContent = commands[0];
    } else {
      new TypeWriter(typedText, commands).start();
    }
  }
}
