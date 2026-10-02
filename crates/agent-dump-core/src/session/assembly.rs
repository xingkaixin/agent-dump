use crate::session::{Message, Part, ToolPart};
use serde_json::{Map, Value};
use std::collections::HashMap;

#[derive(Default)]
pub struct AssistantFold {
    current: Option<usize>,
    scanned: usize,
    has_tool: bool,
    has_text: bool,
    has_plan: bool,
}

impl AssistantFold {
    fn refresh(&mut self, messages: &[Message], index: usize) {
        if self.current != Some(index) {
            *self = Self {
                current: Some(index),
                ..Self::default()
            };
        }
        let parts = &messages[index].parts;
        // Decoders append parts; tool and plan backfills keep their variants.
        for part in &parts[self.scanned..] {
            self.has_tool |= matches!(part, Part::Tool(_));
            self.has_text |= matches!(part, Part::Text(_));
            self.has_plan |= matches!(part, Part::Plan(_));
        }
        self.scanned = parts.len();
    }

    pub fn fold(
        &mut self,
        messages: &mut [Message],
        current: Option<usize>,
        parts: &mut Vec<Part>,
        reasoning: bool,
    ) -> Option<usize> {
        let index = current?;
        self.refresh(messages, index);
        if self.has_tool || (reasoning && self.has_text) {
            return None;
        }
        let message = &mut messages[index];
        for part in parts.drain(..) {
            if message.parts.last() != Some(&part) {
                message.parts.push(part);
            }
        }
        Some(index)
    }

    pub fn has_plan(&mut self, messages: &[Message], index: usize) -> bool {
        self.refresh(messages, index);
        self.has_plan
    }
}

pub fn backfill<'a>(
    messages: &'a mut [Message],
    pending: &HashMap<String, (usize, usize)>,
    id: &str,
    parts: &[Part],
    updates: Option<Map<String, Value>>,
) -> crate::Result<Option<&'a mut ToolPart>> {
    if id.is_empty()
        || (parts.is_empty() && updates.as_ref().is_none_or(Map::is_empty))
    {
        return Ok(None);
    }
    let Some(&(message, part)) = pending.get(id) else {
        return Ok(None);
    };
    let Part::Tool(tool) = &mut messages[message].parts[part] else {
        return Ok(None);
    };
    if !parts.is_empty() {
        let mut output = parts
            .iter()
            .map(serde_json::to_value)
            .collect::<Result<Vec<_>, _>>()?;
        let previous = tool.state.entry("output").or_insert(Value::Null);
        match previous {
            Value::Array(values) => values.append(&mut output),
            Value::Null => *previous = output.into(),
            _ => {
                output.insert(0, previous.clone());
                *previous = output.into();
            }
        }
    }
    if let Some(updates) = updates {
        tool.state.extend(updates);
    }
    Ok(Some(tool))
}
