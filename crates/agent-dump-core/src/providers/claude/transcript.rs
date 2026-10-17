use crate::compat::value::{field, string, text, truthy};
use crate::providers::contract::{DiagnosticSink, RecoverableDiagnostic};
use crate::providers::text::{clean, clean_messages};
use crate::session::assembly::{AssistantFold, backfill};
use crate::session::{
    ImagePart, Message, Part, Session, SessionData, Stats, TextPart, ToolPart,
    parse_timestamp,
};
use serde_json::{Map, Value, json};
use std::collections::HashMap;

#[derive(Default)]
pub struct Decoder {
    agent: &'static str,
    messages: Vec<Message>,
    pending: HashMap<String, (usize, usize)>,
    assistant_calls: HashMap<String, Vec<String>>,
    requests: HashMap<String, usize>,
    children: HashMap<String, String>,
    current: Option<usize>,
    assistant_fold: AssistantFold,
    latest_text: Option<usize>,
}

fn output_parts(content: &Value, timestamp: i64) -> Vec<Part> {
    let text_part = |value: String| {
        let value = clean(&value);
        (!value.is_empty()).then(|| Part::text(value, timestamp))
    };
    match content {
        Value::Null => vec![],
        Value::Array(items) => items
            .iter()
            .filter_map(|item| match item {
                Value::Object(_)
                    if item["type"] == "image" && !item["source"].is_null() =>
                {
                    image(&item["source"], timestamp)
                }
                Value::Object(_) => text_part(
                    item.get("text")
                        .or_else(|| item.get("content"))
                        .map(string)
                        .unwrap_or_default(),
                ),
                Value::String(value) => text_part(value.clone()),
                _ => None,
            })
            .collect(),
        _ => text_part(string(content)).into_iter().collect(),
    }
}

fn image(source: &Value, timestamp: i64) -> Option<Part> {
    let data = text(&source["data"]);
    let mime_type = text(&source["media_type"]);
    (!data.is_empty() && mime_type.starts_with("image/")).then(|| {
        Part::Image(ImagePart {
            mime_type: Some(mime_type.into()),
            data: data.into(),
            time_created: timestamp,
        })
    })
}

fn user_parts(content: &Value, timestamp: i64) -> Vec<Part> {
    match content {
        Value::String(_) => output_parts(content, timestamp),
        Value::Array(items) => items
            .iter()
            .filter_map(|item| {
                let text = match item {
                    Value::Object(_) if item["type"] != "tool_result" => {
                        field(item, "text")
                    }
                    Value::String(value) => value.clone(),
                    _ => return None,
                };
                (!text.trim().is_empty()).then(|| Part::text(text, timestamp))
            })
            .collect(),
        _ => vec![],
    }
}

fn apply_model(message: &mut Message, source: &Value) {
    if truthy(&source["model"])
        && message.model.as_ref().is_none_or(|value| !truthy(value))
    {
        message.model = Some(source["model"].clone());
    }
}

impl Decoder {
    pub fn new(agent: &'static str, children: HashMap<String, String>) -> Self {
        Self {
            agent,
            children,
            ..Self::default()
        }
    }

    pub const fn reset(&mut self) {
        self.current = None;
        self.latest_text = None;
    }

    fn push(
        &mut self,
        id: &str,
        source: &Value,
        timestamp: i64,
        part: Part,
    ) -> usize {
        let tool = matches!(part, Part::Tool(_));
        let text = matches!(part, Part::Text(_));
        let mut parts = vec![part];
        let target = if tool {
            let target = self.latest_text.or(self.current);
            if let Some(index) = target {
                self.messages[index].parts.append(&mut parts);
            }
            target
        } else {
            self.assistant_fold.fold(
                &mut self.messages,
                self.current,
                &mut parts,
                !text,
            )
        };
        let index = target.unwrap_or_else(|| {
            let mut message =
                Message::new(id.to_owned(), "assistant", timestamp, parts);
            message.agent = Some(self.agent.into());
            if tool {
                message.mode = Some("tool".into());
            }
            self.messages.push(message);
            self.messages.len() - 1
        });
        apply_model(&mut self.messages[index], source);
        self.current = Some(index);
        if text {
            self.latest_text = Some(index);
        }
        index
    }

