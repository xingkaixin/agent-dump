use crate::session::{Message, Part, ToolPart};
use serde_json::{Map, Value};
use std::collections::HashMap;

pub fn fold_assistant(
    messages: &mut [Message],
    current: Option<usize>,
    parts: &mut Vec<Part>,
    reasoning: bool,
) -> Option<usize> {
    let index = current?;
    let message = &mut messages[index];
    if message.parts.iter().any(|part| {
        matches!(part, Part::Tool(_))
            || (reasoning && matches!(part, Part::Text(_)))
    }) {
        return None;
    }
    for part in parts.drain(..) {
        if message.parts.last() != Some(&part) {
            message.parts.push(part);
        }
    }
    Some(index)
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
