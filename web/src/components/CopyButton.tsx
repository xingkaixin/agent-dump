import { copyText } from "../lib/clipboard";
import { trackEvent } from "../lib/analytics";
import { useRef, useState } from "react";
import { Icon } from "./Icon";

interface Props {
  text: string;
  copyLabel: string;
  copiedLabel: string;
  installMethod?: string;
}

export function CopyButton({ text, copyLabel, copiedLabel, installMethod }: Props) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  async function onCopy() {
    try {
      if (!(await copyText(text))) return;
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1600);
      if (installMethod) {
        trackEvent("install-copy", { method: installMethod });
      }
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
        className={copied ? "cbtn ok" : "cbtn"}
      >
        <Icon name={copied ? "check" : "copy"} small />
        <span aria-hidden="true">{label}</span>
      </button>
      <span role="status" aria-live="polite" className="sr-only">
        {copied ? copiedLabel : ""}
      </span>
    </>
  );
}
