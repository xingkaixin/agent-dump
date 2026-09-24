use crate::kimi_transcript::{arguments, tool_part};
use crate::message_assembly::backfill;
use crate::session::{Message, Part, TextPart, epoch_seconds};
use crate::value::{field, pretty_json, string, text};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::path::Path;

#[derive(Default)]
struct Decoder {
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

    fn record(&mut self, seq: usize, record: &Value) -> crate::Result<()> {
        let message = &record["message"];
        let payload = &message["payload"];
        if !payload.is_object() {
            return Ok(());
        }
        let timestamp = record["timestamp"]
            .as_f64()
            .and_then(epoch_seconds)
            .map_or(0, |time| time.as_millisecond());
        let id = format!("wire-{seq}");
        match text(&message["type"]) {
            "TurnBegin" => {
                if let Some(first) = payload["user_input"]
                    .as_array()
                    .and_then(|items| items.first())
                    .filter(|item| item.is_object())
                {
                    let body = field(first, "text");
                    if !body.trim().is_empty() {
                        self.messages.push(Message::new(
                            id,
                            "user",
                            timestamp,
                            vec![Part::text(body, timestamp)],
                        ));
                    }
                }
                self.current = None;
                self.open_call = None;
            }
            "ContentPart" => {
                let index = self.assistant(id);
                let reasoning = payload["type"] == "think";
                if reasoning || payload["type"] == "text" {
                    let body = field(payload, if reasoning { "think" } else { "text" });
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
                if !function.is_object() || name.is_empty() || call_id.is_empty() {
                    return Ok(());
                }
                let raw = &function["arguments"];
                let normalized = arguments(raw);
                if raw.is_string() && normalized.is_string() {
                    self.buffers.insert(call_id.clone(), text(raw).into());
                }
                let part = tool_part(&name, call_id.clone(), normalized, timestamp);
                self.pending
                    .insert(call_id.clone(), (index, self.messages[index].parts.len()));
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
                if let Ok(arguments) = serde_json::from_str::<Value>(buffer)
                    && let Part::Tool(tool) = &mut self.messages[message].parts[part]
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
                if backfill(&mut self.messages, &self.pending, &call_id, &parts, None)?.is_none()
                    && !parts.is_empty()
                {
                    let mut message = Message::new(id, "tool", 0, parts);
                    message.tool_call_id = (!call_id.is_empty()).then_some(call_id);
                    self.messages.push(message);
                }
            }
            _ => (),
        }
        Ok(())
    }
}

pub fn read(path: &Path) -> crate::Result<Vec<Message>> {
    let mut decoder = Decoder::default();
    crate::jsonl::scan_numbered(path, true, |seq, record| decoder.record(seq, &record))?;
    decoder.messages.retain(|message| !message.parts.is_empty());
    Ok(decoder.messages)
}
