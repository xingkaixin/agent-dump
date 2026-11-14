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
    visible_segments(message)
        .into_iter()
        .map(|(text, _)| text)
        .collect()
}

pub fn visible_segments(
    message: &Message,
) -> Vec<(String, Option<crate::session::timestamp::Timestamp>)> {
    let time = |millis: i64| {
        if message.inferred_time || millis == 0 {
            return None;
        }
        millis.checked_mul(1000).and_then(|micros| {
            crate::session::timestamp::Timestamp::from_microsecond(micros).ok()
        })
    };
    let mut segments: Vec<_> = message
        .parts
        .iter()
        .filter_map(|part| {
            if let Part::Text(part) = part {
                let text = part.text.trim();
                (!text.is_empty())
                    .then(|| (text.to_owned(), time(part.time_created)))
            } else {
                None
            }
        })
        .collect();
    segments.extend(
        legacy_texts(message)
            .into_iter()
            .map(|text| (text, time(message.time_created))),
    );
    segments
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
pub fn searchable_message(message: &Message) -> String {
    let mut texts = message_texts(message);
    for part in &message.parts {
        if let Part::Tool(tool) = part {
            let output = tool.state.get("output").filter(|v| !v.is_null());
            let error = tool
                .state
                .get("error")
                .filter(|v| !v.is_null() && Some(*v) != output);
            for value in [
                tool.state
                    .get("arguments")
                    .or_else(|| tool.state.get("input")),
                output,
                error,
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
    texts
        .iter()
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join("\n\n")
}

pub fn searchable(data: &SessionData) -> String {
    data.messages
        .iter()
        .map(searchable_message)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join("\n\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn searchable_message_indexes_unique_tool_error() {
        let mut message = Message::new("m1".into(), "assistant", 1, Vec::new());
        message.parts = vec![
            Part::tool(
                "read",
                "c1",
                json!({
                    "status": "error",
                    "input": {"path": "missing.rs"},
                    "output": null,
                    "error": "error-only-needle"
                }),
                1,
            ),
            Part::tool(
                "edit",
                "c2",
                json!({
                    "status": "error",
                    "input": {"path": "a.rs"},
                    "output": "shared-error-needle",
                    "error": "shared-error-needle"
                }),
                2,
            ),
            Part::tool(
                "bash",
                "c3",
                json!({
                    "status": "error",
                    "input": {"command": "false"},
                    "output": "stdout-part",
                    "error": "distinct-error-part"
                }),
                3,
            ),
        ];
        let corpus = searchable_message(&message);
        assert!(corpus.contains("error-only-needle"));
        assert_eq!(corpus.matches("shared-error-needle").count(), 1);
        assert!(corpus.contains("stdout-part"));
        assert!(corpus.contains("distinct-error-part"));
    }
}
