import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import {
  demoScript,
  demoSessions,
  tuiStrings,
  type DemoSession,
  type TuiStrings,
} from "../lib/browse-demo";

interface Props {
  lang: "zh" | "en";
  copy: {
    autoplay: string;
    replay: string;
    label: string;
    keysLabel: string;
    space: string;
    keys: string[];
  };
}

type Status = { key: keyof TuiStrings; args?: Record<string, number> };

type State = {
  selected: number;
  marked: string[];
  focus: "list" | "body";
  editing: "sessions" | "messages" | null;
  input: string;
  sessionQuery: string;
  messageQuery: string;
  hit: number;
  excerpt: boolean;
  radius: number;
  details: boolean;
  help: boolean;
  status: Status | null;
  scroll: number;
};

const initial: State = {
  selected: 0,
  marked: [],
  focus: "list",
  editing: null,
  input: "",
  sessionQuery: "",
  messageQuery: "",
  hit: 0,
  excerpt: false,
  radius: 3,
  details: false,
  help: false,
  status: null,
  scroll: 0,
};

const TICK_MS = 700;
const MACRO_MS = 110;

function format(template: string, args: Record<string, string | number> = {}) {
  return template.replace(/\{(\w+)\}/g, (match, name) =>
    name in args ? String(args[name]) : match,
  );
}

function view(state: State, sessions: DemoSession[]) {
  const words = state.sessionQuery.toLowerCase().split(/\s+/).filter(Boolean);
  const text = (session: DemoSession) =>
    `${session.title} ${session.messages.map((m) => m[1]).join(" ")}`.toLowerCase();
  const rows = sessions.filter((session) => words.every((word) => text(session).includes(word)));
  const selected = Math.min(state.selected, Math.max(0, rows.length - 1));
  const current = rows[selected];
  const phrase = state.messageQuery.toLowerCase();
  const hits = (current?.messages ?? []).flatMap(([, body], index) => {
    const lower = body.toLowerCase();
    const found = phrase
      ? lower.includes(phrase)
      : words.length > 0 && words.every((word) => lower.includes(word));
    return found ? [index] : [];
  });
  const hitIndex = hits.length ? hits[state.hit % hits.length] : -1;
  const total = current?.messages.length ?? 0;
  const range =
    hitIndex >= 0
      ? {
          start: Math.max(0, hitIndex - state.radius),
          end: Math.min(total, hitIndex + state.radius + 1),
          total,
        }
      : { start: 0, end: total, total };
  return { words, rows, selected, current, hits, hitIndex, range };
}

