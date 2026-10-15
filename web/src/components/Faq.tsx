import { Accordion } from "@base-ui/react/accordion";
import { Icon } from "./Icon";

interface Props {
  items: { question: string; answer: string }[];
}

export function Faq({ items }: Props) {
  return (
    <Accordion.Root multiple={false} defaultValue={[0]}>
      {items.map((item, i) => (
        <Accordion.Item key={i} value={i} className="qa">
          <Accordion.Header>
            <Accordion.Trigger className="qbtn">
              <span>{item.question}</span>
              <span className="pl">
                <Icon name="plus" small />
              </span>
            </Accordion.Trigger>
          </Accordion.Header>
          <Accordion.Panel keepMounted className="qpanel">
            <p className="qans">{item.answer}</p>
          </Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion.Root>
  );
}
