use crate::compat::value::{field, integer, pretty_json, string, text};
use crate::providers::kimi::transcript::{arguments, content_text, tool_part};
use crate::session::assembly::backfill;
use crate::session::{Message, Part, TextPart, epoch_seconds};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::path::Path;

pub struct Usage {
    pub input: i64,
    pub output: i64,
    cache_read: i64,
    cache_write: i64,
}

pub fn usage(record: &Value) -> Option<Usage> {
    let message = &record["message"];
    let usage = &message["payload"]["token_usage"];
    if message["type"] != "StatusUpdate" || !usage.is_object() {
        return None;
    }
    let count = |key| integer(&usage[key]);
    let cache_read = count("input_cache_read");
    let cache_write = count("input_cache_creation");
    Some(Usage {
        input: count("input_other")
            .saturating_add(cache_read)
            .saturating_add(cache_write),
        output: count("output"),
        cache_read,
        cache_write,
    })
}

fn add(tokens: &mut serde_json::Map<String, Value>, key: &str, value: i64) {
    let total = tokens.get(key).and_then(Value::as_i64).unwrap_or(0);
    tokens.insert(key.into(), total.saturating_add(value).into());
}

#[derive(Default)]
struct Decoder {
    model: Option<String>,
    messages: Vec<Message>,
    pending: HashMap<String, (usize, usize)>,
    buffers: HashMap<String, String>,
    ignored: HashSet<String>,
    current: Option<usize>,
    open_call: Option<String>,
}

impl Decoder {
    fn assistant(&mut self, id: String) -> usize {
        *self.current.get_or_insert_with(|| {
            let mut message = Message::new(id, "assistant", 0, Vec::new());
            message.agent = Some("kimi".into());
            self.messages.push(message);
            self.messages.len() - 1
        })
    }

    fn usage(&mut self, usage: &Usage) {
        let assistants = || {
            self.messages
                .iter()
                .enumerate()
                .rev()
                .filter(|(_, message)| {
                    message.role == "assistant" && !message.parts.is_empty()
                })
        };
        let Some(index) = assistants()
            .find(|(_, message)| message.tokens.is_empty())
            .or_else(|| {
                assistants().find(|(_, message)| {
                    message.model.as_ref().and_then(Value::as_str)
                        == self.model.as_deref()
                })
            })
            .map(|(index, _)| index)
        else {
            return;
        };
        let message = &mut self.messages[index];
        if message.model.is_none() {
            message.model = self.model.clone().map(Value::String);
        }
        add(&mut message.tokens, "input", usage.input);
        add(&mut message.tokens, "output", usage.output);
        let cache = message
            .tokens
            .entry("cache")
            .or_insert_with(|| Value::Object(serde_json::Map::new()));
        if let Some(cache) = cache.as_object_mut() {
            add(cache, "read", usage.cache_read);
            add(cache, "write", usage.cache_write);
        }
    }

    fn record(&mut self, seq: usize, record: &Value) -> crate::Result<()> {
        if let Some(usage) = usage(record)
            && (usage.input != 0 || usage.output != 0)
        {
            self.usage(&usage);
        }
        let message = &record["message"];
        let payload = &message["payload"];
        if !payload.is_object() {
            return Ok(());
        }
        let timestamp = record["timestamp"]
            .as_f64()
            .and_then(epoch_seconds)
            .map_or(0, crate::session::timestamp::Timestamp::as_millisecond);
        let id = format!("wire-{seq}");
        match text(&message["type"]) {
            "TurnBegin" => {
                let body = content_text(&payload["user_input"]);
                if !body.trim().is_empty() {
                    self.messages.push(Message::new(
                        id,
                        "user",
                        timestamp,
                        vec![Part::text(body, timestamp)],
                    ));
                }
                self.current = None;
                self.open_call = None;
            }
            "ContentPart" => {
                let index = self.assistant(id);
                let reasoning = payload["type"] == "think";
                if reasoning || payload["type"] == "text" {
                    let body = field(
                        payload,
                        if reasoning { "think" } else { "text" },
                    );
                    if !body.trim().is_empty() {
                        self.messages[index].parts.push(if reasoning {
                            Part::Reasoning(TextPart {
                                text: body,
                                time_created: timestamp,
                            })
                        } else {
                            Part::text(body, timestamp)
                        });
                    }
                }
            }
            "ToolCall" => {
                let function = &payload["function"];
                let name = field(function, "name").trim().to_owned();
                let call_id = field(payload, "id").trim().to_owned();
                if name == "SetTodoList" && !call_id.is_empty() {
                    self.ignored.insert(call_id.clone());
                    self.open_call = Some(call_id);
                    return Ok(());
                }
                let index = self.assistant(id);
                if !function.is_object()
                    || name.is_empty()
                    || call_id.is_empty()
                {
                    return Ok(());
                }
                let raw = &function["arguments"];
                let normalized = arguments(raw);
                if raw.is_string() && normalized.is_string() {
                    self.buffers.insert(call_id.clone(), text(raw).into());
                }
                let part =
                    tool_part(&name, call_id.clone(), normalized, timestamp);
                self.pending.insert(
                    call_id.clone(),
                    (index, self.messages[index].parts.len()),
                );
                self.messages[index].parts.push(part);
                self.messages[index].mode = Some("tool".into());
                self.open_call = Some(call_id);
            }
            "ToolCallPart" => {
                let Some(call_id) = self
                    .open_call
                    .as_ref()
                    .filter(|id| !self.ignored.contains(*id))
                else {
                    return Ok(());
                };
                let Some(&(message, part)) = self.pending.get(call_id) else {
                    return Ok(());
                };
                let buffer = self.buffers.entry(call_id.clone()).or_default();
                buffer.push_str(&field(payload, "arguments_part"));
                if let Ok(arguments) = crate::compat::json::from_str(buffer)
                    && let Part::Tool(tool) =
                        &mut self.messages[message].parts[part]
                {
                    tool.state.insert("arguments".into(), arguments);
                    self.buffers.remove(call_id);
                }
            }
            "ToolResult" => {
                let call_id = field(payload, "tool_call_id").trim().to_owned();
                if self.ignored.contains(&call_id) {
                    return Ok(());
                }
                let raw = &payload["return_value"];
                let body = if raw.is_object() || raw.is_array() {
                    pretty_json(raw)
                } else {
                    string(raw)
                };
                let parts = if raw.is_null() || body.trim().is_empty() {
                    Vec::new()
                } else {
                    vec![Part::text(body, 0)]
                };
                if backfill(
                    &mut self.messages,
                    &self.pending,
                    &call_id,
                    &parts,
                    None,
                )?
                .is_none()
                    && !parts.is_empty()
                {
                    let mut message = Message::new(id, "tool", 0, parts);
                    message.tool_call_id =
                        (!call_id.is_empty()).then_some(call_id);
                    self.messages.push(message);
                }
            }
            _ => (),
        }
        Ok(())
    }
}

pub fn read(
    path: &Path,
    model: Option<&str>,
    diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
) -> crate::Result<Vec<Message>> {
    let mut decoder = Decoder {
        model: model.map(str::to_owned),
        ..Decoder::default()
    };
    crate::providers::jsonl::scan_numbered(
        path,
        diagnostics,
        |seq, record, _| decoder.record(seq, &record),
    )?;
    decoder.messages.retain(|message| !message.parts.is_empty());
    Ok(decoder.messages)
}
