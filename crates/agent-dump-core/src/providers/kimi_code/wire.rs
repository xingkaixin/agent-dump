use crate::compat::value::{integer, pretty_json, text};
use crate::providers::kimi::transcript::{arguments, content_text, tool_title};
use crate::providers::kimi::wire::Usage;
use crate::providers::kimi::{timestamp, title};
use crate::session::assembly::backfill;
use crate::session::timestamp::Timestamp;
use crate::session::{ImagePart, Message, Part, PlanPart, TextPart, ToolPart};
use serde_json::{Map, Value};
use std::collections::{HashMap, HashSet};
use std::path::Path;

#[derive(Default)]
pub struct Transcript {
    pub messages: Vec<Message>,
    pub prompt: Option<String>,
    pub model: Option<String>,
    pub input: i64,
    pub output: i64,
    provider: Option<String>,
    current: Option<usize>,
    pending: HashMap<String, (usize, usize)>,
    ignored: HashSet<String>,
}

fn tool_name(name: &str) -> &str {
    match name {
        "Read" => "read",
        "Write" => "write",
        "Edit" => "edit",
        "Bash" => "bash",
        "TodoList" => "todo",
        "AskUserQuestion" => "ask",
        "EnterPlanMode" => "plan mode",
        "ExitPlanMode" => "plan approved",
        _ => tool_title(name),
    }
}

fn tool(name: &str, id: &str, input: Option<Value>, time: i64) -> Part {
    Part::Tool(Box::new(ToolPart {
        subagent_type: None,
        tool: name.into(),
        call_id: id.into(),
        title: tool_name(name).into(),
        state: Map::from_iter([
            ("status".into(), "running".into()),
            ("input".into(), input.unwrap_or(Value::Null)),
            ("output".into(), Value::Null),
        ]),
        time_created: time,
        nickname: None,
        subagent_id: None,
    }))
}

fn clean(value: &Value) -> Option<String> {
    let cleaned = crate::providers::text::clean(text(value));
    (!cleaned.is_empty()).then_some(cleaned)
}

fn string(value: &Value) -> Option<String> {
    value.as_str().map(str::to_owned)
}

fn nonempty(value: &Value) -> Option<String> {
    value
        .as_str()
        .filter(|text| !text.is_empty())
        .map(str::to_owned)
}

fn image(value: &Value, time: i64) -> Option<Part> {
    let source = &value["source"];
    let kind = |expected| source["kind"] == expected;
    let url = string(&value["url"])
        .or_else(|| string(&value["imageUrl"]["url"]))
        .or_else(|| kind("url").then(|| string(&source["url"])).flatten());
    let data = string(&value["data"])
        .or_else(|| kind("base64").then(|| string(&source["data"])).flatten());
    let mime_type = string(&value["mime_type"])
        .or_else(|| string(&value["media_type"]))
        .or_else(|| {
            kind("base64")
                .then(|| string(&source["media_type"]))
                .flatten()
        })
        .unwrap_or_else(|| "application/octet-stream".into());
    // ImagePart has no URL field, so a URL image keeps its URL in `data`.
    let data = url
        .filter(|url| !url.is_empty())
        .or_else(|| data.filter(|data| !data.is_empty()))?;
    Some(Part::Image(ImagePart {
        mime_type: Some(mime_type),
        data: data.into(),
        time_created: time,
    }))
}

fn content_parts(content: &Value, time: i64) -> Vec<Part> {
    let items = content
        .as_array()
        .map_or_else(|| std::slice::from_ref(content), Vec::as_slice);
    items
        .iter()
        .filter_map(|item| {
            if item.is_string() {
                return clean(item).map(|body| Part::text(body, time));
            }
            match text(&item["type"]) {
                "text" => {
                    clean(&item["text"]).map(|body| Part::text(body, time))
                }
                "think" => clean(&item["think"]).map(|body| {
                    Part::Reasoning(TextPart {
                        text: body,
                        time_created: time,
                    })
                }),
                "plan" => clean(&item["text"]).map(|body| {
                    Part::Plan(PlanPart {
                        input: body,
                        output: Value::Null,
                        approval_status: if item["approved"] == false {
                            "fail"
                        } else {
                            "success"
                        }
                        .into(),
                        time_created: time,
                    })
                }),
                "image" => image(item, time),
                "image_url" => nonempty(&item["imageUrl"]["url"])
                    .or_else(|| nonempty(&item["url"]))
                    .map(|url| {
                        Part::Image(ImagePart {
                            mime_type: None,
                            data: url.into(),
                            time_created: time,
                        })
                    }),
                _ => None,
            }
        })
        .collect()
}

