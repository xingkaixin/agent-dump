import { Tabs } from "@base-ui/react/tabs";
import { CopyButton } from "./CopyButton";

interface Group {
  label: string;
  tabs: { label: string; code: string }[];
}

interface Props {
  groups: Group[];
  skill: { note: string; command: string };
  copy: string;
  copied: string;
}

function CommandLine({ code, copy, copied }: { code: string; copy: string; copied: string }) {
  return (
    <div className="flex items-center gap-3 rounded-[var(--radius-sm)] border border-line bg-bg px-3.5 py-2.5">
      <span aria-hidden="true" className="select-none text-subtle">
        $
      </span>
      <code className="flex-1 overflow-x-auto whitespace-nowrap font-mono text-[13.5px] text-fg">
        {code}
      </code>
      <CopyButton text={code} copyLabel={copy} copiedLabel={copied} />
    </div>
  );
}

export function InstallTabs({ groups, skill, copy, copied }: Props) {
  return (
    <div className="grid gap-5">
      {groups.map((group) => (
        <div
          key={group.label}
          className="rounded-[var(--radius-md)] border border-line bg-surface/60 p-4 sm:p-5"
        >
          <p className="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-subtle">
            {group.label}
          </p>
          <Tabs.Root defaultValue={0}>
            <Tabs.List className="relative mb-4 flex gap-1 border-b border-line">
              {group.tabs.map((tab, i) => (
                <Tabs.Tab
                  key={tab.label}
                  value={i}
                  className="cursor-pointer rounded-t-[var(--radius-xs)] px-3 py-1.5 font-mono text-[13px] text-muted transition-colors duration-150 ease-out hover:text-fg data-[active]:text-fg"
                >
                  {tab.label}
                </Tabs.Tab>
              ))}
              <Tabs.Indicator className="ad-tab-indicator" />
            </Tabs.List>
            {group.tabs.map((tab, i) => (
              <Tabs.Panel key={tab.label} value={i}>
                <CommandLine code={tab.code} copy={copy} copied={copied} />
              </Tabs.Panel>
            ))}
          </Tabs.Root>
        </div>
      ))}

      <div className="rounded-[var(--radius-md)] border border-dashed border-line-strong p-4 sm:p-5">
        <p className="mb-3 text-[13px] text-muted">{skill.note}</p>
        <CommandLine code={skill.command} copy={copy} copied={copied} />
      </div>
    </div>
  );
}
