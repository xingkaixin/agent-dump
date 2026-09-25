use crate::compat::value::{field, text, truthy};
use crate::providers::contract::RecoverableDiagnostic;
use crate::providers::pi::{datetime, session_name};
use crate::session::{
    ImagePart, Message, Part, Session, SessionData, Stats, TextPart, ToolPart,
};
use serde_json::{Value, json};

pub fn read(
    session: &Session,
    diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
) -> crate::Result<SessionData> {
    let mut messages = Vec::new();
    let mut stats = Stats {
        total_tokens: Some(0.into()),
        ..Stats::default()
    };
    let mut title = session.title.clone();
    let mut sequence = 0;
    let mut directory = session.source_metadata["cwd"].clone();
    let mut version = session.version.clone();
    crate::providers::jsonl::scan(
        &session.source_path,
        diagnostics,
        |record, diagnostics| {
            sequence += 1;
            if sequence == 1 {
                if !truthy(&directory) {
                    directory =
                        record.get("cwd").cloned().unwrap_or_else(|| "".into());
                }
                if !truthy(&version) {
                    version = record["version"].clone();
                }
            }
            if let Some(name) = session_name(&record) {
                title = name;
            }
            let result = (|| -> crate::Result<()> {
                if let Some(message) = convert(&record, sequence)? {
                    messages.push(message);
                }
                accumulate(&mut stats, &record)
            })();
            if let Err(error) = result {
                diagnostics(RecoverableDiagnostic::PiRecordConvertFailed(
                    error.to_string(),
                ))?;
            }
            Ok(())
        },
    )?;
    stats.message_count = messages.len();
    let mut data = session.payload(messages, stats);
    data.title = title;
    data.directory = directory;
    data.version = version;
    Ok(data)
}

fn accumulate(stats: &mut Stats, record: &Value) -> crate::Result<()> {
    let usage = &record["message"]["usage"];
    if record["type"] != "message" || !usage.is_object() {
        return Ok(());
    }
    stats.add_tokens(&usage["input"], &usage["output"])?;
    crate::compat::value::add_integer(
        stats.total_tokens.as_mut().unwrap(),
        &usage["totalTokens"],
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
        stats.total_cost = crate::compat::json::float(
            crate::compat::json::nonfinite(&stats.total_cost)
                .or_else(|| stats.total_cost.as_f64())
                .unwrap_or(0.0)
                + cost,
        );
    }
    Ok(())
}

fn timestamp_ms(value: &Value) -> crate::Result<Option<i64>> {
    if let Some(text) = value.as_str()
        && let Ok(pieces) =
            jiff::fmt::temporal::DateTimeParser::new().parse_pieces(text.trim())
    {
        if pieces.date().year() < 1 {
            return Ok(None);
        }
        if let Some(offset) = pieces.to_numeric_offset() {
            let local = pieces
                .date()
                .to_datetime(pieces.time().unwrap_or(jiff::civil::Time::MIN));
            // Python's astimezone rejects UTC dates outside years 1..=9999.
            if local
                .checked_sub(jiff::SignedDuration::from_secs(i64::from(
                    offset.seconds(),
                )))
                .map_or(true, |utc| utc.year() < 1)
            {
                return Err("date value out of range".into());
            }
        }
    }
    Ok(datetime(value)
        .map(crate::session::timestamp::Timestamp::as_millisecond))
}

fn convert(record: &Value, sequence: usize) -> crate::Result<Option<Message>> {
    let raw_id = field(record, "id").trim().to_owned();
    let id = if raw_id.is_empty() {
        format!("pi-{sequence}")
    } else {
        raw_id.clone()
    };
    let timestamp = timestamp_ms(&record["timestamp"])?.unwrap_or(0);
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
            (!parts.is_empty())
                .then(|| Message::new(id, "custom", timestamp, parts))
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

fn agent_message(
    source: &Value,
    id: String,
    entry_time: i64,
) -> crate::Result<Option<Message>> {
    let role = field(source, "role");
    let role = role.trim();
    let time = timestamp_ms(&source["timestamp"])?
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
            .map_or_else(|| "tool".into(), crate::compat::value::string);
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
        let output =
            serde_json::to_value(content_parts(&source["content"], time))?;
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
    message.model =
        source["model"].is_string().then(|| source["model"].clone());
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
                let text =
                    field(item, if reasoning { "thinking" } else { "text" })
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

fn tool(
    name: String,
    call_id: String,
    arguments: Value,
    output: Value,
    time: i64,
) -> Part {
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
