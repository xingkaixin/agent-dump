use crate::compat::value::{
    add_integer, float, integer, integer_number, json_object, string, text,
};
use crate::providers::sqlite::connection::rows;
use crate::session::{
    ImagePart, Message, Part, Session, SessionData, Stats, TextPart, ToolPart,
};
use rusqlite::Connection;
use serde_json::{Map, Value, json};
use std::collections::HashSet;

pub fn read(
    connection: &Connection,
    session: &Session,
    row: &Value,
) -> crate::Result<SessionData> {
    let messages = rows(connection, "SELECT id, type, seq, time_created, data FROM session_message WHERE session_id = ? ORDER BY seq ASC", &[&session.id])?
        .iter().map(decode).filter_map(Result::transpose).collect::<crate::Result<Vec<_>>>()?;
    let current = crate::providers::sqlite::build_session(
        row,
        &session.source_path,
        true,
    );
    let mut input = integer_number(&row["tokens_input"]);
    add_integer(&mut input, &row["tokens_cache_read"]);
    add_integer(&mut input, &row["tokens_cache_write"]);
    let mut output = integer_number(&row["tokens_output"]);
    add_integer(&mut output, &row["tokens_reasoning"]);
    let mut total = input.clone();
    add_integer(&mut total, &output.clone().into());
    let stats = Stats {
        total_cost: serde_json::Number::from_f64(float(&row["cost"])).unwrap(),
        total_input_tokens: input,
        total_output_tokens: output,
        message_count: messages.len(),
        total_tokens: Some(total),
        extra: Map::default(),
    };
    let mut payload = current.payload(messages, stats);
    payload.slug = row["slug"].clone();
    payload.directory = row["directory"].clone();
    payload.time_created = integer(&row["time_created"]);
    payload.time_updated = integer(&row["time_updated"]);
    payload.summary_files = row["summary_files"].clone();
    let mut metadata = row.as_object().unwrap().clone();
    for name in ["model", "metadata", "revert", "fork_boundary"] {
        if let Some(value) = metadata.get_mut(name) {
            *value = json_object(value).unwrap_or(Value::Null);
        }
    }
    payload.metadata = Some(metadata.into());
    Ok(payload)
}

fn decode(row: &Value) -> crate::Result<Option<Message>> {
    message(row).map_err(|error| {
        crate::providers::error::ProviderError::invalid(format!(
            "Invalid OpenCode V2 message {}: {error}",
            string(&row["id"])
        ))
        .into()
    })
}

