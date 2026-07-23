import { useRef, useState } from "react";
import { CheckIcon, CopyIcon } from "@phosphor-icons/react";

interface Props {
  text: string;
  copyLabel: string;
  copiedLabel: string;
}

function fallbackCopy(text: string) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.cssText = "position:absolute;opacity:0;pointer-events:none";
  document.body.append(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

export function CopyButton({ text, copyLabel, copiedLabel }: Props) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  async function onCopy() {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        fallbackCopy(text);
      }
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard denied — leave state untouched */
    }
  }

  const label = copied ? copiedLabel : copyLabel;

  return (
    <>
      <button
        type="button"
        onClick={onCopy}
        aria-label={label}
        title={label}
        className="group grid size-8 shrink-0 place-items-center rounded-[var(--radius-xs)] border border-line-strong text-muted transition-[transform,color,background-color,border-color] duration-150 ease-out hover:bg-fg hover:text-bg hover:border-fg active:scale-95"
      >
        <span className="relative block size-3.5">
        <CopyIcon
          weight="bold"
          className="absolute inset-0 size-3.5 transition-[opacity,transform] duration-150 ease-out"
          style={{ opacity: copied ? 0 : 1, transform: copied ? "scale(0.75)" : "scale(1)" }}
        />
        <CheckIcon
          weight="bold"
          className="absolute inset-0 size-3.5 text-accent transition-[opacity,transform] duration-150 ease-out group-hover:text-bg"
          style={{ opacity: copied ? 1 : 0, transform: copied ? "scale(1)" : "scale(0.75)" }}
        />
        </span>
      </button>
      <span role="status" aria-live="polite" className="sr-only">
        {copied ? copiedLabel : ""}
      </span>
    </>
  );
}
