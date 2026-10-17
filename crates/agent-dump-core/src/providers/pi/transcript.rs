use crate::compat::value::{add_integer, field, integer_number, text, truthy};
use crate::providers::contract::RecoverableDiagnostic;
use crate::providers::pi::{Kind, Titles, datetime};
use crate::session::{
    ImagePart, Message, Part, Session, SessionData, Stats, TextPart, ToolPart,
};
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};

pub struct Transcript {
    pub header: Option<Value>,
    pub title: Option<String>,
    pub messages: Vec<Message>,
}

impl Transcript {
    pub fn new(
        records: Vec<Value>,
        kind: Kind,
        mut failed: impl FnMut(crate::Error) -> crate::Result<()>,
    ) -> crate::Result<Self> {
        let mut header = None;
        let mut titles = Titles::default();
        let mut entries = Vec::new();
        for (sequence, record) in (1_usize..).zip(records) {
            match text(&record["type"]) {
                "session" => {
                    if header.is_none() {
                        header = Some(record);
                    }
                }
                "title" => titles.add(&record),
                _ => entries.push((sequence, record)),
            }
        }
        let mut messages = Vec::new();
        let mut calls = HashMap::new();
        for (sequence, record) in active_branch(entries) {
            titles.add(&record);
            if let Err(error) =
                append(&mut messages, &mut calls, &record, sequence, kind)
            {
                failed(error)?;
            }
        }
        crate::providers::text::clean_messages(&mut messages);
        let title = titles.resolve(header.as_ref().unwrap_or(&Value::Null));
        Ok(Self {
            header,
            title,
            messages,
        })
    }
}

pub fn read(
    session: &Session,
    kind: Kind,
    diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
) -> crate::Result<SessionData> {
    let mut records = Vec::new();
    crate::providers::jsonl::scan(
        &session.source_path,
        diagnostics,
        |record, _| {
            records.push(record);
            Ok(())
        },
    )?;
    let transcript = Transcript::new(records, kind, |error| {
        diagnostics(RecoverableDiagnostic::PiRecordConvertFailed {
            provider: kind.display_name(),
            error: error.to_string(),
        })
    })?;
    let header = transcript.header.unwrap_or_default();
    let mut directory = session.source_metadata["cwd"].clone();
    if !truthy(&directory) {
        directory = header.get("cwd").cloned().unwrap_or_else(|| "".into());
    }
    let mut version = session.version.clone();
    if !truthy(&version) {
        version = header["version"].clone();
    }
    let stats = stats(&transcript.messages)?;
    let mut data = session.payload(transcript.messages, stats);
    data.title = transcript.title.unwrap_or_else(|| session.title.clone());
    data.directory = directory;
    data.version = version;
    Ok(data)
}

fn entry_id(entry: &Value) -> Option<&str> {
    entry["id"].as_str().filter(|id| !id.is_empty())
}

/// Walks `parentId` links back from the last identified entry. Legacy
/// files without entry ids keep every entry in file order.
fn active_branch(mut entries: Vec<(usize, Value)>) -> Vec<(usize, Value)> {
    let Some(leaf) = entries
        .iter()
        .rposition(|(_, entry)| entry_id(entry).is_some())
    else {
        return entries;
    };
    let branch = {
        let index: HashMap<&str, usize> = entries
            .iter()
            .enumerate()
            .filter_map(|(position, (_, entry))| {
                Some((entry_id(entry)?, position))
            })
            .collect();
        let mut branch = vec![leaf];
        let mut seen = HashSet::from([leaf]);
        while let Some(&parent) = branch
            .last()
            .and_then(|current| entries[*current].1["parentId"].as_str())
            .and_then(|parent| index.get(parent))
        {
            if !seen.insert(parent) {
                break;
            }
            branch.push(parent);
        }
        branch
    };
    branch
        .into_iter()
        .rev()
        .map(|position| std::mem::take(&mut entries[position]))
        .collect()
}

fn append(
    messages: &mut Vec<Message>,
    calls: &mut HashMap<String, (usize, usize)>,
    record: &Value,
    sequence: usize,
    kind: Kind,
) -> crate::Result<()> {
    let Some(message) = convert(record, sequence, kind)? else {
        return Ok(());
    };
    if field(&record["message"], "role").trim() == "toolResult"
        && let [Part::Tool(result)] = message.parts.as_slice()
        && let Some((index, position)) = calls.remove(&result.call_id)
        && let Some(Part::Tool(call)) = messages[index].parts.get_mut(position)
    {
        for (key, value) in &result.state {
            if key != "arguments" {
                call.state.insert(key.clone(), value.clone());
            }
        }
        return Ok(());
    }
    if message.role != "tool" {
        for (position, part) in message.parts.iter().enumerate() {
            if let Part::Tool(tool) = part {
                calls.insert(tool.call_id.clone(), (messages.len(), position));
            }
        }
    }
    messages.push(message);
    Ok(())
}

