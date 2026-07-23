import { Accordion } from "@base-ui/react/accordion";
import { PlusIcon } from "@phosphor-icons/react";

interface Props {
  items: { question: string; answer: string }[];
}

export function Faq({ items }: Props) {
  return (
    <Accordion.Root
      multiple={false}
      className="grid divide-y divide-line border-y border-line"
    >
      {items.map((item, i) => (
        <Accordion.Item key={i} value={i} className="group">
          <Accordion.Header>
            <Accordion.Trigger className="flex w-full cursor-pointer items-center justify-between gap-4 rounded-[var(--radius-xs)] py-4 text-left">
              <span className="font-mono text-[15px] font-medium text-fg">{item.question}</span>
              <PlusIcon
                weight="bold"
                aria-hidden="true"
                className="size-4 shrink-0 text-subtle transition-transform duration-[260ms] ease-out group-data-[open]:rotate-45"
              />
            </Accordion.Trigger>
          </Accordion.Header>
          <Accordion.Panel keepMounted className="ad-accordion-panel">
            <p className="max-w-[62ch] pb-5 pr-8 text-[14px] leading-relaxed text-muted">
              {item.answer}
            </p>
          </Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion.Root>
  );
}
