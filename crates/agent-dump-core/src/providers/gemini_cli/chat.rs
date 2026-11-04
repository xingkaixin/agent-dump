use crate::compat::value::{integer, text};
use crate::providers::kimi::title;
use crate::session::timestamp::Timestamp;
use crate::session::{Message, Part, TextPart};
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};
use std::path::Path;

pub struct Chat {
    pub id: String,
    pub title: Option<String>,
    pub created: Timestamp,
    pub updated: Timestamp,
    pub model: Option<String>,
    pub messages: Vec<Message>,
    pub input: i64,
    pub output: i64,
}

#[derive(Default)]
struct Conversation {
    metadata: Map<String, Value>,
    order: Vec<String>,
    messages: HashMap<String, Value>,
}

impl Conversation {
    fn load(contents: &str) -> Self {
        let mut conversation = Self::default();
        for line in contents.lines() {
            if let Ok(Value::Object(record)) = serde_json::from_str(line) {
                conversation.apply(record);
            }
        }
        if !conversation.metadata.contains_key("sessionId")
            && let Ok(Value::Object(record)) = serde_json::from_str(contents)
        {
            conversation = Self::default();
            conversation.merge(record, false);
        }
        conversation
    }

    // Mirrors Gemini CLI's JSONL replay, where a rewind also drops its target.
    fn apply(&mut self, mut record: Map<String, Value>) {
        if let Some(Value::String(target)) = record.get("$rewindTo") {
            let start =
                self.order.iter().position(|id| id == target).unwrap_or(0);
            for id in self.order.drain(start..) {
                self.messages.remove(&id);
            }
        } else if let Some(Value::Object(patch)) = record.get("$patch") {
            self.patch(patch);
            for update in list(patch, "updates") {
                if let Some(update) = update.as_object() {
                    self.patch(update);
                }
            }
            for id in list(patch, "removeIds") {
                if let Some(id) = id.as_str()
                    && self.messages.remove(id).is_some()
                {
                    self.order.retain(|existing| existing != id);
                }
            }
            if let Some(ids) = patch.get("orderIds").and_then(Value::as_array) {
                let mut ordered = Vec::new();
                for id in ids.iter().filter_map(Value::as_str) {
                    if self.messages.contains_key(id) && !ordered.contains(&id)
                    {
                        ordered.push(id);
                    }
                }
                self.order.retain(|id| !ordered.contains(&id.as_str()));
                self.order.extend(ordered.into_iter().map(str::to_owned));
            }
        } else if record.get("id").is_some_and(Value::is_string) {
            self.insert(Value::Object(record));
        } else if let Some(Value::Object(set)) = record.remove("$set") {
            self.merge(set, true);
        } else if record.get("sessionId").is_some_and(Value::is_string)
            && record.get("projectHash").is_some_and(Value::is_string)
        {
            self.merge(record, false);
        }
    }

    fn patch(&mut self, patch: &Map<String, Value>) {
        let Some(message) = patch
            .get("id")
            .and_then(Value::as_str)
            .and_then(|id| self.messages.get_mut(id))
        else {
            return;
        };
        if let Some(content) = patch.get("content") {
            message["content"] = content.clone();
        }
        if message["type"] != "gemini" {
            return;
        }
        let Some(calls) =
            message.get_mut("toolCalls").and_then(Value::as_array_mut)
        else {
            return;
        };
        for update in list(patch, "toolCalls") {
            if let Some(result) = update.get("result")
                && let Some(call) = calls
                    .iter_mut()
                    .find(|call| call.is_object() && call["id"] == update["id"])
            {
                call["result"] = result.clone();
            }
        }
    }

    fn insert(&mut self, message: Value) {
        let Some(id) = message["id"].as_str().map(str::to_owned) else {
            return;
        };
        if self.messages.insert(id.clone(), message).is_none() {
            self.order.push(id);
        }
    }

    fn merge(&mut self, mut record: Map<String, Value>, replace: bool) {
        if let Some(Value::Array(messages)) = record.remove("messages") {
            if replace {
                self.order.clear();
                self.messages.clear();
            }
            for message in messages {
                self.insert(message);
            }
        }
        self.metadata.extend(record);
    }
}

fn array(value: &Value) -> &[Value] {
    value.as_array().map_or(&[], Vec::as_slice)
}

fn list<'a>(map: &'a Map<String, Value>, key: &str) -> &'a [Value] {
    map.get(key).map(array).unwrap_or_default()
}

