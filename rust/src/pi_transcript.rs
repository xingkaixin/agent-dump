use crate::pi::{datetime, session_name};
use crate::session::{ImagePart, Message, Part, Session, SessionData, Stats, TextPart, ToolPart};
use crate::value::{field, integer, text, truthy};
use serde_json::{Value, json};

pub fn read(
    session: &Session,
    diagnostics: &mut crate::provider::DiagnosticSink<'_>,
) -> crate::Result<SessionData> {
    let mut messages = Vec::new();
    let mut stats = Stats {
        total_tokens: Some(0),
        ..Stats::default()
    };
    let mut title = session.title.clone();
    let mut sequence = 0;
    crate::jsonl::scan(&session.source_path, diagnostics, |record| {
        sequence += 1;
        if let Some(name) = session_name(&record) {
            title = name;
        }
        if let Some(message) = convert(&record, sequence)? {
            messages.push(message);
        }
        accumulate(&mut stats, &record)
    })?;
    stats.message_count = messages.len();
    let mut data = session.payload(messages, stats);
    data.title = title;
    Ok(data)
}

fn accumulate(stats: &mut Stats, record: &Value) -> crate::Result<()> {
    let usage = &record["message"]["usage"];
    if record["type"] != "message" || !usage.is_object() {
        return Ok(());
    }
    stats.add_tokens(&usage["input"], &usage["output"])?;
    stats.total_tokens = Some(
        stats
            .total_tokens
            .unwrap_or(0)
            .checked_add(integer(&usage["totalTokens"]))
            .ok_or("token total is out of range")?,
    );
    if usage["cost"].is_object() {
        let value = &usage["cost"]["total"];
        let cost = value
            .as_f64()
            .or_else(|| {
                value
                    .as_str()
                    .and_then(|text| text.trim().parse::<f64>().ok())
            })
            .filter(|cost| cost.is_finite())
            .unwrap_or(0.0);
        stats.total_cost =
            serde_json::Number::from_f64(stats.total_cost.as_f64().unwrap_or(0.0) + cost)
                .ok_or("cost total is out of range")?;
    }
    Ok(())
}

fn convert(record: &Value, sequence: usize) -> crate::Result<Option<Message>> {
    let raw_id = field(record, "id").trim().to_owned();
    let id = if raw_id.is_empty() {
        format!("pi-{sequence}")
    } else {
        raw_id.clone()
    };
    let timestamp = datetime(&record["timestamp"]).map_or(0, |time| time.as_millisecond());
    let message = match text(&record["type"]) {
        "message" if record["message"].is_object() => {
            agent_message(&record["message"], id, timestamp)?
        }
        "compaction" | "branch_summary" => {
            let summary = field(record, "summary").trim().to_owned();
            (!summary.is_empty()).then(|| {
                Message::new(
                    id,
                    text(&record["type"]),
                    timestamp,
                    vec![Part::text(summary, timestamp)],
                )
            })
        }
        "custom_message" => {
            let parts = content_parts(&record["content"], timestamp);
            (!parts.is_empty()).then(|| Message::new(id, "custom", timestamp, parts))
        }
        _ => None,
    };
    Ok(message.map(|mut message| {
        message.entry_type = Some(record["type"].clone());
        message.entry_id = (!raw_id.is_empty()).then_some(raw_id);
        if record["parentId"].is_null() || record["parentId"].is_string() {
            message.parent_id = Some(record["parentId"].clone());
        }
        message
    }))
}