fn message(row: &Value) -> crate::Result<Option<Message>> {
    let data = crate::providers::sqlite::connection::json_cell(&row["data"])?;
    if !data.is_object() {
        return Err("message data must be an object".into());
    }
    let kind = text(&row["type"]);
    if kind == "idle" {
        return Ok(None);
    }
    let role = match kind {
        "user" => "user",
        "assistant" => "assistant",
        "system" | "skill" => "system",
        "shell" => "tool",
        "compaction" => "compaction",
        "synthetic" | "agent-switched" | "model-switched"
        | "location-switched" => "custom",
        _ => "unknown",
    };
    let timestamp = integer(&row["time_created"]);
    let mut message =
        Message::new(string(&row["id"]), role, timestamp, Vec::new());
    message.agent = data["agent"].as_str().map(str::to_owned);
    message.model = data["model"]["id"].as_str().map(std::convert::Into::into);
    message.provider = data["model"]["providerID"].as_str().map(str::to_owned);
    if !data["time"]["completed"].is_null() {
        message.time_completed = integer(&data["time"]["completed"]).into();
    }
    message.tokens = object(&data["tokens"]);
    message.cost = serde_json::Number::from_f64(float(&data["cost"])).unwrap();
    message.entry_type = Some(row["type"].clone());
    let mut metadata = data.as_object().unwrap().clone();
    for name in ["text", "content", "files"] {
        metadata.remove(name);
    }
    metadata.insert("seq".into(), row["seq"].clone());
    message.metadata = Some(metadata);
    let line = |text: String| Part::text(text, timestamp);
    let parts = &mut message.parts;
    match kind {
        "user" => {
            parts.push(line(text(&data["text"]).into()));
            for file in data["files"].as_array().into_iter().flatten() {
                let image = file["mime"]
                    .as_str()
                    .is_some_and(|mime| mime.starts_with("image/"))
                    && file["data"]
                        .as_str()
                        .is_some_and(|data| !data.is_empty());
                parts.push(if image {
                    Part::Image(ImagePart {
                        mime_type: file["mime"].as_str().map(str::to_owned),
                        data: file["data"].clone(),
                        time_created: timestamp,
                    })
                } else {
                    line(attachment(file))
                });
            }
            for mention in ["agents", "skills"]
                .iter()
                .flat_map(|name| data[*name].as_array().into_iter().flatten())
            {
                if let Some(name) =
                    mention["name"].as_str().filter(|name| !name.is_empty())
                {
                    parts.push(line(format!("@{name}")));
                }
            }
        }
        "assistant" => {
            let content = data["content"]
                .as_array()
                .ok_or("content must be an array")?;
            parts.extend(
                content.iter().map(|item| content_part(item, timestamp)),
            );
            let children: HashSet<_> = parts
                .iter()
                .filter_map(|part| match part {
                    Part::Tool(tool) if tool.tool == "subagent" => tool
                        .state
                        .get("metadata")
                        .and_then(|metadata| metadata["sessionID"].as_str())
                        .filter(|id| !id.is_empty()),
                    _ => None,
                })
                .collect();
            let child = (children.len() == 1)
                .then(|| children.into_iter().next().map(str::to_owned))
                .flatten();
            message.subagent_id = child;
        }
        "shell" => parts.push(shell(&data, timestamp)),
        "compaction" => {
            let status =
                data.get("status").map_or_else(|| "undefined".into(), plain);
            let mut sections = vec![format!("[Compaction: {status}]")];
            for name in ["summary", "recent"] {
                if let Some(text) =
                    data[name].as_str().filter(|text| !text.is_empty())
                {
                    sections.push(text.into());
                }
            }
            parts.push(line(sections.join("\n\n")));
        }
        "synthetic" | "system" | "skill" => {
            let label = data["description"]
                .as_str()
                .or_else(|| data["name"].as_str())
                .unwrap_or_default();
            parts.push(line(format!("[{kind}] {label}")));
            parts.push(line(text(&data["text"]).into()));
        }
        _ => parts.push(line(format!("[{kind}] {}", describe(&data)))),
    }
    if !data["error"].is_null() {
        message
            .parts
            .push(line(format!("[Error] {}", describe(&data["error"]))));
    }
    let used = usage(&data);
    let mut messages = vec![message];
    crate::providers::text::clean_messages(&mut messages);
    Ok(messages
        .pop()
        .filter(|message| used || !message.parts.is_empty()))
}

fn content_part(content: &Value, timestamp: i64) -> Part {
    match content["type"].as_str() {
        Some("text") => Part::text(text(&content["text"]).into(), timestamp),
        Some("reasoning") => Part::Reasoning(TextPart {
            text: text(&content["text"]).into(),
            time_created: timestamp,
        }),
        Some("tool") if !text(&content["name"]).is_empty() => {
            tool(content, timestamp)
        }
        _ => Part::text(
            format!("[Unknown content] {}", describe(content)),
            timestamp,
        ),
    }
}

