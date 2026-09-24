use crate::session::{Message, Part, Session, SessionData, Stats, TextPart, ToolPart};
use crate::sqlite::rows;
use crate::value::{float, integer, json_object};
use rusqlite::Connection;
use serde_json::{Map, Value, json};

pub fn read(connection: &Connection, session: &Session, row: Value) -> crate::Result<SessionData> {
    let current = crate::sqlite_provider::build_session(row.clone(), &session.source_path, true);
    let messages = rows(connection, "SELECT id, type, seq, time_created, data FROM session_message WHERE session_id = ? ORDER BY seq ASC", &[&session.id])?
        .iter().map(decode).collect::<crate::Result<Vec<_>>>()?;
    let stats = Stats {
        total_cost: serde_json::Number::from_f64(float(&row["cost"])).unwrap(),
        total_input_tokens: crate::value::integer_number(&row["tokens_input"]),
        total_output_tokens: crate::value::integer_number(&row["tokens_output"]),
        message_count: messages.len(),
        total_tokens: None,
        extra: Default::default(),
    };
    let mut payload = current.payload(messages, stats);
    payload.slug = row["slug"].clone();
    payload.directory = row["directory"].clone();
    payload.time_created = integer(&row["time_created"]);
    payload.time_updated = integer(&row["time_updated"]);
    payload.summary_files = row["summary_files"].clone();
    let mut metadata = row.as_object().unwrap().clone();
    for name in ["model", "metadata", "revert", "fork_boundary"] {
        if let Some(value) = metadata.get_mut(name) {
            *value = json_object(value).unwrap_or(Value::Null);
        }
    }
    payload.metadata = Some(metadata.into());
    Ok(payload)
}

fn decode(row: &Value) -> crate::Result<Message> {
    build_message(row).map_err(|error| {
        format!(
            "Invalid OpenCode V2 message {}: {error}",
            crate::value::string(&row["id"])
        )
        .into()
    })
}

fn build_message(row: &Value) -> crate::Result<Message> {
    let data = json_object(&row["data"]).ok_or("message data must be a JSON object")?;
    let kind = crate::value::text(&row["type"]);
    let role = match kind {
        "user" => "user",
        "assistant" => "assistant",
        "system" | "skill" => "system",
        "shell" => "tool",
        "compaction" => "compaction",
        "synthetic" | "agent-switched" | "model-switched" | "location-switched" | "idle" => {
            "custom"
        }
        _ => "unknown",
    };
    let timestamp = integer(&row["time_created"]);
    let mut message = Message::new(
        crate::value::string(&row["id"]),
        role,
        timestamp,
        Vec::new(),
    );
    message.agent = data["agent"].as_str().map(str::to_owned);
    message.model = data["model"]["id"].as_str().map(|value| value.into());
    message.provider = data["model"]["providerID"].as_str().map(str::to_owned);
    if !data["time"]["completed"].is_null() {
        message.time_completed = integer(&data["time"]["completed"]).into();
    }
    message.tokens = object(&data["tokens"]);
    message.cost = serde_json::Number::from_f64(float(&data["cost"])).unwrap();
    message.entry_type = Some(row["type"].clone());
    let mut metadata = data.as_object().unwrap().clone();
    metadata.remove("text");
    metadata.remove("content");
    metadata.insert("seq".into(), row["seq"].clone());
    match kind {
        "user" | "synthetic" | "system" | "skill" => message
            .parts
            .push(Part::text(required_text(&data, "text")?.into(), timestamp)),
        "assistant" => {
            let mut unmapped = Vec::new();
            for content in objects(&data["content"])? {
                match required_text(content, "type")? {
                    "text" => message.parts.push(Part::text(
                        required_text(content, "text")?.into(),
                        timestamp,
                    )),
                    "reasoning" => message.parts.push(Part::Reasoning(TextPart {
                        text: required_text(content, "text")?.into(),
                        time_created: timestamp,
                    })),
                    "tool" => message.parts.push(tool(content, timestamp)?),
                    _ => unmapped.push(content.clone()),
                }
            }
            if !unmapped.is_empty() {
                metadata.insert("unmapped_content".into(), unmapped.into());
            }
        }
        "shell" => {
            let command = required_text(&data, "command")?;
            message.parts.push(Part::Tool(Box::new(ToolPart {
                subagent_type: None,
                tool: "shell".into(),
                call_id: required_text(&data, "shellID")?.into(),
                title: command.into(),
                state: Map::from_iter([
                    ("status".into(), data["status"].clone()),
                    ("input".into(), json!({"command": command})),
                    ("output".into(), data["output"]["output"].clone()),
                    ("exit".into(), data["exit"].clone()),
                    ("truncated".into(), data["output"]["truncated"].clone()),
                    ("time".into(), object(&data["time"]).into()),
                ]),
                time_created: timestamp,
                nickname: None,
                subagent_id: None,
            })));
        }
        "compaction" => {
            for field in ["summary", "recent"] {
                if data.get(field).is_some() {
                    message
                        .parts
                        .push(Part::text(required_text(&data, field)?.into(), timestamp));
                }
            }
        }
        _ => metadata.extend(data.as_object().unwrap().clone()),
    }
    message.metadata = Some(metadata);
    Ok(message)
}

fn tool(content: &Value, timestamp: i64) -> crate::Result<Part> {
    let mut state = content["state"]
        .as_object()
        .cloned()
        .ok_or("tool state must be an object")?;
    state
        .get("status")
        .and_then(Value::as_str)
        .ok_or("status must be a string")?;
    if !state
        .get("input")
        .is_some_and(|input| input.is_object() || input.is_string())
    {
        return Err("tool input must be an object or streaming string".into());
    }
    let raw = state.remove("content").unwrap_or_else(|| json!([]));
    let mut output = objects(&raw)?.to_vec();
    for item in &output {
        if item["type"] == "text" {
            required_text(item, "text")?;
        } else if item["type"] == "file" {
            required_text(item, "uri")?;
        }
    }
    if let Some(error) = state
        .get("error")
        .and_then(|error| error["message"].as_str())
    {
        output.push(json!({"type": "text", "text": error}));
    }
    if !output.is_empty() {
        state.insert("output".into(), output.into());
    }
    let time = object(&content["time"]);
    let created = time.get("created").map_or(timestamp, integer);
    state.insert("time".into(), time.into());
    for field in ["executed", "providerState", "providerResultState"] {
        if let Some(value) = content.get(field) {
            state.insert(field.into(), value.clone());
        }
    }
    let name = required_text(content, "name")?;
    Ok(Part::Tool(Box::new(ToolPart {
        subagent_type: None,
        tool: name.into(),
        call_id: required_text(content, "id")?.into(),
        title: name.into(),
        state,
        time_created: created,
        nickname: None,
        subagent_id: None,
    })))
}

fn required_text<'a>(data: &'a Value, field: &str) -> crate::Result<&'a str> {
    data[field]
        .as_str()
        .ok_or_else(|| format!("{field} must be a string").into())
}

fn object(value: &Value) -> Map<String, Value> {
    value.as_object().cloned().unwrap_or_default()
}

fn objects(value: &Value) -> crate::Result<&[Value]> {
    value
        .as_array()
        .filter(|items| items.iter().all(Value::is_object))
        .map(Vec::as_slice)
        .ok_or_else(|| "content must be an array of objects".into())
}
