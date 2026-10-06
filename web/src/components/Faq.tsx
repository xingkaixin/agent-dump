import { Accordion } from "@base-ui/react/accordion";
import { PlusIcon } from "@phosphor-icons/react";

interface Props {
  items: { question: string; answer: string }[];
}

export function Faq({ items }: Props) {
  return (
    <Accordion.Root multiple={false} className="faq-list">
      {items.map((item, i) => (
        <Accordion.Item key={i} value={i} className="faq-item">
          <Accordion.Header className="faq-item__header">
            <Accordion.Trigger className="faq-item__trigger">
              <span>{item.question}</span>
              <PlusIcon weight="bold" aria-hidden="true" className="faq-item__icon" />
            </Accordion.Trigger>
          </Accordion.Header>
          <Accordion.Panel keepMounted className="ad-accordion-panel">
            <p className="faq-item__answer">{item.answer}</p>
          </Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion.Root>
  );
}
