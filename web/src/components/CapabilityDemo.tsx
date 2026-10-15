import { useEffect, useState } from "react";
import type { CapabilityCopy, LandingCopy } from "../lib/landing";
import { Icon } from "./Icon";

interface Props {
  items: CapabilityCopy[];
  sample: LandingCopy["sample"];
  notes: LandingCopy["notes"];
  demo: LandingCopy["demo"];
  untouched: string;
}

const AUTOPLAY_MS = 6000;
const QUERY = "auth timeout";

const commands = [
  "agent-dump search 'auth timeout' --query 'path:.' --days 30",
  "agent-dump read codex://019a7c2e --json",
  "agent-dump export codex://019a7c2e --format markdown --output ./sessions",
  "agent-dump collect --days 7 --emit-prompt --save ./reports/weekly.md",
];

function Quote({ text }: { text: string }) {
  const [before, after] = text.split(QUERY);
  if (after === undefined) return <>{text}</>;
  return (
    <>
      {before}
      <mark>{QUERY}</mark>
      {after}
    </>
  );
}

function Search({ sample, demo }: Pick<Props, "sample" | "demo">) {
  const results = [
    { provider: "claude", title: sample.s1, meta: "2 hits · 3d", msg: 14, quote: sample.q1, loc: "claude://7f3c91#msg-14" },
    { provider: "codex", title: sample.s2, meta: "4 hits · 6d", msg: 3, quote: sample.q2, loc: "codex://019a7c2e#msg-3" },
    { provider: "cursor", title: sample.s3, meta: "1 hit · 12d" },
  ];
  return (
    <div className="win-body stg">
      <div className="sbar">
        <Icon name="search" />
        <span className="q">{QUERY}</span>
        <span className="kbd">s</span>
      </div>
      <div className="fchips">
        <span className="fchip on">path:.</span>
        <span className="fchip on">{demo.days}</span>
        <span className="fchip">{demo.provider}</span>
        <span className="fchip">{demo.role}</span>
      </div>
      {results.map((result) => (
        <div className="res" key={result.provider}>
          <div className="r1">
            <span className="pbadge">{result.provider}</span>
            <span className="t">{result.title}</span>
            <span className="m">{result.meta}</span>
          </div>
          {result.quote && (
            <>
              <p className="qq">
                › msg {result.msg} “<Quote text={result.quote} />”
              </p>
              <p className="loc">{result.loc}</p>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

function Read({ demo }: Pick<Props, "demo">) {
  return (
    <div className="win-body">
      <div className="rd stg">
        <div className="code">
          {"{\n  "}
          <span className="tm">"kind"</span>: <span className="tok">"read"</span>,{" "}
          <span className="tm">"status"</span>: <span className="tok">"ok"</span>
          {",\n  "}
          <span className="tm">"data"</span>
          {": {\n    "}
          <span className="tm">"total_messages"</span>: <span className="tam">38</span>
          {",\n    "}
          <span className="tm">"messages"</span>
          {": [ … ],\n    "}
          <span className="tm">"next_cursor"</span>: <span className="tok">"r1.7b2275…"</span>
          {"\n  },\n  "}
          <span className="tm">"has_more"</span>: <span className="tam">true</span>
          {"\n}"}
        </div>
        <ol className="rail">
          <li><b>PAGE 1</b><span>msg 1–16 · cursor →</span></li>
          <li><b>PAGE 2</b><span>msg 17–32 · cursor →</span></li>
          <li><b>PAGE 3</b><span>msg 33–38</span></li>
          <li className="end"><b>DONE</b><span>has_more=false · {demo.readDone}</span></li>
        </ol>
      </div>
    </div>
  );
}

function Export({ sample, demo, untouched }: Pick<Props, "sample" | "demo" | "untouched">) {
  return (
    <div className="win-body">
      <div className="ex stg">
        <div className="sheet">
          <div className="doc">
            <span className="fm">{"---\nuri: codex://019a7c2e\nprovider: codex\nmessages: 38\n---"}</span>
            {"\n"}
            <span className="hd"># {sample.s2}</span>
            {"\n\n"}
            <span className="rl">## user</span>
            {` · msg 1\n${demo.exportUser}\n\n`}
            <span className="rl">## assistant</span>
            {` · msg 2\n${demo.exportAssistant}`}
            <span className="stamp">{untouched}</span>
          </div>
        </div>
        <div className="side">
          <div className="filecard">
            <Icon name="folder" small />
            <span>./sessions/</span>
            <span className="fmt">DIR</span>
          </div>
          <div className="filecard">
            <span>{sample.s2}.md</span>
            <span className="fmt">MD</span>
          </div>
          <div className="filecard">
            <span>{sample.s2}.json</span>
            <span className="fmt">JSON</span>
          </div>
          <p className="inote">{demo.exportNote}</p>
        </div>
      </div>
    </div>
  );
}

function Collect({ notes, demo }: Pick<Props, "notes" | "demo">) {
  return (
    <div className="win-body">
      <div className="ctop">
        <span className="fchip on">{notes.scan}</span>
        <span className="fchip">{notes.chunk}</span>
      </div>
      <div className="chunks" aria-hidden="true">
        {Array.from({ length: 56 }, (_, index) => (
          <span
            key={index}
            className="ck"
            style={{ animationDelay: `${(0.15 + index * 0.035).toFixed(3)}s` }}
          />
        ))}
      </div>
      <div className="cfoot">
        <div className="stdout">
          <span className="tok">→ stdout</span> {demo.collectStdout}
        </div>
        <span className="okpill">
          <span className="pdot" />
          status: complete
        </span>
      </div>
    </div>
  );
}

export function CapabilityDemo({ items, sample, notes, demo, untouched }: Props) {
  const [active, setActive] = useState(0);
  const [auto, setAuto] = useState(true);

  useEffect(() => {
    if (!auto || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = setTimeout(() => setActive((active + 1) % items.length), AUTOPLAY_MS);
    return () => clearTimeout(timer);
  }, [active, auto, items.length]);

  const footers = [notes.search, notes.read, demo.exportFoot, notes.collect];
  return (
    <div className="capbox">
      <div className="ctabs" role="tablist" aria-orientation="vertical">
        {items.map((item, index) => {
          const current = index === active;
          return (
            <button
              key={item.verb}
              type="button"
              role="tab"
              id={`capability-tab-${index}`}
              aria-selected={current}
              aria-controls="capability-terminal"
              className="ctab"
              onClick={() => {
                setActive(index);
                setAuto(false);
              }}
            >
              <span className="top">
                <span className="no">0{index + 1}</span>
                <span className="vb">{item.verb}</span>
                <span className="lb">{item.label}</span>
              </span>
              <span className="bd">{item.body}</span>
              {current && auto && (
                <span className="prog" aria-hidden="true">
                  <i style={{ animationDuration: `${AUTOPLAY_MS}ms` }} />
                </span>
              )}
            </button>
          );
        })}
      </div>
      <div
        className="win"
        id="capability-terminal"
        role="tabpanel"
        aria-labelledby={`capability-tab-${active}`}
      >
        <div className="win-cmd">
          <span className="tok">$</span>
          <span>{commands[active]}</span>
        </div>
        <div key={active}>
          {active === 0 && <Search sample={sample} demo={demo} />}
          {active === 1 && <Read demo={demo} />}
          {active === 2 && <Export sample={sample} demo={demo} untouched={untouched} />}
          {active === 3 && <Collect notes={notes} demo={demo} />}
        </div>
        <p className="win-note">
          {active === 0 && <Icon name="search" small />}
          {footers[active]}
        </p>
      </div>
    </div>
  );
}