    fn assistant(&mut self, record: &Value, source: &Value, timestamp: i64) {
        let id = field(record, "uuid");
        let key = Some(text(&record["requestId"]).trim())
            .filter(|key| !key.is_empty())
            .unwrap_or_else(|| text(&record["uuid"]).trim())
            .to_owned();
        let usage = source["usage"].as_object().filter(|_| !key.is_empty());
        let mut usage_index =
            usage.and_then(|_| self.requests.get(&key).copied());
        if usage.is_some() && usage_index.is_none() {
            self.reset();
        }
        let mut calls = Vec::new();
        for item in source["content"].as_array().into_iter().flatten() {
            let (part, call_id) = match text(&item["type"]) {
                "text" | "thinking" => {
                    let reasoning = item["type"] == "thinking";
                    let body = clean(&field(
                        item,
                        if reasoning { "thinking" } else { "text" },
                    ));
                    if body.is_empty() {
                        continue;
                    }
                    let part = if reasoning {
                        Part::Reasoning(TextPart {
                            text: body,
                            time_created: timestamp,
                        })
                    } else {
                        Part::text(body, timestamp)
                    };
                    (part, String::new())
                }
                "tool_use" => {
                    let name = field(item, "name");
                    let raw_id = field(item, "id");
                    let call_id = raw_id.trim().to_owned();
                    let input =
                        item.get("input").cloned().unwrap_or_else(|| json!({}));
                    let part = Part::Tool(Box::new(ToolPart {
                        subagent_type: None,
                        tool: name.clone(),
                        call_id: raw_id,
                        title: format!("Tool: {name}"),
                        state: json!({
                            "status": "running",
                            "input": input,
                            "output": null,
                        })
                        .as_object()
                        .unwrap()
                        .clone(),
                        time_created: timestamp,
                        nickname: None,
                        subagent_id: None,
                    }));
                    (part, call_id)
                }
                _ => continue,
            };
            let index = self.push(&id, source, timestamp, part);
            usage_index.get_or_insert(index);
            if !call_id.is_empty() {
                let message = &mut self.messages[index];
                self.pending
                    .insert(call_id.clone(), (index, message.parts.len() - 1));
                if let Some(child) = self.children.get(&call_id) {
                    message.subagent_id = Some(child.clone());
                }
                calls.push(call_id);
            }
        }
        if !calls.is_empty() {
            self.assistant_calls.insert(id.clone(), calls);
        }
        if let Some(usage) = usage {
            let index = usage_index.unwrap_or_else(|| {
                let mut message =
                    Message::new(id, "assistant", timestamp, Vec::new());
                message.agent = Some(self.agent.into());
                self.messages.push(message);
                self.current = Some(self.messages.len() - 1);
                self.messages.len() - 1
            });
            self.requests.insert(key, index);
            let message = &mut self.messages[index];
            message.tokens.clone_from(usage);
            if truthy(&source["model"]) {
                message.model = Some(source["model"].clone());
            }
        }
    }

    fn fallback(
        &mut self,
        id: String,
        timestamp: i64,
        parts: Vec<Part>,
        call_id: Option<String>,
    ) {
        if !parts.is_empty() {
            let mut message = Message::new(id, "tool", timestamp, parts);
            message.tool_call_id = call_id;
            self.messages.push(message);
        }
    }