fn tool(content: &Value, timestamp: i64) -> Part {
    let mut state = object(&content["state"]);
    let status = match state.get("status").and_then(Value::as_str) {
        Some("completed") => "completed",
        Some("error") => "error",
        _ => "running",
    };
    state.insert("status".into(), status.into());
    let mut output = match state.remove("content") {
        Some(Value::Array(items)) => items,
        _ => Vec::new(),
    };
    if let Some(error) = state
        .get("error")
        .and_then(|error| error["message"].as_str())
    {
        output.push(json!({"type": "text", "text": error}));
    }
    if !output.is_empty() {
        state.insert("output".into(), output.into());
    }
    let time = object(&content["time"]);
    let created = time.get("created").map_or(timestamp, integer);
    state.insert("time".into(), time.into());
    for field in ["executed", "providerState", "providerResultState"] {
        if let Some(value) = content.get(field) {
            state.insert(field.into(), value.clone());
        }
    }
    let name = text(&content["name"]);
    Part::Tool(Box::new(ToolPart {
        subagent_type: None,
        tool: name.into(),
        call_id: text(&content["id"]).into(),
        title: name.into(),
        state,
        time_created: created,
        nickname: None,
        subagent_id: None,
    }))
}

fn shell(data: &Value, timestamp: i64) -> Part {
    let status = match data["status"].as_str() {
        Some("running") => "running",
        Some("exited")
            if data["exit"].is_null() || float(&data["exit"]) == 0.0 =>
        {
            "completed"
        }
        _ => "error",
    };
    let mut state = Map::from_iter([
        ("status".into(), status.into()),
        (
            "input".into(),
            data.get("command").map_or_else(
                || json!({}),
                |command| json!({"command": command}),
            ),
        ),
        ("output".into(), data["output"]["output"].clone()),
        ("exit".into(), data["exit"].clone()),
        ("truncated".into(), data["output"]["truncated"].clone()),
        ("time".into(), object(&data["time"]).into()),
    ]);
    if status == "error" {
        let exit = if data["exit"].is_null() {
            "unknown".into()
        } else {
            plain(&data["exit"])
        };
        state.insert(
            "error".into(),
            format!("Shell {} (exit: {exit})", plain(&data["status"])).into(),
        );
    }
    let command = text(&data["command"]);
    Part::Tool(Box::new(ToolPart {
        subagent_type: None,
        tool: "shell".into(),
        call_id: text(&data["shellID"]).into(),
        title: command.into(),
        state,
        time_created: timestamp,
        nickname: None,
        subagent_id: None,
    }))
}

fn attachment(file: &Value) -> String {
    let uri = if file["uri"].is_null() {
        &file["source"]["uri"]
    } else {
        &file["uri"]
    };
    let fields: Vec<_> = [&file["name"], &file["mime"], uri]
        .into_iter()
        .filter(|value| !matches!(value, Value::Null | Value::Bool(false)))
        .filter(|value| *value != "")
        .map(plain)
        .collect();
    format!("[Attachment] {}", fields.join(" · "))
}

fn usage(data: &Value) -> bool {
    let tokens = &data["tokens"];
    let positive = |value: &Value| value.as_f64().is_some_and(|n| n > 0.0);
    positive(&data["cost"])
        || [
            &tokens["input"],
            &tokens["output"],
            &tokens["reasoning"],
            &tokens["cache"]["read"],
            &tokens["cache"]["write"],
        ]
        .into_iter()
        .any(positive)
}

fn describe(value: &Value) -> String {
    value.as_str().map_or_else(
        || serde_json::to_string_pretty(value).unwrap_or_default(),
        str::to_owned,
    )
}

fn plain(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(text) => text.clone(),
        value => value.to_string(),
    }
}