fn stats(messages: &[Message]) -> crate::Result<Stats> {
    let mut stats = Stats {
        message_count: messages.len(),
        ..Stats::default()
    };
    let mut total_tokens = serde_json::Number::from(0);
    let mut total_cost = None;
    for message in messages {
        let tokens = |key| message.tokens.get(key).unwrap_or(&Value::Null);
        stats.add_tokens(tokens("input"), tokens("output"))?;
        add_integer(&mut total_tokens, tokens("total"));
        if message.cost.is_f64() {
            *total_cost.get_or_insert(0.0) +=
                message.cost.as_f64().unwrap_or_default();
        }
    }
    stats.total_tokens = Some(total_tokens);
    if let Some(cost) = total_cost {
        stats.total_cost = crate::compat::json::float(cost);
    }
    Ok(stats)
}

fn usage(message: &mut Message, usage: &Value) {
    let mut input = integer_number(&usage["input"]);
    add_integer(&mut input, &usage["cacheRead"]);
    add_integer(&mut input, &usage["cacheWrite"]);
    message.tokens = Map::from_iter([
        ("input".into(), input.into()),
        ("output".into(), integer_number(&usage["output"]).into()),
        (
            "cache".into(),
            json!({
                "read": integer_number(&usage["cacheRead"]),
                "write": integer_number(&usage["cacheWrite"]),
            }),
        ),
        ("total".into(), integer_number(&usage["totalTokens"]).into()),
    ]);
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
        message.cost = crate::compat::json::float(cost);
    }
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

fn convert(
    record: &Value,
    sequence: usize,
    kind: Kind,
) -> crate::Result<Option<Message>> {
    let raw_id = field(record, "id").trim().to_owned();
    let id = if raw_id.is_empty() {
        format!("{}-{sequence}", kind.agent())
    } else {
        raw_id.clone()
    };
    let timestamp = timestamp_ms(&record["timestamp"])?.unwrap_or(0);
    let message = match text(&record["type"]) {
        "message" if record["message"].is_object() => {
            agent_message(&record["message"], id, timestamp, kind)?
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
        "custom_message" if record["display"] == true => {
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
    kind: Kind,
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
        let exit_code = &source["exitCode"];
        let failed = source["cancelled"] == true
            || !(exit_code.is_null() || exit_code.as_f64() == Some(0.0));
        let metadata = ["exitCode", "cancelled", "truncated", "fullOutputPath"]
            .into_iter()
            .filter_map(|key| Some((key.to_owned(), source.get(key)?.clone())))
            .collect();
        let mut part = tool(
            "bash".into(),
            id.clone(),
            json!({"command": command}),
            serde_json::to_value(output)?,
            time,
        );
        part.state.insert("status".into(), status(failed));
        part.state
            .insert("metadata".into(), Value::Object(metadata));
        let mut message =
            Message::new(id, "tool", time, vec![Part::Tool(part)]);
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
        part.state
            .insert("status".into(), status(source["isError"] == true));
        if let Some(details) =
            source.get("details").filter(|details| !details.is_null())
        {
            part.state.insert("metadata".into(), details.clone());
        }
        let mut message =
            Message::new(id, "tool", time, vec![Part::Tool(part)]);
        message.mode = Some("tool".into());
        return Ok(Some(message));
    }
    if role == "custom" && source["display"] != true {
        return Ok(None);
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
    message.agent = (message.role == "assistant").then(|| kind.agent().into());
    message.mode = tool_only.then(|| "tool".into());
    message.model =
        source["model"].is_string().then(|| source["model"].clone());
    message.provider = source["provider"].as_str().map(str::to_owned);
    if source["usage"].is_object() {
        usage(&mut message, &source["usage"]);
    }
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
                    parts.push(Part::Tool(tool(
                        name,
                        call_id,
                        item["arguments"].clone(),
                        Value::Null,
                        time,
                    )));
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

fn status(failed: bool) -> Value {
    if failed { "error" } else { "completed" }.into()
}

fn tool(
    name: String,
    call_id: String,
    arguments: Value,
    output: Value,
    time: i64,
) -> Box<ToolPart> {
    let arguments = if arguments.is_null() {
        json!({})
    } else {
        arguments
    };
    Box::new(ToolPart {
        subagent_type: None,
        tool: name.clone(),
        call_id,
        title: name,
        state: Map::from_iter([
            ("arguments".into(), arguments),
            ("output".into(), output),
        ]),
        time_created: time,
        nickname: None,
        subagent_id: None,
    })
}
