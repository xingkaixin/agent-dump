use crate::compat::value::{integer, integer_number, parse_json, text, truthy};
use crate::providers::cursor::{bubbles, composer, model, records};
use crate::providers::text::clean;
use crate::session::{
    Message, Part, PlanPart, Session, SessionData, Stats, parse_timestamp,
};
use rusqlite::Connection;
use serde_json::{Value, json};

pub fn read(
    connection: &Connection,
    session: &Session,
) -> crate::Result<SessionData> {
    let id = text(&session.source_metadata["composer_id"]);
    let composer = composer(connection, id)?.unwrap_or_default();
    let fallback = session.created_at.as_millisecond();
    let mut messages =
        messages(&bubbles(connection, id)?, model(&composer), fallback);
    let mut stats = Stats::default();
    for message in &messages {
        stats
            .add_tokens(&message.tokens["input"], &message.tokens["output"])?;
    }
    for (total, key) in [
        (&mut stats.total_input_tokens, "inputTokenCount"),
        (&mut stats.total_output_tokens, "outputTokenCount"),
    ] {
        if total.as_i64() == Some(0) {
            *total = integer_number(&composer[key]);
        }
    }
    messages.extend(subagents(connection, &composer, fallback)?);
    crate::providers::text::clean_messages(&mut messages);
    stats.message_count = messages.len();
    for (source, target) in [
        ("contextTokensUsed", "context_tokens_used"),
        ("contextTokenLimit", "context_token_limit"),
        ("contextUsagePercent", "context_usage_percent"),
    ] {
        stats.extra.insert(
            target.into(),
            session.source_metadata["usage_data"][source].clone(),
        );
    }
    let mut data = session.payload(messages, stats);
    if session.directory.is_empty() {
        data.directory = Value::Null;
    }
    data.metadata = Some(json!({ "composer_id": id }));
    Ok(data)
}

pub fn messages(
    bubbles: &[(String, Value)],
    model: Option<&str>,
    fallback: i64,
) -> Vec<Message> {
    let mut active = model.map(str::to_owned);
    let mut result = Vec::new();
    for (id, bubble) in bubbles {
        if ["eventType", "kind", "subtype", "name"]
            .iter()
            .any(|field| internal(&bubble[field]))
        {
            continue;
        }
        let model = text(&bubble["modelInfo"]["modelName"]);
        if !model.is_empty() {
            active = Some(model.to_owned());
        }
        let (time, inferred) =
            bubble_time(bubble).map_or((fallback, true), |time| (time, false));
        let mut parts = Vec::new();
        let body = clean(text(&bubble["text"]));
        if !body.is_empty() {
            parts.push(Part::text(body, time));
        }
        parts.extend(tool(&bubble["toolFormerData"], time));
        if parts.is_empty() {
            continue;
        }
        let role = if bubble["type"].as_f64() == Some(2.0) {
            "assistant"
        } else {
            "user"
        };
        let tool = parts.iter().any(|part| matches!(part, Part::Tool(_)));
        let mut message = Message::new(id.clone(), role, time, parts);
        message.inferred_time = inferred;
        message.agent = Some("cursor".into());
        message.model = active.clone().map(Value::String);
        if role == "assistant" && tool {
            message.mode = Some("tool".into());
        }
        message.tokens = serde_json::Map::from_iter([
            (
                "input".into(),
                integer_number(&bubble["tokenCount"]["inputTokens"]).into(),
            ),
            (
                "output".into(),
                integer_number(&bubble["tokenCount"]["outputTokens"]).into(),
            ),
        ]);
        result.push(message);
    }
    result
}

fn internal(value: &Value) -> bool {
    let mut normalized = String::new();
    let mut separator = false;
    for character in text(value).trim().to_lowercase().chars() {
        if matches!(character, '_' | '-') {
            if !separator {
                normalized.push(' ');
            }
            separator = true;
        } else {
            normalized.push(character);
            separator = false;
        }
    }
    matches!(
        normalized.as_str(),
        "progress"
            | "file history snapshot"
            | "queue operation"
            | "last prompt"
    )
}