function press(state: State, key: string, sessions: DemoSession[]): State | null {
  const v = view(state, sessions);
  const next = (patch: Partial<State>): State => ({ ...state, status: null, ...patch });

  if (state.help) {
    if (key === "Escape" || key === "?" || key === "q") return next({ help: false });
    return key === "ArrowUp" || key === "ArrowDown" || key === " " ? state : null;
  }
  if (state.editing) {
    if (key === "Escape") return next({ editing: null, input: "" });
    if (key === "Enter" && state.editing === "sessions")
      return next({
        editing: null,
        input: "",
        sessionQuery: state.input.trim(),
        messageQuery: "",
        selected: 0,
        hit: 0,
        excerpt: false,
        scroll: 0,
      });
    if (key === "Enter")
      return next({
        editing: null,
        input: "",
        messageQuery: state.input,
        hit: 0,
        excerpt: false,
        scroll: 0,
        focus: "body",
      });
    if (key === "Backspace") return { ...state, input: state.input.slice(0, -1) };
    if (key.length === 1) return { ...state, input: state.input + key };
    return null;
  }

  const last = Math.max(0, v.rows.length - 1);
  const move = (to: number) =>
    to === v.selected
      ? state
      : next({ selected: to, messageQuery: "", hit: 0, excerpt: false, scroll: 0 });
  const inBody = state.focus === "body";

  switch (key) {
    case "ArrowDown":
    case "j":
      return inBody ? { ...state, scroll: state.scroll + 1 } : move(Math.min(v.selected + 1, last));
    case "ArrowUp":
    case "k":
      return inBody
        ? { ...state, scroll: Math.max(0, state.scroll - 1) }
        : move(Math.max(0, v.selected - 1));
    case "Home":
      return move(0);
    case "End":
      return move(last);
    case "ArrowRight":
    case "Enter":
      return { ...state, focus: "body" };
    case "ArrowLeft":
      return { ...state, focus: "list" };
    case "s":
      return next({ editing: "sessions", input: "" });
    case "/":
      return next({ editing: "messages", input: "" });
    case "c":
      return next({ sessionQuery: "", messageQuery: "", selected: 0, hit: 0, excerpt: false, scroll: 0 });
    case "?":
      return { ...state, help: true };
    case "n":
    case "N": {
      const count = v.hits.length;
      if (!count) return state;
      const hit = key === "N" ? (state.hit + count - 1) % count : (state.hit + 1) % count;
      return next({ hit, focus: "body", scroll: 0 });
    }
    case "x":
      if (state.excerpt) return next({ excerpt: false });
      if (v.hits.length)
        return next({ excerpt: true, radius: 3, scroll: 0, status: { key: "excerptHelp" } });
      return next({ status: { key: "needHit" } });
    case "+":
    case "=":
    case "-":
      if (!state.excerpt || !v.current) return state;
      return {
        ...state,
        radius:
          key === "-"
            ? Math.max(0, state.radius - 1)
            : Math.min(v.current.messages.length, state.radius + 1),
      };
    case "Escape":
      return state.excerpt ? next({ excerpt: false }) : next({ status: { key: "quit" } });
    case "q":
    case "Q":
      return next({ status: { key: "quit" } });
    case "t":
      return { ...state, details: !state.details };
    case " ": {
      if (!v.current) return state;
      const uri = v.current.uri;
      const marked = state.marked.includes(uri)
        ? state.marked.filter((item) => item !== uri)
        : [...state.marked, uri];
      return next({ marked, status: { key: "marked", args: { count: marked.length } } });
    }
    case "e":
      if (state.marked.length && !state.excerpt)
        return next({ status: { key: "exported", args: { count: state.marked.length } } });
      if (state.excerpt)
        return next({
          status: { key: "exportedRange", args: { start: v.range.start + 1, end: v.range.end } },
        });
      return v.current ? next({ status: { key: "exportedOne" } }) : state;
    case "y":
      return v.current ? next({ status: { key: "copyRequest" } }) : state;
    default:
      return null;
  }
}

function body(state: State, v: ReturnType<typeof view>) {
  if (!v.current) return { items: [], offset: 0 };
  const items = v.current.messages
    .map(([role, text, tool], index) => ({ index, role, text, tool: tool?.trim() }))
    .filter(
      ({ index }) => !state.excerpt || (index >= v.range.start && index < v.range.end),
    );
  const active = items.findIndex((item) => item.index === v.hitIndex);
  const offset = Math.min(
    Math.max(0, items.length - 1),
    Math.max(0, active - 1) + state.scroll,
  );
  return { items, offset };
}

function Marked({ text, terms }: { text: string; terms: string[] }) {
  if (!terms.length) return <>{text}</>;
  const pattern = new RegExp(
    `(${terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`,
    "gi",
  );
  return (
    <>
      {text
        .split(pattern)
        .map((part, index) => (index % 2 ? <mark key={index}>{part}</mark> : part))}
    </>
  );
}

const chips: [string, string][] = [
  ["↓", "j"],
  ["↑", "k"],
  ["Tab", "pane"],
  ["", " "],
  ["e", "e"],
  ["s", "search"],
  ["/", "find"],
  ["n", "n"],
  ["x", "x"],
  ["t", "t"],
  ["c", "c"],
  ["?", "?"],
];

