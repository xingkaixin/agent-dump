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

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn chat(records: &[Value]) -> Chat {
        let lines: Vec<_> = records.iter().map(Value::to_string).collect();
        parse(&lines.join("\n"), || panic!("unexpected mtime"))
            .unwrap()
            .unwrap()
    }

    #[test]
    fn jsonl_updates_replay_into_messages_tools_and_usage() {
        let thinking = json!({
            "id": "g1",
            "timestamp": "2026-10-01T10:00:02.000Z",
            "type": "gemini",
            "content": "",
            "thoughts": [{
                "subject": "Reading",
                "description": "Open the file first.",
            }],
            "tokens": null,
            "model": "gemini-2.5-pro",
        });
        let mut counted = thinking.clone();
        counted["tokens"] = json!({
            "input": 1000,
            "output": 50,
            "cached": 400,
            "thoughts": 30,
            "tool": 10,
            "total": 1090,
        });
        let mut called = counted.clone();
        called["toolCalls"] = json!([
            {
                "id": "call-read",
                "name": "read_file",
                "args": {"file_path": "src/main.rs"},
                "status": "success",
                "result": [
                    {"functionResponse": {
                        "id": "call-read",
                        "name": "read_file",
                        "response": {"output": "fn main() {}"},
                    }},
                    {"functionResponse": {
                        "id": "call-shell",
                        "name": "run_shell_command",
                        "response": {"output": "sibling"},
                    }}
                ]
            },
            {
                "id": "call-shell",
                "name": "run_shell_command",
                "args": {"command": "cargo test"},
                "status": "error",
                "result": null
            }
        ]);
        let chat = chat(&[
            json!({
                "sessionId": "abcd1234-0000",
                "projectHash": "hash",
                "startTime": "2026-10-01T10:00:00.000Z",
                "lastUpdated": "2026-10-01T10:00:00.000Z",
            }),
            json!({
                "id": "u1",
                "timestamp": "2026-10-01T10:00:01.000Z",
                "type": "user",
                "content": [{"text": "Explain @src/main.rs\n--- Content ---"}],
                "displayContent": [{"text": "Explain @src/main.rs"}],
            }),
            thinking,
            counted,
            called,
            json!({"$patch": {"updates": [{
                "id": "g1",
                "toolCalls": [{
                    "id": "call-shell",
                    "result": [{"functionResponse": {
                        "id": "call-shell",
                        "name": "run_shell_command",
                        "response": {"error": "exit 1"},
                    }}],
                }],
            }]}}),
            json!({
                "id": "u2",
                "timestamp": "2026-10-01T10:00:04.000Z",
                "type": "user",
                "content": [{"functionResponse": {
                    "id": "call-read",
                    "name": "read_file",
                    "response": {"output": "fn main() {}"},
                }}],
            }),
            json!({
                "id": "g2",
                "timestamp": "2026-10-01T10:00:05.000Z",
                "type": "gemini",
                "model": "gemini-2.5-pro",
                "content": [
                    {"text": "Plan", "thought": true},
                    {"text": " more", "thought": true},
                    {"text": "The file is empty."},
                    {"functionCall": {
                        "id": "call-ls",
                        "name": "list_directory",
                        "args": {"dir_path": "."},
                    }},
                ],
                "tokens": {
                    "input": 2000,
                    "output": 20,
                    "cached": 1500,
                    "thoughts": 0,
                    "tool": 0,
                },
            }),
            json!({
                "id": "u3",
                "timestamp": "2026-10-01T10:00:06.000Z",
                "type": "user",
                "content": [{"functionResponse": {
                    "id": "call-ls",
                    "name": "list_directory",
                    "response": {"output": "src/"},
                }}],
            }),
            json!({"id":"g3","type":"gemini","content":"Rewound answer"}),
            json!({"$rewindTo":"g3"}),
            json!({"id":"g4","type":"gemini","content":"Removed answer"}),
            json!({"$patch":{"removeIds":["g4"]}}),
            json!({"id":"u4","type":"user","content":"<session_context>cwd</session_context>"}),
            json!({"$set": {
                "summary": "Explain the main file",
                "lastUpdated": "2026-10-01T10:00:10.000Z",
            }}),
        ]);
        assert_eq!(chat.id, "abcd1234-0000");
        assert_eq!(chat.title.as_deref(), Some("Explain the main file"));
        assert_eq!(chat.updated, time(&json!("2026-10-01T10:00:10Z")).unwrap());
        assert_eq!(chat.model.as_deref(), Some("gemini-2.5-pro"));
        let ids: Vec<_> = chat.messages.iter().map(|m| m.id.as_str()).collect();
        assert_eq!(ids, ["u1", "g1", "g2", "u4"]);
        assert!(chat.messages[3].inferred_time);
        assert!(matches!(
            &chat.messages[0].parts[0],
            Part::Text(part) if part.text == "Explain @src/main.rs"
        ));
        let parts = |index: usize| {
            let parts = serde_json::to_value(&chat.messages[index].parts);
            let mut parts = parts.unwrap();
            for part in parts.as_array_mut().unwrap() {
                part.as_object_mut().unwrap().remove("time_created");
            }
            parts
        };
        let tool = |id: &str, name: &str, state: Value| {
            json!({
                "type": "tool",
                "tool": name,
                "callID": id,
                "title": name,
                "state": state,
            })
        };
        assert_eq!(
            parts(1),
            json!([
                {"type":"reasoning","text":"**Reading** Open the file first."},
                tool(
                    "call-read",
                    "read_file",
                    json!({
                        "status": "completed",
                        "input": {"file_path": "src/main.rs"},
                        "output": "fn main() {}",
                        "error": null,
                    }),
                ),
                tool(
                    "call-shell",
                    "run_shell_command",
                    json!({
                        "status": "error",
                        "input": {"command": "cargo test"},
                        "output": null,
                        "error": "exit 1",
                    }),
                ),
            ])
        );
        assert_eq!(
            parts(2),
            json!([
                {"type":"reasoning","text":"Plan more"},
                {"type":"text","text":"The file is empty."},
                tool(
                    "call-ls",
                    "list_directory",
                    json!({
                        "status": "completed",
                        "input": {"dir_path": "."},
                        "output": "src/",
                        "error": null,
                    }),
                ),
            ])
        );
        assert_eq!(
            Value::Object(chat.messages[1].tokens.clone()),
            json!({"input":1010,"output":50,"reasoning":30,"cache":{"read":400}})
        );
        assert_eq!((chat.input, chat.output), (3010, 100));
    }

    #[test]
    fn legacy_json_snapshot_and_missing_session_id() {
        let snapshot = json!({
            "sessionId":"legacy01",
            "projectHash":"0123abcd",
            "messages":[
                {
                    "id": "a",
                    "timestamp": "2025-09-18T02:45:01.000Z",
                    "type": "user",
                    "content": "<session_context>cwd</session_context>"
                },
                {
                    "id": "b",
                    "timestamp": "2025-09-18T02:45:02.000Z",
                    "type": "user",
                    "content": "Old question"
                },
                {
                    "id": "c",
                    "timestamp": "2025-09-18T02:45:03.000Z",
                    "type": "gemini",
                    "content": "",
                    "tokens": {"input": 0, "output": 0}
                }
            ]
        });
        let chat =
            parse(&serde_json::to_string_pretty(&snapshot).unwrap(), || {
                panic!("unexpected mtime")
            })
            .unwrap()
            .unwrap();
        assert_eq!(chat.title.as_deref(), Some("Old question"));
        assert_eq!(chat.created, time(&json!("2025-09-18T02:45:01Z")).unwrap());
        assert_eq!(chat.messages.len(), 2);
        assert!(
            parse("{\"truncated\":", || unreachable!())
                .unwrap()
                .is_none()
        );
    }
}