fn tool_name(name: &str) -> &str {
    match name {
        "read_file_v2" => "read",
        "edit_file_v2" => "edit",
        "run_terminal_command_v2" => "bash",
        "ripgrep_raw_search" => "grep",
        "glob_file_search" => "glob",
        _ => name,
    }
}

fn tool(data: &Value, time: i64) -> Option<Part> {
    let name = text(&data["name"]);
    if name.is_empty() {
        return None;
    }
    let status = match text(&data["status"]) {
        "completed" => "completed",
        "error" | "failed" => "error",
        _ => "running",
    };
    let params = &data["params"];
    let input = match params.as_str() {
        _ if !truthy(params) => Value::Null,
        Some(raw) => crate::compat::json::from_str(raw)
            .unwrap_or_else(|_| json!({ "_raw": raw })),
        None => params.clone(),
    };
    let output = parse_json(&data["result"]);
    let error = if status == "error" {
        ["error", "message", "stderr"]
            .iter()
            .map(|key| &output[key])
            .find(|value| !value.is_null())
            .unwrap_or(&output)
            .clone()
    } else {
        Value::Null
    };
    if name == "create_plan" {
        let plan = js_string(&input["plan"]);
        if !plan.trim().is_empty() {
            let plan = clean(plan.trim());
            return (!plan.is_empty()).then(|| {
                Part::Plan(PlanPart {
                    input: plan,
                    output: Value::Null,
                    approval_status: if status == "completed" {
                        "success"
                    } else {
                        "fail"
                    }
                    .into(),
                    time_created: time,
                })
            });
        }
    }
    let name = if name == "create_plan" {
        "plan"
    } else {
        tool_name(name)
    };
    Some(Part::tool(
        name,
        text(&data["toolCallId"]),
        json!({"status":status,"input":input,"output":output,"error":error}),
        time,
    ))
}