fn object(value: &Value) -> Map<String, Value> {
    value.as_object().cloned().unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn convert(kind: &str, data: &Value) -> Option<Value> {
        let row = json!({"id": "m", "type": kind, "seq": 1, "time_created": 5, "data": data.to_string()});
        message(&row)
            .unwrap()
            .map(|message| serde_json::to_value(message).unwrap())
    }

    fn texts(message: &Value) -> Vec<&str> {
        message["parts"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|part| part["text"].as_str())
            .collect()
    }

    #[test]
    fn user_attachments_mentions_and_errors_are_visible() {
        let message = convert(
            "user",
            &json!({
                "text": "Look",
                "files": [
                    {"mime": "image/png", "data": "aGk="},
                    {"name": "a.txt", "mime": "text/plain", "source": {"uri": "file:///a.txt"}},
                    {"mime": "image/png", "data": "", "uri": "https://x/y.png"},
                ],
                "agents": [{"name": "plan"}, {"name": ""}],
                "skills": [{"name": "review"}],
                "error": {"message": "boom"},
            }),
        )
        .unwrap();
        assert_eq!(message["parts"][1]["type"], "image");
        assert_eq!(message["parts"][1]["data"], "aGk=");
        assert_eq!(
            texts(&message),
            [
                "Look",
                "[Attachment] a.txt · text/plain · file:///a.txt",
                "[Attachment] image/png · https://x/y.png",
                "@plan",
                "@review",
                "[Error] {\n  \"message\": \"boom\"\n}",
            ]
        );
        assert!(message["metadata"].get("files").is_none());
    }

    #[test]
    fn assistant_content_is_lenient_and_links_one_subagent() {
        let converted = convert(
            "assistant",
            &json!({"content": [
                {"type": "tool", "id": "a", "name": "bash", "state": {"status": "streaming", "input": "{\"x\":"}},
                {"type": "tool", "id": "b", "name": "subagent", "state": {"status": "completed", "metadata": {"sessionID": "ses_child"}}},
                {"type": "tool", "id": "c"},
                {"type": "text", "text": 7},
                "invalid",
            ]}),
        )
        .unwrap();
        let parts = converted["parts"].as_array().unwrap();
        assert_eq!(parts.len(), 4);
        assert_eq!(parts[0]["state"]["status"], "running");
        assert_eq!(parts[0]["state"]["input"], "{\"x\":");
        assert_eq!(converted["subagent_id"], "ses_child");
        assert_eq!(
            texts(&converted),
            [
                "[Unknown content] {\n  \"type\": \"tool\",\n  \"id\": \"c\"\n}",
                "[Unknown content] invalid",
            ]
        );
        let row = json!({"id": "m", "type": "assistant", "seq": 1, "data": "{\"content\": null}"});
        assert!(message(&row).is_err());
    }

    #[test]
    fn records_get_labels_and_shell_status_follows_exit() {
        let labelled = [
            (
                "system",
                json!({"text": "Body", "name": "rules"}),
                vec!["[system] rules", "Body"],
            ),
            (
                "compaction",
                json!({"summary": "S", "recent": "", "status": "completed"}),
                vec!["[Compaction: completed]\n\nS"],
            ),
            (
                "agent-switched",
                json!({"agent": "plan"}),
                vec!["[agent-switched] {\n  \"agent\": \"plan\"\n}"],
            ),
        ];
        for (kind, data, expected) in labelled {
            assert_eq!(texts(&convert(kind, &data).unwrap()), expected);
        }
        for (data, status, error) in [
            (json!({"status": "exited", "exit": 0}), "completed", None),
            (
                json!({"status": "exited", "exit": 2}),
                "error",
                Some("Shell exited (exit: 2)"),
            ),
            (
                json!({"status": "killed"}),
                "error",
                Some("Shell killed (exit: unknown)"),
            ),
            (json!({"status": "running"}), "running", None),
        ] {
            let state =
                convert("shell", &data).unwrap()["parts"][0]["state"].clone();
            assert_eq!(state["status"], status);
            assert_eq!(state["error"].as_str(), error);
        }
    }

    #[test]
    fn idle_and_empty_records_without_usage_are_dropped() {
        assert!(convert("idle", &json!({})).is_none());
        assert!(convert("user", &json!({"text": 7})).is_none());
        assert!(convert("assistant", &json!({"content": []})).is_none());
        let used = convert(
            "assistant",
            &json!({"content": [], "tokens": {"cache": {"read": 3}}}),
        )
        .unwrap();
        assert!(used["parts"].as_array().unwrap().is_empty());
    }
}
