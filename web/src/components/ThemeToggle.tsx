import { useState } from "react";
import { Toggle } from "@base-ui/react/toggle";
import { MoonIcon, SunIcon } from "@phosphor-icons/react";

const KEY = "agent-dump-theme";
const THEME_COLOR = { light: "#faf8f4", dark: "#141109" } as const;

function readTheme(): "light" | "dark" {
  if (typeof document === "undefined") return "light";
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

export function ThemeToggle({ label }: { label: string }) {
  const [theme, setTheme] = useState<"light" | "dark">(readTheme);
  const isDark = theme === "dark";

  function onToggle(pressed: boolean) {
    const next = pressed ? "dark" : "light";
    setTheme(next);
    const root = document.documentElement;
    // Crossfade every themed surface together, but only when motion is allowed.
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      root.classList.add("theme-transition");
      window.setTimeout(() => root.classList.remove("theme-transition"), 260);
    }
    root.setAttribute("data-theme", next);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[next]);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* storage unavailable — theme still applies for this page */
    }
  }

  return (
    <Toggle
      pressed={isDark}
      onPressedChange={onToggle}
      aria-label={label}
      title={label}
      className="grid size-9 cursor-pointer place-items-center rounded-[var(--radius-sm)] border border-line text-muted transition-[transform,color,background-color,border-color] duration-150 ease-out hover:border-line-strong hover:text-fg active:scale-95"
    >
      <span className="relative block size-[18px]">
        <SunIcon
          weight="bold"
          aria-hidden="true"
          className="absolute inset-0 size-[18px] transition-[opacity,transform] duration-200 ease-out"
          style={{ opacity: isDark ? 0 : 1, transform: isDark ? "rotate(-90deg) scale(0.6)" : "none" }}
        />
        <MoonIcon
          weight="bold"
          aria-hidden="true"
          className="absolute inset-0 size-[18px] text-accent transition-[opacity,transform] duration-200 ease-out"
          style={{ opacity: isDark ? 1 : 0, transform: isDark ? "none" : "rotate(90deg) scale(0.6)" }}
        />
      </span>
    </Toggle>
  );
}
