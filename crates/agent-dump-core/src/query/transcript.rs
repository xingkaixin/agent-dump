use crate::session::{Message, Part, SessionData};
use serde_json::Value;

fn clean(value: &Value) -> String {
    if crate::compat::value::truthy(value) {
        crate::compat::value::string(value).trim().into()
    } else {
        String::new()
    }
}

pub fn message_texts(message: &Message) -> Vec<String> {
    let mut texts: Vec<_> = message
        .parts
        .iter()
        .filter_map(Part::content)
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .collect();
    texts.extend(legacy_texts(message));
    texts
}
pub fn visible_texts(message: &Message) -> Vec<String> {
    let mut texts: Vec<_> = message
        .parts
        .iter()
        .filter_map(|part| {
            if let Part::Text(part) = part {
                Some(part.text.trim().to_owned())
            } else {
                None
            }
        })
        .filter(|s| !s.is_empty())
        .collect();
    texts.extend(legacy_texts(message));
    texts
}

fn legacy_texts(message: &Message) -> Vec<String> {
    let mut texts = Vec::new();
    if let Some(content) = message.extra.get("content") {
        match content {
            Value::String(text) if !text.trim().is_empty() => {
                texts.push(text.clone());
            }
            Value::Array(items) => {
                for item in items {
                    let text = item
                        .as_str()
                        .map_or_else(|| clean(&item["text"]), str::to_owned);
                    if !text.trim().is_empty() {
                        texts.push(text);
                    }
                }
            }
            _ => {}
        }
    }
    texts
}

pub fn search_value(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Array(values) => format!(
            "[{}]",
            values.iter().map(json_value).collect::<Vec<_>>().join(", ")
        ),
        Value::Object(values) => format!(
            "{{{}}}",
            values
                .iter()
                .map(|(k, v)| format!(
                    "{}: {}",
                    serde_json::to_string(k).unwrap(),
                    json_value(v)
                ))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::Number(n) => crate::compat::json::number_text(n),
        _ => value.to_string(),
    }
}

fn json_value(value: &Value) -> String {
    if value.is_string() {
        serde_json::to_string(value).unwrap()
    } else {
        search_value(value)
    }
}
pub fn searchable(data: &SessionData) -> String {
    let mut texts = Vec::new();
    for message in &data.messages {
        texts.extend(message_texts(message));
        for part in &message.parts {
            if let Part::Tool(tool) = part {
                for value in [
                    tool.state
                        .get("arguments")
                        .or_else(|| tool.state.get("input")),
                    tool.state.get("output"),
                ]
                .into_iter()
                .flatten()
                .filter(|v| !v.is_null())
                {
                    texts.push(search_value(value));
                }
                if let Some(prompt) = tool.state.get("prompt") {
                    let prompt = clean(prompt);
                    if !prompt.is_empty() {
                        texts.push(prompt);
                    }
                }
            }
        }
    }
    texts
        .iter()
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join("\n\n")
}