fn output_parts(output: &Value, time: i64) -> Vec<Part> {
    if output.is_array() || output.is_string() || output["type"] == "text" {
        content_parts(output, time)
    } else if output.is_null() {
        Vec::new()
    } else {
        content_parts(&pretty_json(output).into(), time)
    }
}

impl Transcript {
    fn append(&mut self, id: String, role: &str, time: i64, parts: Vec<Part>) {
        let index = self.messages.len();
        for (position, part) in parts.iter().enumerate() {
            if let Part::Tool(tool) = part {
                self.pending.insert(tool.call_id.clone(), (index, position));
            }
        }
        let mut message = Message::new(id, role, time, parts);
        if role == "assistant" {
            message.agent = Some("kimi-code".into());
            message.model = self.model.clone().map(Value::String);
            message.provider.clone_from(&self.provider);
            message.mode = message
                .parts
                .iter()
                .all(|part| matches!(part, Part::Tool(_)))
                .then(|| "tool".into());
            self.current = Some(index);
        } else if role != "tool" {
            self.current = None;
        }
        self.messages.push(message);
    }

    fn part(&mut self, id: String, time: i64, part: Part) {
        let Some(index) = self.current else {
            self.append(id, "assistant", time, vec![part]);
            return;
        };
        let message = &mut self.messages[index];
        if let Part::Tool(tool) = &part {
            self.pending
                .insert(tool.call_id.clone(), (index, message.parts.len()));
            message.mode = Some("tool".into());
        }
        message.parts.push(part);
        if message.model.is_none() {
            message.model = self.model.clone().map(Value::String);
        }
        if message.provider.is_none() {
            message.provider.clone_from(&self.provider);
        }
    }

    fn result(
        &mut self,
        id: String,
        time: i64,
        call: &str,
        parts: Vec<Part>,
        updates: Map<String, Value>,
    ) -> crate::Result<()> {
        if backfill(
            &mut self.messages,
            &self.pending,
            call,
            &parts,
            Some(updates),
        )?
        .is_none()
            && !parts.is_empty()
        {
            let mut message = Message::new(id, "tool", time, parts);
            message.tool_call_id = (!call.is_empty()).then(|| call.into());
            self.messages.push(message);
        }
        Ok(())
    }

    fn usage(&mut self, record: &Value) {
        let usage = &record["usage"];
        if !usage.is_object() {
            return;
        }
        let cache_read = integer(&usage["inputCacheRead"]);
        let cache_write = integer(&usage["inputCacheCreation"]);
        let usage = Usage {
            input: integer(&usage["inputOther"])
                .saturating_add(cache_read)
                .saturating_add(cache_write),
            output: integer(&usage["output"]),
            cache_read,
            cache_write,
        };
        self.input = self.input.saturating_add(usage.input);
        self.output = self.output.saturating_add(usage.output);
        let model = string(&record["model"]).or_else(|| self.model.clone());
        let assistant = |message: &Message| message.role == "assistant";
        let Some(index) = self
            .messages
            .iter()
            .rposition(|message| {
                assistant(message) && message.tokens.is_empty()
            })
            .or_else(|| {
                self.messages.iter().rposition(|message| {
                    assistant(message)
                        && message.model.as_ref().and_then(Value::as_str)
                            == model.as_deref()
                })
            })
        else {
            return;
        };
        let message = &mut self.messages[index];
        if message.model.is_none() {
            message.model = model.map(Value::String);
        }
        usage.add_to(&mut message.tokens);
    }

