use crate::session::{Message, Part, SessionData, ToolPart};
use crate::value::{field, parsed_string, string};
use regex::Regex;
use serde_json::{Value, json};
use std::collections::HashMap;
use std::sync::LazyLock;

static CONTEXT_BLOCK: LazyLock<Regex> = LazyLock::new(|| {
    let tags = [
        "instructions",
        "skills_instructions",
        "apps_instructions",
        "plugins_instructions",
        "recommended_plugins",
        "environment_context",
        "permissions instructions",
        "collaboration_mode",
        "multi_agent_mode",
    ];
    let blocks = tags
        .iter()
        .map(|tag| format!("<{tag}>.*?</{tag}>"))
        .collect::<Vec<_>>()
        .join("|");
    Regex::new(&format!(r"(?is)\A(?:# AGENTS\.md instructions for [^\r\n]+\r?\n(?:[ \t]*\r?\n)*)?(?:{blocks})(?:[ \t]*\r?\n)*")).unwrap()
});

pub fn inner_tag<'a>(text: &'a str, tag: &str) -> Option<&'a str> {
    let start = format!("<{tag}>");
    let end = format!("</{tag}>");
    let rest = text.split_once(&start)?.1;
    Some(rest.split_once(&end)?.0.trim())
}

pub fn injected_context(content: &Value) -> bool {
    let Some(items) = content.as_array().filter(|items| !items.is_empty()) else {
        return false;
    };
    if items
        .iter()
        .any(|item| item["type"] != "input_text" || !item["text"].is_string())
    {
        return false;
    }
    let text = items
        .iter()
        .map(|item| item["text"].as_str().unwrap())
        .collect::<Vec<_>>()
        .join("\n\n");
    let mut rest = text.trim_start_matches(['\r', '\n']).trim_end();
    if rest.is_empty() {
        return false;
    }
    while !rest.is_empty() {
        let Some(matched) = CONTEXT_BLOCK.find(rest) else {
            return false;
        };
        rest = &rest[matched.end()..];
    }
    true
}

pub fn subagent_notification(
    id: &str,
    timestamp: i64,
    parts: &[Part],
    nicknames: &mut HashMap<String, String>,
) -> Option<Message> {
    let [Part::Text(part)] = parts else {
        return None;
    };
    let body = part
        .text
        .trim()
        .strip_prefix("<subagent_notification>")?
        .strip_suffix("</subagent_notification>")?;
    let payload: Value = serde_json::from_str(body.trim()).ok()?;
    if !payload.is_object() {
        return None;
    }
    let agent_id = field(&payload, "agent_id").trim().to_owned();
    let nickname = field(&payload, "nickname").trim().to_owned();
    let completed = if payload["status"].is_object() {
        field(&payload["status"], "completed").trim().to_owned()
    } else {
        String::new()
    };
    if agent_id.is_empty() || completed.is_empty() {
        return None;
    }
    let nickname = if nickname.is_empty() {
        nicknames.get(&agent_id).cloned().unwrap_or_default()
    } else {
        nickname
    };
    if !nickname.is_empty() {
        nicknames.insert(agent_id.clone(), nickname.clone());
    }
    let mut message = Message::new(
        id.to_owned(),
        "assistant",
        timestamp,
        vec![Part::text(completed, timestamp)],
    );
    message.subagent_id = Some(agent_id);
    message.nickname = (!nickname.is_empty()).then_some(nickname);
    Some(message)
}

pub fn record_subagent_output(
    tool: &mut ToolPart,
    raw: &Value,
    output: &Value,
    nicknames: &mut HashMap<String, String>,
) {
    if tool.tool != "subagent" {
        return;
    }
    let arguments = tool.state.get("arguments").unwrap_or(&Value::Null);
    let prompt = match arguments {
        Value::Object(_) => {
            let message = field(arguments, "message").trim().to_owned();
            if message.is_empty() {
                crate::value::pretty_json(arguments)
            } else {
                message
            }
        }
        Value::String(value) => value.clone(),
        _ => crate::value::pretty_json(arguments),
    };
    tool.state.insert("prompt".into(), prompt.into());
    let Some(parsed) = parsed_string(raw).filter(Value::is_object) else {
        return;
    };
    let agent_id = field(&parsed, "agent_id").trim().to_owned();
    let nickname = field(&parsed, "nickname").trim().to_owned();
    if !agent_id.is_empty() && !nickname.is_empty() {
        nicknames.insert(agent_id.clone(), nickname.clone());
    }
    if !agent_id.is_empty() {
        tool.subagent_id = Some(agent_id);
    }
    if !nickname.is_empty() {
        tool.nickname = Some(nickname);
    }
    tool.state.insert("output".into(), output.clone());
}

pub fn json_payload(data: &SessionData) -> SessionData {
    let mut payload = data.clone();
    let mut skill_index = 0;
    for message in &mut payload.messages {
        if message.role != "user" {
            continue;
        }
        let [Part::Text(part)] = &message.parts[..] else {
            continue;
        };
        let body = part.text.trim();
        if !body.starts_with("<skill>") || !body.ends_with("</skill>") {
            continue;
        }
        let Some(name) = inner_tag(body, "name").filter(|name| !name.is_empty()) else {
            continue;
        };
        let part = Part::Tool(Box::new(ToolPart {
            tool: "skill".into(),
            call_id: format!("skill:{skill_index}"),
            title: "skill".into(),
            state: json!({"status": "completed", "input": {"name": name}, "output": null})
                .as_object()
                .unwrap()
                .clone(),
            time_created: part.time_created,
            nickname: None,
            subagent_id: None,
        }));
        let mut converted = Message::new(
            message.id.clone(),
            "assistant",
            message.time_created,
            vec![part],
        );
        converted.mode = Some("tool".into());
        *message = converted;
        skill_index += 1;
    }
    for message in &mut payload.messages {
        message
            .parts
            .retain(|part| !matches!(part, Part::Tool(tool) if tool.tool == "wait_agent"));
        if message
            .parts
            .iter()
            .all(|part| matches!(part, Part::Tool(_)))
        {
            message.mode = Some("tool".into());
        } else if message.mode.as_deref() == Some("tool") {
            message.mode = None;
        }
    }
    payload
        .messages
        .retain(|message| message.role != "developer" && !message.parts.is_empty());
    payload
}

pub fn output_parts(raw: &Value, timestamp: i64, custom: bool) -> Vec<Part> {
    let parsed = custom.then(|| parsed_string(raw)).flatten();
    let value = match parsed.as_ref() {
        Some(value) if value.is_object() && value.get("output").is_some() => &value["output"],
        Some(value) => value,
        None => raw,
    };
    if value.is_null() {
        return Vec::new();
    }
    let text = match value {
        Value::Object(_) | Value::Array(_) => crate::value::pretty_json(value),
        _ => string(value),
    };
    vec![Part::text(text, timestamp)]
}