fn subagents(
    connection: &Connection,
    composer: &Value,
    fallback: i64,
) -> crate::Result<Vec<Message>> {
    let mut result = Vec::new();
    for info in composer["subagentInfos"].as_array().into_iter().flatten() {
        let id = text(&info["id"]);
        if id.is_empty() {
            continue;
        }
        let Some(bubble) = records(
            connection,
            "SELECT key, value FROM cursorDiskKV WHERE key = ?",
            &[&format!("bubble:{id}")],
        )?
        .into_iter()
        .find_map(|(_, value)| value) else {
            continue;
        };
        let nickname = [&info["nickname"], &info["title"]]
            .into_iter()
            .find_map(Value::as_str);
        for chat in bubble["chatMessages"].as_array().into_iter().flatten() {
            let role = match text(&chat["role"]).trim().to_lowercase().as_str()
            {
                "user" => "user",
                "assistant" => "assistant",
                _ => continue,
            };
            let (time, inferred) = ["createdAt", "timestamp"]
                .iter()
                .map(|key| &chat[key])
                .find(|value| value.as_f64().is_some_and(|time| time > 0.0))
                .map_or((fallback, true), |time| (integer(time), false));
            let mut parts = Vec::new();
            let body = clean(text(&chat["text"]));
            if !body.is_empty() {
                parts.push(Part::text(body, time));
            }
            if role == "assistant" {
                parts.extend(
                    chat["actions"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter(|action| {
                            !internal(&action["type"])
                                && !internal(&action["tool"])
                        })
                        .filter_map(|action| action_part(action, time)),
                );
            }
            if parts.is_empty() {
                continue;
            }
            let mut message = Message::new(
                format!("subagent:{id}:{}", result.len()),
                role,
                time,
                parts,
            );
            message.inferred_time = inferred;
            message.agent = Some("cursor".into());
            message.subagent_id = Some(id.into());
            message.nickname = nickname.map(str::to_owned);
            result.push(message);
        }
    }
    Ok(result)
}

fn action_part(action: &Value, time: i64) -> Option<Part> {
    let tool = text(&action["tool"]);
    let terminal = tool == "run_terminal_command_v2";
    if !terminal && (tool.is_empty() || action["type"] != "tool") {
        return None;
    }
    let state = &action["state"];
    let input = state
        .get("input")
        .or_else(|| state.get("arguments"))
        .or_else(|| action.get("input"))
        .cloned()
        .unwrap_or_default();
    let output = state
        .get("output")
        .or_else(|| state.get("result"))
        .cloned()
        .or_else(|| {
            action.get("output").map(|value| {
                let parts = output_parts(value, 0);
                if parts.is_empty() {
                    value.clone()
                } else {
                    Value::Array(parts)
                }
            })
        });
    let error = state.get("error").cloned().unwrap_or_default();
    let status = match text(&state["status"]) {
        "running" => "running",
        "completed" | "success" => "completed",
        "error" => "error",
        _ if !error.is_null() => "error",
        _ if output.is_some() => "completed",
        _ => "running",
    };
    let mut metadata = state
        .get("metadata")
        .filter(|value| !value.is_null())
        .or_else(|| state.get("meta"))
        .cloned()
        .unwrap_or_default();
    let extras: serde_json::Map<_, _> = state
        .as_object()
        .into_iter()
        .flatten()
        .filter(|(key, _)| {
            ![
                "status",
                "input",
                "arguments",
                "output",
                "result",
                "error",
                "metadata",
                "meta",
            ]
            .contains(&key.as_str())
        })
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect();
    if !extras.is_empty() {
        let mut merged = metadata.as_object().cloned().unwrap_or_default();
        merged.extend(extras);
        metadata = Value::Object(merged);
    }
    let mut state = json!({
        "status": status,
        "input": input,
        "output": output,
        "error": error,
        "metadata": metadata,
    });
    let (call_id, title) = if terminal {
        let command = js_string(&action["input"]["command"]);
        let description =
            clean(&js_string(&action["input"]["commandDescription"]));
        state["output"] = Value::Array(match action["output"].as_str() {
            Some(text) => {
                vec![json!({"type":"text","text":text,"time_created":time})]
            }
            None => output_parts(&action["output"], time),
        });
        let title = if description.is_empty() {
            let short: Vec<_> = command.encode_utf16().take(60).collect();
            format!("bash: {}", String::from_utf16_lossy(&short))
        } else {
            description
        };
        state["input"] = json!({ "command": command });
        (String::new(), title)
    } else {
        (
            format!(
                "{}:{}",
                text(&action["type"]),
                js_string(&action["input"]["id"])
            ),
            tool_name(tool).to_owned(),
        )
    };
    let mut part = Part::tool(tool_name(tool), &call_id, state, time);
    if let Part::Tool(tool) = &mut part {
        tool.title = title;
    }
    Some(part)
}

fn output_parts(value: &Value, time: i64) -> Vec<Value> {
    let (items, array) = match value {
        Value::Array(items) => (items.as_slice(), true),
        _ => (std::slice::from_ref(value), false),
    };
    items
        .iter()
        .filter_map(|item| {
            let body = match item {
                Value::Null => return None,
                Value::String(text) => text.clone(),
                Value::Object(_) if array => ["text", "content"]
                    .iter()
                    .map(|key| &item[key])
                    .find(|value| !value.is_null())
                    .map(js_string)
                    .unwrap_or_default(),
                _ if array => return None,
                _ => js_string(item),
            };
            let body = clean(&body);
            (!body.is_empty())
                .then(|| json!({"type":"text","text":body,"time_created":time}))
        })
        .collect()
}

// Mirrors JavaScript `String(value)`, which CodeSesh inherited for tool text.
fn js_string(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(text) => text.clone(),
        Value::Object(_) => "[object Object]".into(),
        Value::Array(items) => {
            items.iter().map(js_string).collect::<Vec<_>>().join(",")
        }
        _ => value.to_string(),
    }
}

fn bubble_time(bubble: &Value) -> Option<i64> {
    if let Some(time) = bubble["createdAt"].as_str().and_then(parse_timestamp) {
        return Some(time.as_millisecond());
    }
    ["clientRpcSendTime", "clientSettleTime", "clientEndTime"]
        .iter()
        .map(|name| &bubble["timingInfo"][name])
        .find(|value| crate::providers::desktop::timestamp(value).is_some())
        .map(integer)
}
