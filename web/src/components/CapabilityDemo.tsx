import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import type { CapabilityCopy } from "../lib/landing";

interface Props {
  items: CapabilityCopy[];
  sample: { s1: string; s2: string; s3: string; q1: string; q2: string };
  notes: {
    search: string;
    read: string;
    scan: string;
    chunk: string;
    prompt: string;
    collect: string;
  };
  untouched: string;
}

const AUTOPLAY_MS = 7000;

const commands = [
  "agent-dump search 'auth timeout' --query 'path:.' --days 30",
  "agent-dump head codex://019a7c2e --json",
  "agent-dump export codex://019a7c2e --format markdown --output ./sessions",
  "agent-dump collect --days 7 --emit-prompt --save ./reports/weekly.md",
];
const files = ["search", "head --json", "export", "collect"];

function Line({ delay, className, children }: { delay: number; className?: string; children: ReactNode }) {
  return (
    <div className={`term-line ${className ?? ""}`} style={{ animationDelay: `${delay}s` }}>
      {children}
    </div>
  );
}

function Output({ index, sample, notes, untouched }: Omit<Props, "items"> & { index: number }) {
  const start = commands[index].length * 0.028 + 0.4;
  const at = (step: number) => start + step * 0.15;
  if (index === 0)
    return (
      <>
        <Line delay={at(0)} className="row"><span className="accent">claude://7f3c91</span><span>{sample.s1}</span><span className="subtle">2 hits · 3d</span></Line>
        <Line delay={at(1)} className="muted">{`  › msg 14  “${sample.q1}”`}</Line>
        <Line delay={at(2)} className="row"><span className="accent">codex://019a7c2e</span><span>{sample.s2}</span><span className="subtle">4 hits · 6d</span></Line>
        <Line delay={at(3)} className="muted">{`  › msg 3   “${sample.q2}”`}</Line>
        <Line delay={at(4)} className="row"><span className="accent">cursor://b21e04</span><span>{sample.s3}</span><span className="subtle">1 hit · 12d</span></Line>
        <Line delay={at(6)} className="subtle note">{notes.search}</Line>
      </>
    );
  if (index === 1)
    return (
      <>
        <Line delay={at(0)}>{"{"}</Line>
        <Line delay={at(1)}>{"  "}<span className="muted">"uri"</span>: <span className="ok">"codex://019a7c2e"</span>,</Line>
        <Line delay={at(2)}>{"  "}<span className="muted">"title"</span>: <span className="ok">"{sample.s2}"</span>,</Line>
        <Line delay={at(3)}>{"  "}<span className="muted">"messages"</span>: <span className="num">38</span>,</Line>
        <Line delay={at(4)}>{"  "}<span className="muted">"next_cursor"</span>: <span className="ok">"c_0040"</span>,</Line>
        <Line delay={at(5)}>{"  "}<span className="muted">"has_more"</span>: <span className="accent">true</span></Line>
        <Line delay={at(6)}>{"}"}</Line>
        <Line delay={at(8)} className="subtle note">{notes.read}</Line>
      </>
    );
  if (index === 2)
    return (
      <>
        <Line delay={at(0)} className="muted">reading   codex://019a7c2e  (38 messages)</Line>
        <Line delay={at(1)} className="muted">writing   ./sessions/{sample.s2}.md</Line>
        <Line delay={at(2)} className="ok">ok        {untouched}</Line>
        <Line delay={at(4)} className="term-doc">
          <div className="fg"># {sample.s2}</div>
          <div className="subtle">source: codex://019a7c2e · msg 3–17</div>
          <div>## User · {sample.q2}</div>
        </Line>
      </>
    );
  return (
    <>
      <Line delay={at(0)} className="muted">scan      {notes.scan}</Line>
      <Line delay={at(1)} className="muted">chunk     {notes.chunk}</Line>
      <Line delay={at(2)} className="muted">prompt    {notes.prompt}</Line>
      <Line delay={at(3)} className="muted">target    ./reports/weekly.md</Line>
      <Line delay={at(4)} className="ok">status    complete</Line>
      <Line delay={at(6)} className="subtle note">{notes.collect}</Line>
    </>
  );
}

export function CapabilityDemo({ items, ...rest }: Props) {
  const [active, setActive] = useState(0);
  const [auto, setAuto] = useState(true);

  useEffect(() => {
    if (!auto || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = setTimeout(() => setActive((active + 1) % items.length), AUTOPLAY_MS);
    return () => clearTimeout(timer);
  }, [active, auto, items.length]);

  const command = commands[active];
  return (
    <div className="capability-demo">
      <div className="capability-tabs">
        {items.map((item, index) => {
          const current = index === active;
          return (
            <button
              key={item.verb}
              type="button"
              aria-pressed={current}
              aria-controls="capability-terminal"
              className="capability-tab"
              onClick={() => {
                setActive(index);
                setAuto(false);
              }}
            >
              <span className="capability-tab__num">0{index + 1}</span>
              <span className="capability-tab__text">
                <span className="capability-tab__label">
                  {item.verb} · {item.label}
                </span>
                {current && <span className="capability-tab__body">{item.body}</span>}
              </span>
              {current && auto && (
                <span
                  className="capability-tab__progress"
                  style={{ animationDuration: `${AUTOPLAY_MS}ms` }}
                  aria-hidden="true"
                />
              )}
            </button>
          );
        })}
      </div>
      <div className="term terminal-window" id="capability-terminal" aria-live="polite">
        <div className="terminal-window__bar">
          <span>~/work/gateway</span>
          <span>agent-dump {files[active]}</span>
        </div>
        <div className="terminal-window__body" key={active}>
          <div>
            <span className="accent">$ </span>
            <span className="typed" style={{ "--n": command.length } as CSSProperties}>
              {command}
            </span>
            <span className="caret" aria-hidden="true" />
          </div>
          <div className="term-gap" />
          <Output index={active} {...rest} />
        </div>
      </div>
    </div>
  );
}