fn agent_message(source: &Value, id: String, entry_time: i64) -> crate::Result<Option<Message>> {
    let role = field(source, "role");
    let role = role.trim();
    let time = datetime(&source["timestamp"])
        .map(|time| time.as_millisecond())
        .filter(|time| *time != 0)
        .unwrap_or(entry_time);
    if role == "bashExecution" {
        let command = field(source, "command").trim().to_owned();
        let output = field(source, "output");
        if command.is_empty() && output.trim().is_empty() {
            return Ok(None);
        }
        let output = if output.trim().is_empty() {
            Vec::new()
        } else {
            vec![Part::text(output, time)]
        };
        let part = tool(
            "bash".into(),
            id.clone(),
            json!({"command": command}),
            serde_json::to_value(output)?,
            time,
        );
        let mut message = Message::new(id, "tool", time, vec![part]);
        message.mode = Some("tool".into());
        return Ok(Some(message));
    }
    if role == "toolResult" {
        let name = source
            .get("toolName")
            .map(crate::value::string)
            .unwrap_or_else(|| "tool".into());
        let name = if name.trim().is_empty() {
            "tool"
        } else {
            name.trim()
        };
        let call_id = field(source, "toolCallId");
        let call_id = if call_id.trim().is_empty() {
            id.clone()
        } else {
            call_id.trim().into()
        };
        let output = serde_json::to_value(content_parts(&source["content"], time))?;
        let mut part = tool(name.into(), call_id, json!({}), output, time);
        if let Part::Tool(part) = &mut part {
            part.state
                .insert("is_error".into(), truthy(&source["isError"]).into());
        }
        let mut message = Message::new(id, "tool", time, vec![part]);
        message.mode = Some("tool".into());
        return Ok(Some(message));
    }
    let (role, parts) = match role {
        "branchSummary" | "compactionSummary" => {
            let summary = field(source, "summary").trim().to_owned();
            let parts = if summary.is_empty() {
                Vec::new()
            } else {
                vec![Part::text(summary, time)]
            };
            (
                if role == "branchSummary" {
                    "branch_summary"
                } else {
                    "compaction"
                },
                parts,
            )
        }
        _ => (role, content_parts(&source["content"], time)),
    };
    if parts.is_empty() {
        return Ok(None);
    }
    let tool_only = parts.iter().all(|part| matches!(part, Part::Tool(_)));
    let mut message = Message::new(id, role, time, parts);
    message.agent = (message.role == "assistant").then(|| "pi".into());
    message.mode = tool_only.then(|| "tool".into());
    message.model = source["model"].is_string().then(|| source["model"].clone());
    message.provider = source["provider"].as_str().map(str::to_owned);
    Ok(Some(message))
}

fn content_parts(content: &Value, time: i64) -> Vec<Part> {
    if let Some(text) = content.as_str() {
        return if text.trim().is_empty() {
            Vec::new()
        } else {
            vec![Part::text(text.into(), time)]
        };
    }
    let Some(items) = content.as_array() else {
        return Vec::new();
    };
    let mut parts = Vec::new();
    for item in items {
        if let Some(text) = item.as_str() {
            if !text.trim().is_empty() {
                parts.push(Part::text(text.into(), time));
            }
            continue;
        }
        match text(&item["type"]) {
            "text" | "thinking" => {
                let reasoning = item["type"] == "thinking";
                let text = field(item, if reasoning { "thinking" } else { "text" })
                    .trim()
                    .to_owned();
                if !text.is_empty() {
                    parts.push(if reasoning {
                        Part::Reasoning(TextPart {
                            text,
                            time_created: time,
                        })
                    } else {
                        Part::text(text, time)
                    });
                }
            }
            "toolCall" => {
                let name = field(item, "name").trim().to_owned();
                let call_id = field(item, "id").trim().to_owned();
                if !name.is_empty() && !call_id.is_empty() {
                    parts.push(tool(
                        name,
                        call_id,
                        item["arguments"].clone(),
                        Value::Null,
                        time,
                    ));
                }
            }
            "image" => {
                let mime_type = field(item, "mimeType").trim().to_owned();
                parts.push(Part::Image(ImagePart {
                    mime_type: (!mime_type.is_empty()).then_some(mime_type),
                    data: item["data"].clone(),
                    time_created: time,
                }));
            }
            _ => {}
        }
    }
    parts
}

fn tool(name: String, call_id: String, arguments: Value, output: Value, time: i64) -> Part {
    let arguments = if arguments.is_null() {
        json!({})
    } else {
        arguments
    };
    Part::Tool(Box::new(ToolPart {
        subagent_type: None,
        tool: name.clone(),
        call_id,
        title: name,
        state: serde_json::Map::from_iter([
            ("arguments".into(), arguments),
            ("output".into(), output),
        ]),
        time_created: time,
        nickname: None,
        subagent_id: None,
    }))
}