fn time(value: &Value) -> Option<Timestamp> {
    crate::session::parse_timestamp(value.as_str()?)
}

fn parts(content: &Value) -> &[Value] {
    match content {
        Value::Array(items) => items,
        Value::Null => &[],
        _ => std::slice::from_ref(content),
    }
}

fn part_text(part: &Value) -> Option<&str> {
    part.as_str().or_else(|| part["text"].as_str())
}

fn push_text(parts: &mut Vec<Part>, reasoning: bool, value: &str, time: i64) {
    match (parts.last_mut(), reasoning) {
        (Some(Part::Reasoning(part)), true)
        | (Some(Part::Text(part)), false) => part.text.push_str(value),
        _ => {
            let part = TextPart {
                text: value.into(),
                time_created: time,
            };
            parts.push(if reasoning {
                Part::Reasoning(part)
            } else {
                Part::Text(part)
            });
        }
    }
}

// Some versions copy a whole parallel functionResponse turn into each call's
// result.
fn response(
    call: &Value,
    id: Option<&str>,
    name: &str,
    later: &HashMap<&str, &Value>,
) -> Option<Value> {
    if let Some(output) = call["result"].as_str() {
        return Some(json!({ "output": output }));
    }
    parts(&call["result"])
        .iter()
        .find_map(|part| {
            let response = part.get("functionResponse")?;
            match response["id"].as_str() {
                Some(other) => Some(other) == id,
                None => response["name"].as_str() == Some(name),
            }
            .then(|| response["response"].clone())
        })
        .or_else(|| later.get(id?).map(|response| (*response).clone()))
}

fn tool(call: &Value, time: i64, later: &HashMap<&str, &Value>) -> Part {
    let id = call["id"].as_str().filter(|id| !id.is_empty());
    let name = match text(&call["name"]).trim() {
        "" => "tool",
        name => name,
    };
    let response = response(call, id, name, later);
    let error = response
        .as_ref()
        .map(|response| &response["error"])
        .filter(|error| !error.is_null())
        .cloned();
    let status = match call["status"].as_str() {
        Some("success") => "completed",
        Some("error" | "cancelled") => "error",
        Some(_) => "running",
        None if error.is_some() => "error",
        None if response.is_some() => "completed",
        None => "unknown",
    };
    let output = response
        .filter(|_| error.is_none())
        .map(|response| response.get("output").cloned().unwrap_or(response));
    let input = call
        .get("args")
        .filter(|args| !args.is_null())
        .cloned()
        .unwrap_or_else(|| json!({}));
    Part::tool(
        name,
        id.unwrap_or_default(),
        json!({"status": status, "input": input, "output": output, "error": error}),
        time,
    )
}

fn user(
    raw: &Value,
    id: String,
    time: i64,
    prompt: &mut Option<String>,
) -> Option<Message> {
    let shown = match &raw["displayContent"] {
        Value::Null => &raw["content"],
        display => display,
    };
    let value: String = parts(shown).iter().filter_map(part_text).collect();
    let start = value.trim_start();
    if prompt.is_none()
        && !start.starts_with("<session_context>")
        && !start.starts_with("<hook_context>")
    {
        *prompt = title(&value);
    }
    (!value.trim().is_empty())
        .then(|| Message::new(id, "user", time, vec![Part::text(value, time)]))
}

