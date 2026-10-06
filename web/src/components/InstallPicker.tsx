import { useState } from "react";
import { CopyButton } from "./CopyButton";

interface Method {
  label: string;
  code: string;
  note?: string;
}

interface Props {
  groups: { label: string; methods: Method[] }[];
  skill: { note: string; command: string };
  copy: string;
  copied: string;
}

export function InstallPicker({ groups, skill, copy, copied }: Props) {
  const methods = groups.flatMap((group) => group.methods);
  const [selected, setSelected] = useState(methods[0].label);
  const method = methods.find((item) => item.label === selected)!;

  return (
    <div className="install-picker">
      {groups.map((group) => (
        <div key={group.label} className="install-group">
          <span className="install-group__label">{group.label}</span>
          <div role="group" aria-label={group.label} className="install-group__options">
            {group.methods.map((item) => (
              <button
                key={item.label}
                type="button"
                aria-pressed={item.label === selected}
                aria-controls="install-command"
                className="pill"
                onClick={() => setSelected(item.label)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      ))}
      <div id="install-command" className="term install-command" aria-label={method.label} role="region">
        <span aria-hidden="true" className="accent">$</span>
        <code>{method.code}</code>
        <CopyButton
          key={method.label}
          text={method.code}
          copyLabel={copy}
          copiedLabel={copied}
          installMethod={method.label}
        />
      </div>
      {method.note && <p className="install-note">{method.note}</p>}
      <div className="install-skill">
        <span>{skill.note}</span>
        <code>{skill.command}</code>
        <CopyButton text={skill.command} copyLabel={copy} copiedLabel={copied} />
      </div>
    </div>
  );
}
