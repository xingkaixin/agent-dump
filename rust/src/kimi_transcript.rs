use crate::message_assembly::backfill;
use crate::session::{Message, Part, TextPart, ToolPart};
use crate::value::{field, string, text};
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::path::Path;

pub fn tool_title(name: &str) -> &str {
    match name {
        "ReadFile" => "read",
        "Glob" => "glob",
        "StrReplaceFile" => "edit",
        "Grep" => "grep",
        "WriteFile" => "write",
        "Shell" => "bash",
        _ => name,
    }
}

pub fn arguments(raw: &Value) -> Value {
    raw.as_str()
        .and_then(|value| serde_json::from_str(value).ok())
        .unwrap_or_else(|| raw.clone())
}

pub fn tool_part(name: &str, id: String, arguments: Value, timestamp: i64) -> Part {
    Part::Tool(Box::new(ToolPart {
        subagent_type: None,
        tool: name.into(),
        call_id: id,
        title: tool_title(name).into(),
        state: json!({"arguments": arguments, "output": null})
            .as_object()
            .unwrap()
            .clone(),
        time_created: timestamp,
        nickname: None,
        subagent_id: None,
    }))
}

fn output_parts(content: &Value) -> Vec<Part> {
    let texts = match content {
        Value::Array(items) => items
            .iter()
            .filter_map(|item| {
                if item["type"] == "text" {
                    Some(field(item, "text"))
                } else {
                    item.as_str().map(str::to_owned)
                }
            })
            .collect(),
        Value::Null => Vec::new(),
        _ => vec![string(content)],
    };
    texts
        .into_iter()
        .filter(|text| !text.trim().is_empty())
        .map(|text| Part::text(text, 0))
        .collect()
}

pub fn read(path: &Path, warn: bool) -> crate::Result<Vec<Message>> {
    let mut messages = Vec::new();
    let mut pending = HashMap::new();
    let mut ignored = HashSet::new();
    crate::jsonl::scan_numbered(path, warn, |seq, record| {
        let id = format!("context-{seq}");
        match text(&record["role"]) {
            "user" => {
                let body = field(&record, "content");
                if !body.trim().is_empty() {
                    messages.push(Message::new(id, "user", 0, vec![Part::text(body, 0)]));
                }
            }
            "assistant" => {
                let mut parts = Vec::new();
                if let Some(content) = record["content"].as_array() {
                    for item in content {
                        let reasoning = item["type"] == "think";
                        if !reasoning && item["type"] != "text" {
                            continue;
                        }
                        let body = field(item, if reasoning { "think" } else { "text" });
                        if body.trim().is_empty() {
                            continue;
                        }
                        parts.push(if reasoning {
                            Part::Reasoning(TextPart {
                                text: body,
                                time_created: 0,
                            })
                        } else {
                            Part::text(body, 0)
                        });
                    }
                }
                if let Some(calls) = record["tool_calls"].as_array() {
                    for call in calls {
                        let function = &call["function"];
                        let name = field(function, "name").trim().to_owned();
                        let call_id = field(call, "id").trim().to_owned();
                        if name.is_empty() || call_id.is_empty() {
                            continue;
                        }
                        if name == "SetTodoList" {
                            ignored.insert(call_id);
                            continue;
                        }
                        if call["type"] != "function" || !function.is_object() {
                            continue;
                        }
                        pending.insert(call_id.clone(), (messages.len(), parts.len()));
                        parts.push(tool_part(
                            &name,
                            call_id,
                            arguments(&function["arguments"]),
                            0,
                        ));
                    }
                }
                if !parts.is_empty() {
                    let tools_only = parts.iter().all(|part| matches!(part, Part::Tool(_)));
                    let mut message = Message::new(id, "assistant", 0, parts);
                    message.agent = Some("kimi".into());
                    message.mode = tools_only.then(|| "tool".into());
                    messages.push(message);
                }
            }
            "tool" => {
                let call_id = field(&record, "tool_call_id").trim().to_owned();
                if ignored.contains(&call_id) {
                    return Ok(());
                }
                let parts = output_parts(&record["content"]);
                if backfill(&mut messages, &pending, &call_id, &parts, None)?.is_none()
                    && !parts.is_empty()
                {
                    let mut message = Message::new(id, "tool", 0, parts);
                    message.tool_call_id = (!call_id.is_empty()).then_some(call_id);
                    messages.push(message);
                }
            }
            _ => (),
        }
        Ok(())
    })?;
    Ok(messages)
}