fn assistant(
    raw: &Value,
    id: String,
    time: i64,
    later: &HashMap<&str, &Value>,
) -> Option<Message> {
    let content = parts(&raw["content"]);
    let mut message_parts = Vec::new();
    if !content.iter().any(|part| part["thought"] == true) {
        let thoughts: Vec<_> = array(&raw["thoughts"])
            .iter()
            .map(|thought| {
                let subject = text(&thought["subject"]);
                let description = text(&thought["description"]);
                if subject.trim().is_empty() {
                    description.to_owned()
                } else {
                    format!("**{subject}** {description}")
                }
            })
            .collect();
        if !thoughts.is_empty() {
            push_text(&mut message_parts, true, &thoughts.join("\n\n"), time);
        }
    }
    let records: Vec<&Value> = array(&raw["toolCalls"]).iter().collect();
    let mut recorded = HashSet::new();
    for part in content {
        if let Some(call) = part.get("functionCall") {
            let record = call["id"].as_str().and_then(|id| {
                records
                    .iter()
                    .position(|record| record["id"].as_str() == Some(id))
            });
            if let Some(index) = record {
                recorded.insert(index);
            }
            let call = record.map_or(call, |index| records[index]);
            message_parts.push(tool(call, time, later));
        } else if let Some(value) = part_text(part) {
            push_text(&mut message_parts, part["thought"] == true, value, time);
        }
    }
    for (index, record) in records.iter().enumerate() {
        if !recorded.contains(&index) {
            message_parts.push(tool(record, time, later));
        }
    }
    let mut message = Message::new(id, "assistant", time, message_parts);
    message.agent = Some("gemini-cli".into());
    message.model = raw["model"]
        .as_str()
        .map(str::trim)
        .filter(|model| !model.is_empty())
        .map(Into::into);
    let used = if let Some(usage) = raw["tokens"].as_object() {
        let count = |key| usage.get(key).map_or(0, integer).max(0);
        // Gemini's input count includes cached tokens; thoughts and tool-use
        // prompts are counted separately.
        let input = count("input").saturating_add(count("tool"));
        let (output, cached, thoughts) =
            (count("output"), count("cached"), count("thoughts"));
        message.tokens.insert("input".into(), input.into());
        message.tokens.insert("output".into(), output.into());
        if thoughts > 0 {
            message.tokens.insert("reasoning".into(), thoughts.into());
        }
        if cached > 0 {
            message
                .tokens
                .insert("cache".into(), json!({ "read": cached }));
        }
        input > 0 || output > 0 || thoughts > 0 || cached > 0
    } else {
        false
    };
    (used || !message.parts.is_empty()).then_some(message)
}

pub fn read(path: &Path) -> crate::Result<Option<Chat>> {
    let bytes = crate::storage::source_io::read(path)?;
    parse(&String::from_utf8_lossy(&bytes), || {
        Timestamp::try_from(path.metadata()?.modified()?)
    })
}

fn parse(
    contents: &str,
    modified: impl FnOnce() -> crate::Result<Timestamp>,
) -> crate::Result<Option<Chat>> {
    let conversation = Conversation::load(contents);
    let meta = &conversation.metadata;
    let Some(id) = meta
        .get("sessionId")
        .and_then(Value::as_str)
        .filter(|id| !id.is_empty())
    else {
        return Ok(None);
    };
    let ordered: Vec<&Value> = conversation
        .order
        .iter()
        .filter_map(|id| conversation.messages.get(id))
        .collect();
    let created = match meta.get("startTime").and_then(time).or_else(|| {
        ordered
            .iter()
            .find_map(|message| time(&message["timestamp"]))
    }) {
        Some(created) => created,
        None => modified()?,
    };
    let mut updated = meta
        .get("lastUpdated")
        .and_then(time)
        .unwrap_or(created)
        .max(created);
    let mut later = HashMap::new();
    for message in ordered.iter().filter(|message| message["type"] == "user") {
        for part in parts(&message["content"]) {
            let response = &part["functionResponse"];
            if let Some(id) = response["id"].as_str() {
                later.entry(id).or_insert_with(|| &response["response"]);
            }
        }
    }
    let mut messages = Vec::new();
    let mut prompt = None;
    for raw in ordered {
        let recorded = time(&raw["timestamp"]);
        let at = recorded.unwrap_or(created);
        updated = updated.max(at);
        let id = text(&raw["id"]).to_owned();
        let millis = at.as_millisecond();
        let message = match text(&raw["type"]) {
            "user" => user(raw, id, millis, &mut prompt),
            "gemini" => assistant(raw, id, millis, &later),
            _ => None,
        };
        if let Some(mut message) = message {
            message.inferred_time = recorded.is_none();
            messages.push(message);
        }
    }
    crate::providers::text::clean_messages(&mut messages);
    if messages.is_empty() {
        return Ok(None);
    }
    let (mut input, mut output) = (0_i64, 0_i64);
    for message in &messages {
        let count = |key| message.tokens.get(key).map_or(0, integer);
        input = input.saturating_add(count("input"));
        output = output
            .saturating_add(count("output"))
            .saturating_add(count("reasoning"));
    }
    let model = messages
        .iter()
        .find_map(|message| message.model.as_ref()?.as_str())
        .map(str::to_owned);
    Ok(Some(Chat {
        id: id.to_owned(),
        title: meta
            .get("summary")
            .and_then(Value::as_str)
            .and_then(title)
            .or(prompt),
        created,
        updated,
        model,
        messages,
        input,
        output,
    }))
}