export function BrowseDemo({ lang, copy }: Props) {
  const t = tuiStrings[lang];
  const sessions = demoSessions[lang];
  const [state, setState] = useState(initial);
  const [auto, setAuto] = useState(true);
  const stateRef = useRef(state);
  const step = useRef(0);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  function apply(key: string) {
    const next = press(stateRef.current, key, sessions);
    if (!next) return false;
    stateRef.current = next;
    setState(next);
    return true;
  }

  function reset() {
    stateRef.current = initial;
    setState(initial);
  }

  function takeOver() {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setAuto(false);
  }

  function macro(keys: string[]) {
    takeOver();
    timers.current = keys.map((key, index) => setTimeout(() => apply(key), index * MACRO_MS));
  }

  useEffect(() => {
    if (!auto || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = setInterval(() => {
      const key = demoScript[step.current % demoScript.length];
      step.current += 1;
      if (key === "RESET") reset();
      else if (key !== "__") apply(key);
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [auto]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (apply(event.key)) {
      event.preventDefault();
      takeOver();
    }
  }

  const v = view(state, sessions);
  const { items, offset } = body(state, v);
  const terms = v.hits.length
    ? state.messageQuery
      ? [state.messageQuery]
      : v.words
    : [];
  let status: string;
  if (state.editing)
    status = `${state.editing === "sessions" ? t.inputSessions : t.inputMessages} > ${state.input}`;
  else if (state.status) status = format(t[state.status.key], state.status.args);
  else if (v.hits.length) status = format(t.matches, { count: v.hits.length });
  else if (v.words.length) status = format(t.results, { count: v.rows.length });
  else status = t.ready;
  const bodyTitle = state.excerpt
    ? format(t.excerptRange, { start: v.range.start + 1, end: v.range.end, total: v.range.total })
    : `${t.body} · ${offset + 1}/${items.length}`;

  return (
    <>
      <div className="tui">
        <div className="term-bar">
          <span className="tab">
            <span className="prompt-mark">&gt;_</span>
            agent-dump --browse --time-field updated --days 7
          </span>
          {auto ? (
            <span className="auto-pill">
              <span className="pdot" aria-hidden="true" />
              {copy.autoplay}
            </span>
          ) : (
            <button
              type="button"
              className="replay"
              onClick={() => {
                takeOver();
                step.current = 0;
                reset();
                setAuto(true);
              }}
            >
              {copy.replay}
            </button>
          )}
        </div>
        <div
          className="tui-screen"
          tabIndex={0}
          role="application"
          aria-roledescription="terminal"
          aria-label={copy.label}
          onKeyDown={onKeyDown}
          onMouseDown={takeOver}
        >
          <div className="tui-body">
            <div className={state.focus === "list" ? "tpane act" : "tpane"}>
              <p className="ph">
                <span>{t.sessions}</span>
                <span>{v.rows.length}</span>
              </p>
              {state.sessionQuery && (
                <p className="tsearch">
                  {format(t.state, { count: v.rows.length, mode: t.terms, query: state.sessionQuery })}
                </p>
              )}
              {v.rows.length === 0 && <p className="tempty">{t.noMatches}</p>}
              {v.rows.map((session, index) => {
                const marked = state.marked.includes(session.uri);
                return (
                  <div
                    key={session.uri}
                    className={`trow${index === v.selected ? " sel" : ""}${marked ? " marked" : ""}`}
                  >
                    <span className="cr">{index === v.selected ? "›" : ""}</span>
                    <span className="mk2">{marked ? "●" : "○"}</span>
                    <span className="tt">{session.title}</span>
                    <span className="tw">
                      {session.provider} · {session.when}
                    </span>
                  </div>
                );
              })}
            </div>
            <div className={state.focus === "body" ? "tpane act" : "tpane"}>
              <p className="ph">
                <span>{bodyTitle}</span>
                <span>{v.current?.path}</span>
              </p>
              {v.current ? (
                <p className="thead">
                  <b>{v.current.uri}</b> · {v.current.title}
                </p>
              ) : (
                <p className="tempty">{t.noMatches}</p>
              )}
              {items.slice(offset).map((item) => (
                <div key={item.index}>
                  <div className={item.index === v.hitIndex ? "tmsg cur" : "tmsg"}>
                    <span className={item.role === "user" ? "trole u" : "trole a"}>
                      {item.role}
                    </span>
                    <span>
                      <Marked text={item.text} terms={terms} />
                    </span>
                  </div>
                  {state.details && item.tool && <p className="ttool">{item.tool}</p>}
                </div>
              ))}
            </div>
          </div>
          <div className="tstat">
            <span className="l" aria-live="polite">
              {status}
              {state.editing && <span className="caret" aria-hidden="true" />}
            </span>
            <span className="r">{t.scope}</span>
          </div>
          {state.help && (
            <div className="thelp">
              <b>{t.helpTitle}</b>
              {t.helpFull}
            </div>
          )}
        </div>
      </div>
      <div role="group" aria-label={copy.keysLabel} className="keys">
        {chips.map(([cap, action], index) => (
          <button
            key={action}
            type="button"
            className="key"
            onClick={() => {
              if (action === "search") macro(["s", "a", "u", "t", "h", "Enter"]);
              else if (action === "find") macro(["/", "t", "o", "k", "e", "n", "Enter"]);
              else {
                takeOver();
                apply(
                  action === "pane"
                    ? stateRef.current.focus === "list"
                      ? "ArrowRight"
                      : "ArrowLeft"
                    : action,
                );
              }
            }}
          >
            <kbd className="kbd">{cap || copy.space}</kbd>
            {copy.keys[index]}
          </button>
        ))}
      </div>
    </>
  );
}