    fn calls(&mut self, calls: &Value, time: i64) -> Vec<Part> {
        let mut parts = Vec::new();
        for call in calls.as_array().into_iter().flatten() {
            let function = Some(&call["function"])
                .filter(|function| function.is_object())
                .unwrap_or(call);
            let name = text(&function["name"]).trim();
            let id = text(&call["id"]).trim();
            if name.is_empty() || id.is_empty() {
                continue;
            }
            if name == "SetTodoList" {
                self.ignored.insert(id.into());
                continue;
            }
            let input = function
                .get("arguments")
                .filter(|value| !value.is_null())
                .or_else(|| call.get("arguments"))
                .map(arguments);
            parts.push(tool(name, id, input, time));
        }
        parts
    }

    fn message(
        &mut self,
        id: String,
        time: i64,
        message: &Value,
    ) -> crate::Result<()> {
        let role = text(&message["role"]);
        if role == "user" && self.prompt.is_none() {
            self.prompt = title(&content_text(&message["content"]));
        }
        if role == "tool" {
            let call = text(&message["toolCallId"]).trim();
            if self.ignored.contains(call) {
                return Ok(());
            }
            let parts = output_parts(&message["content"], time);
            let updates =
                Map::from_iter([("status".into(), "completed".into())]);
            return self.result(id, time, call, parts, updates);
        }
        if role != "user" && role != "assistant" {
            return Ok(());
        }
        let mut parts = content_parts(&message["content"], time);
        if role == "assistant" {
            parts.extend(self.calls(&message["toolCalls"], time));
        }
        if !parts.is_empty() {
            self.append(id, role, time, parts);
        }
        Ok(())
    }

    fn event(
        &mut self,
        id: String,
        time: i64,
        event: &Value,
    ) -> crate::Result<()> {
        match text(&event["type"]) {
            "step.begin" => self.current = None,
            "content.part" => {
                for part in content_parts(&event["part"], time) {
                    self.part(id.clone(), time, part);
                }
            }
            "tool.call" => {
                let name = text(&event["name"]).trim();
                let call = text(&event["toolCallId"]).trim();
                if name.is_empty() || call.is_empty() {
                    return Ok(());
                }
                if name == "SetTodoList" {
                    self.ignored.insert(call.into());
                    return Ok(());
                }
                let part = tool(name, call, event.get("args").cloned(), time);
                self.part(id, time, part);
            }
            "tool.result" => {
                let call = text(&event["toolCallId"]).trim();
                if call.is_empty() || self.ignored.contains(call) {
                    return Ok(());
                }
                let result = &event["result"];
                let parts = output_parts(&result["output"], time);
                let status = if result["isError"] == true {
                    "error"
                } else {
                    "completed"
                };
                let mut updates =
                    Map::from_iter([("status".into(), status.into())]);
                if let Some(note) = nonempty(&result["note"]) {
                    updates.insert(
                        "metadata".into(),
                        serde_json::json!({"note": note}),
                    );
                }
                self.result(id, time, call, parts, updates)?;
            }
            _ => {}
        }
        Ok(())
    }

    fn record(&mut self, seq: usize, record: &Value) -> crate::Result<()> {
        let time =
            timestamp(&record["time"]).map_or(0, Timestamp::as_millisecond);
        let id = format!("wire-{seq}");
        match text(&record["type"]) {
            "llm.request" => {
                if let Some(model) = string(&record["model"]) {
                    self.model = Some(model);
                }
                if let Some(provider) = string(&record["provider"]) {
                    self.provider = Some(provider);
                }
            }
            "config.update" => {
                if let Some(model) = string(&record["modelAlias"]) {
                    self.model = Some(model);
                }
            }
            "usage.record" => self.usage(record),
            "context.append_message" => {
                self.message(id, time, &record["message"])?;
            }
            "context.append_loop_event" => {
                self.event(id, time, &record["event"])?;
            }
            "context.apply_compaction" => {
                if let Some(summary) = clean(&record["summary"]) {
                    let parts = vec![Part::text(summary, time)];
                    self.append(id, "compaction", time, parts);
                }
            }
            _ => {}
        }
        Ok(())
    }
}

pub fn read(
    path: &Path,
    diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
) -> crate::Result<Transcript> {
    let mut transcript = Transcript::default();
    crate::providers::jsonl::scan_numbered(
        path,
        diagnostics,
        |seq, record, _| transcript.record(seq, &record),
    )?;
    Ok(transcript)
}