    fn user(
        &mut self,
        record: &Value,
        source: &Value,
        timestamp: i64,
    ) -> crate::Result<()> {
        let empty = Value::String(String::new());
        let content = source.get("content").unwrap_or(&empty);
        let visible = user_parts(content, timestamp);
        if let Some(items) = content.as_array() {
            let mut updates = Map::new();
            let result = &record["toolUseResult"];
            if let Some(success) = result["success"].as_bool() {
                updates.insert(
                    "status".into(),
                    if success { "completed" } else { "error" }.into(),
                );
            }
            if truthy(&result["commandName"]) {
                updates.insert(
                    "metadata".into(),
                    json!({"commandName": result["commandName"]}),
                );
            }
            for item in
                items.iter().filter(|item| item["type"] == "tool_result")
            {
                let mut call_id = field(item, "tool_use_id").trim().to_owned();
                if call_id.is_empty() {
                    let uuid = field(record, "sourceToolAssistantUUID")
                        .trim()
                        .to_owned();
                    if let Some(calls) = self
                        .assistant_calls
                        .get(&uuid)
                        .filter(|calls| calls.len() == 1)
                    {
                        call_id.clone_from(&calls[0]);
                    }
                }
                let parts = output_parts(&item["content"], timestamp);
                let mut updates = updates.clone();
                if item["is_error"] == true {
                    updates.insert("status".into(), "error".into());
                }
                if let Some(tool) = backfill(
                    &mut self.messages,
                    &self.pending,
                    &call_id,
                    &parts,
                    Some(updates),
                )? {
                    if !parts.is_empty() && tool.state["status"] == "running" {
                        tool.state.insert("status".into(), "completed".into());
                    }
                } else {
                    self.fallback(
                        field(record, "uuid"),
                        timestamp,
                        parts,
                        (!call_id.is_empty()).then_some(call_id),
                    );
                }
            }
        }
        if !visible.is_empty() {
            self.messages.push(Message::new(
                field(record, "uuid"),
                "user",
                timestamp,
                visible,
            ));
        }
        self.reset();
        Ok(())
    }

    fn record(&mut self, record: &Value) -> crate::Result<()> {
        if record["isMeta"] == true {
            return Ok(());
        }
        if !matches!(
            text(&record["type"]),
            "assistant" | "user" | "tool_result"
        ) {
            return Ok(());
        }
        let empty = json!({});
        let source = record.get("message").unwrap_or(&empty);
        if !source.is_object() {
            return Err(format!(
                "'{}' object has no attribute 'get'",
                crate::compat::value::type_name(source)
            )
            .into());
        }
        let timestamp = parse_timestamp(text(&record["timestamp"]))
            .map_or(0, crate::session::timestamp::Timestamp::as_millisecond);
        match text(&record["type"]) {
            "assistant" => self.assistant(record, source, timestamp),
            "user" => self.user(record, source, timestamp)?,
            "tool_result" => {
                self.fallback(
                    field(record, "uuid"),
                    timestamp,
                    output_parts(&source["content"], timestamp),
                    None,
                );
                self.reset();
            }
            _ => (),
        }
        Ok(())
    }

    pub fn convert(
        &mut self,
        record: &Value,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<()> {
        if let Err(error) = self.record(record) {
            diagnostics(RecoverableDiagnostic::MessageConvertFailed(
                error.to_string(),
            ))?;
        }
        Ok(())
    }

    pub fn finish(mut self) -> Vec<Message> {
        clean_messages(&mut self.messages);
        self.messages
    }
}

pub fn read(
    session: &Session,
    children: HashMap<String, String>,
    diagnostics: &mut DiagnosticSink<'_>,
) -> crate::Result<SessionData> {
    let mut decoder = Decoder::new("claude", children);
    crate::providers::jsonl::scan(
        &session.source_path,
        diagnostics,
        |record, diagnostics| decoder.convert(&record, diagnostics),
    )?;
    let messages = decoder.finish();
    let mut stats = Stats {
        message_count: messages.len(),
        ..Stats::default()
    };
    for message in &messages {
        let tokens =
            |key: &str| message.tokens.get(key).unwrap_or(&Value::Null);
        stats.add_tokens(tokens("input_tokens"), tokens("output_tokens"))?;
        for key in ["cache_read_input_tokens", "cache_creation_input_tokens"] {
            stats.add_tokens(tokens(key), &Value::Null)?;
        }
    }
    Ok(session.payload(messages, stats))
}
