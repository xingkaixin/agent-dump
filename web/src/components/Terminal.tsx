import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import type { OutputTone, TerminalScene } from "../lib/i18n";

interface Props {
  scenes: TerminalScene[];
  label: string;
}

type Phase = "typing" | "revealing" | "holding" | "deleting";
interface State {
  scene: number;
  phase: Phase;
  chars: number;
  lines: number;
}

const TYPE_MS = 46;
const DELETE_MS = 22;
const LINE_MS = 170;
const HOLD_MS = 2600;
const PAUSE_MS = 500;

const toneClass: Record<OutputTone, string> = {
  dim: "text-term-dim",
  text: "text-term-fg",
  ok: "text-phosphor",
  scheme: "text-phosphor",
};

function next(state: State, sceneCount: number, scene: TerminalScene): { state: State; wait: number } {
  const cmdLen = scene.command.length;
  const outLen = scene.output.length;
  switch (state.phase) {
    case "typing":
      if (state.chars < cmdLen) {
        return { state: { ...state, chars: state.chars + 1 }, wait: TYPE_MS };
      }
      return { state: { ...state, phase: "revealing" }, wait: LINE_MS };
    case "revealing":
      if (state.lines < outLen) {
        return { state: { ...state, lines: state.lines + 1 }, wait: LINE_MS };
      }
      return { state: { ...state, phase: "holding" }, wait: LINE_MS };
    case "holding":
      // The caret blinks here; hold long enough to read before deleting.
      return { state: { ...state, phase: "deleting", lines: 0 }, wait: HOLD_MS };
    case "deleting":
      if (state.chars > 0) {
        return { state: { ...state, chars: state.chars - 1 }, wait: DELETE_MS };
      }
      return {
        state: { scene: (state.scene + 1) % sceneCount, phase: "typing", chars: 0, lines: 0 },
        wait: PAUSE_MS,
      };
  }
}

export function Terminal({ scenes, label }: Props) {
  const reduce = useReducedMotion();
  // Start on the first scene fully rendered so SSR / no-JS shows real content, then
  // the effect continues naturally into hold -> delete -> next.
  const [state, setState] = useState<State>({
    scene: 0,
    phase: "holding",
    chars: scenes[0].command.length,
    lines: scenes[0].output.length,
  });

  useEffect(() => {
    if (reduce) return;
    const scene = scenes[state.scene];
    const { state: nextState, wait } = next(state, scenes.length, scene);
    const id = setTimeout(() => setState(nextState), wait);
    return () => clearTimeout(id);
  }, [state, reduce, scenes]);

  const active = reduce ? scenes[0] : scenes[state.scene];
  const typed = reduce ? active.command : active.command.slice(0, state.chars);
  const shownLines = reduce ? active.output.length : state.lines;
  const caretVisible = reduce ? false : state.phase === "typing" || state.phase === "holding";

  return (
    <div
      role="img"
      aria-label={label}
      className="overflow-hidden rounded-[var(--radius-lg)] border border-line-strong bg-term shadow-[0_24px_60px_-24px_rgba(0,0,0,0.5)]"
    >
      <div className="flex items-center gap-2 border-b border-white/8 px-4 py-3">
        <span className="size-2.5 rounded-full bg-white/15" />
        <span className="size-2.5 rounded-full bg-white/15" />
        <span className="size-2.5 rounded-full bg-white/15" />
        <span className="ml-2 font-mono text-[11px] text-term-dim">agent-dump</span>
      </div>
      <div className="min-h-[13.5rem] px-4 py-4 font-mono text-[13px] leading-[1.7] sm:px-5">
        <div className="flex items-baseline gap-2">
          <span aria-hidden="true" className="text-phosphor">
            $
          </span>
          <span className="text-term-fg">
            {typed}
            <span
              aria-hidden="true"
              className="ml-0.5 inline-block h-[1.05em] w-[0.55ch] translate-y-[0.15em] bg-term-fg align-baseline"
              style={{
                animation: caretVisible ? "ad-blink 1s steps(1) infinite" : "none",
                opacity: caretVisible ? undefined : 0,
              }}
            />
          </span>
        </div>
        <div className="mt-2 grid gap-1">
          {active.output.slice(0, shownLines).map((line, i) => (
            <motion.div
              key={`${state.scene}-${i}`}
              initial={reduce ? false : { opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.24, ease: [0.23, 1, 0.32, 1] }}
              className={`whitespace-pre ${toneClass[line.tone]}`}
            >
              {line.text}
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}
