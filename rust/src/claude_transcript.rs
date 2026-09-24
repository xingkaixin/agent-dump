use crate::message_assembly::{backfill, fold_assistant};
use crate::session::{
    Message, Part, Session, SessionData, Stats, TextPart, ToolPart, parse_timestamp,
};
use crate::value::{field, string, text, truthy};
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};

#[derive(Default)]
struct Decoder {
    messages: Vec<Message>,
    pending: HashMap<String, (usize, usize)>,
    ignored: HashSet<String>,
    assistant_calls: HashMap<String, Vec<String>>,
    current: Option<usize>,
    latest_text: Option<usize>,
}

fn output_parts(content: &Value, timestamp: i64) -> Vec<Part> {
    let texts = match content {
        Value::Null => vec![],
        Value::Array(items) => items
            .iter()
            .filter_map(|item| match item {
                Value::Object(_) => Some(
                    item.get("text")
                        .or_else(|| item.get("content"))
                        .map(string)
                        .unwrap_or_default(),
                ),
                Value::String(value) => Some(value.clone()),
                _ => None,
            })
            .collect(),
        _ => vec![string(content)],
    };
    texts
        .into_iter()
        .filter(|text| !text.trim().is_empty())
        .map(|text| Part::text(text, timestamp))
        .collect()
}

fn user_parts(content: &Value, timestamp: i64) -> Vec<Part> {
    match content {
        Value::String(_) => output_parts(content, timestamp),
        Value::Array(items) => items
            .iter()
            .filter_map(|item| {
                let text = match item {
                    Value::Object(_) if item["type"] != "tool_result" => field(item, "text"),
                    Value::String(value) => value.clone(),
                    _ => return None,
                };
                (!text.trim().is_empty()).then(|| Part::text(text, timestamp))
            })
            .collect(),
        _ => vec![],
    }
}

fn apply_metadata(message: &mut Message, source: &Value) {
    if truthy(&source["model"]) && message.model.as_ref().is_none_or(|value| !truthy(value)) {
        message.model = Some(source["model"].clone());
    }
    if message.tokens.is_empty()
        && let Some(usage) = source["usage"].as_object()
    {
        message.tokens = usage.clone();
    }
}

impl Decoder {
    fn reset(&mut self) {
        self.current = None;
        self.latest_text = None;
    }

    fn assistant_part(
        &mut self,
        id: &str,
        source: &Value,
        timestamp: i64,
        part: Part,
        reasoning: bool,
    ) {
        let mut parts = vec![part];
        let index = fold_assistant(&mut self.messages, self.current, &mut parts, reasoning)
            .unwrap_or_else(|| {
                let mut message = Message::new(id.to_owned(), "assistant", timestamp, parts);
                message.agent = Some("claude".into());
                self.messages.push(message);
                self.messages.len() - 1
            });
        apply_metadata(&mut self.messages[index], source);
        self.current = Some(index);
        if !reasoning {
            self.latest_text = Some(index);
        }
    }

    fn assistant(&mut self, record: &Value, source: &Value, timestamp: i64) {
        let Some(items) = source["content"].as_array() else {
            return;
        };
        let id = field(record, "uuid");
        let mut calls = Vec::new();
        for item in items {
            match text(&item["type"]) {
                "text" | "thinking" => {
                    let reasoning = item["type"] == "thinking";
                    let body = field(item, if reasoning { "thinking" } else { "text" });
                    if body.trim().is_empty() {
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
                    self.assistant_part(&id, source, timestamp, part, reasoning);
                }
                "tool_use" => {
                    let name = field(item, "name");
                    let raw_id = field(item, "id");
                    let call_id = raw_id.trim().to_owned();
                    if name.trim() == "TodoWrite" && !call_id.is_empty() {
                        self.ignored.insert(call_id);
                        continue;
                    }
                    let input = item.get("input").cloned().unwrap_or_else(|| json!({}));
                    let part = Part::Tool(Box::new(ToolPart {
                        subagent_type: None,
                        tool: name.clone(),
                        call_id: raw_id,
                        title: format!("Tool: {name}"),
                        state: json!({"input": input, "output": null})
                            .as_object()
                            .unwrap()
                            .clone(),
                        time_created: timestamp,
                        nickname: None,
                        subagent_id: None,
                    }));
                    let index = if let Some(index) = self.latest_text {
                        self.messages[index].parts.push(part);
                        index
                    } else {
                        let mut message =
                            Message::new(id.clone(), "assistant", timestamp, vec![part]);
                        message.agent = Some("claude".into());
                        message.mode = Some("tool".into());
                        self.messages.push(message);
                        self.messages.len() - 1
                    };
                    apply_metadata(&mut self.messages[index], source);
                    self.current = Some(index);
                    if !call_id.is_empty() {
                        self.pending.insert(
                            call_id.clone(),
                            (index, self.messages[index].parts.len() - 1),
                        );
                        calls.push(call_id);
                    }
                }
                _ => (),
            }
        }
        if !calls.is_empty() {
            self.assistant_calls.insert(id, calls);
        }
    }

    fn fallback(&mut self, id: String, timestamp: i64, parts: Vec<Part>, call_id: Option<String>) {
        if !parts.is_empty() {
            let mut message = Message::new(id, "tool", timestamp, parts);
            message.tool_call_id = call_id;
            self.messages.push(message);
        }
    }

    fn user(&mut self, record: &Value, source: &Value, timestamp: i64) -> crate::Result<()> {
        let content = &source["content"];
        let visible = user_parts(content, timestamp);
        if content.is_string() && visible.is_empty() {
            return Ok(());
        }
        if let Some(items) = content.as_array() {
            let mut updates = Map::new();
            let result = &record["toolUseResult"];
            if let Some(success) = result["success"].as_bool() {
                updates.insert(
                    "status".into(),
                    if success { "success" } else { "error" }.into(),
                );
            }
            if truthy(&result["commandName"]) {
                updates.insert("meta".into(), json!({"commandName": result["commandName"]}));
            }
            for item in items.iter().filter(|item| item["type"] == "tool_result") {
                let mut call_id = field(item, "tool_use_id").trim().to_owned();
                if call_id.is_empty() {
                    let uuid = field(record, "sourceToolAssistantUUID").trim().to_owned();
                    if let Some(calls) = self
                        .assistant_calls
                        .get(&uuid)
                        .filter(|calls| calls.len() == 1)
                    {
                        call_id = calls[0].clone();
                    }
                }
                if self.ignored.contains(&call_id) {
                    continue;
                }
                let parts = output_parts(&item["content"], timestamp);
                if let Some(tool) = backfill(
                    &mut self.messages,
                    &self.pending,
                    &call_id,
                    &parts,
                    Some(updates.clone()),
                )? {
                    if !parts.is_empty() {
                        tool.state.entry("status").or_insert("completed".into());
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
        let source = &record["message"];
        if !source.is_object() {
            return Ok(());
        }
        let timestamp =
            parse_timestamp(text(&record["timestamp"])).map_or(0, |time| time.as_millisecond());
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
}

pub fn read(session: &Session) -> crate::Result<SessionData> {
    let mut decoder = Decoder::default();
    crate::jsonl::scan(&session.source_path, |record| decoder.record(&record))?;
    let mut stats = Stats {
        message_count: decoder.messages.len(),
        ..Stats::default()
    };
    for message in &decoder.messages {
        stats.add_tokens(
            message.tokens.get("input_tokens").unwrap_or(&Value::Null),
            message.tokens.get("output_tokens").unwrap_or(&Value::Null),
        )?;
    }
    Ok(session.payload(decoder.messages, stats))
}
