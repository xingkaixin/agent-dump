use crate::compat::value::{float, integer, json_object, string, text};
use crate::providers::contract::{DiagnosticSink, RecoverableDiagnostic};
use crate::providers::sqlite::Facts;
use crate::providers::sqlite::connection::{each_row, has_column, rows};
use crate::providers::text::clean;
use crate::session::{
    ImagePart, Message, Part, PlanPart, Session, SessionData, Stats, StepPart,
    TextPart, ToolPart, UnknownPart,
};
use rusqlite::{Connection, ToSql};
use serde_json::{Map, Value};
use std::collections::{HashMap, HashSet};

pub fn read(
    connection: &Connection,
    session: &Session,
    descendants: bool,
    diagnostics: &mut DiagnosticSink<'_>,
) -> crate::Result<SessionData> {
    // Non-text payloads must reach record validation instead of aborting SQLite row decoding.
    let records = rows(
        connection,
        "SELECT id, time_created, CASE WHEN typeof(data) = 'text' THEN data END AS data
         FROM message WHERE session_id = ? ORDER BY time_created ASC",
        &[&session.id],
    )?;
    let mut parts_by_id: HashMap<String, Vec<Value>> = HashMap::new();
    for chunk in records.chunks(500) {
        let ids: Vec<_> = chunk.iter().map(|row| string(&row["id"])).collect();
        let parameters: Vec<&dyn ToSql> =
            ids.iter().map(|id| id as &dyn ToSql).collect();
        let placeholders = vec!["?"; ids.len()].join(", ");
        for part in rows(
            connection,
            &format!(
                "SELECT id, message_id, time_created, \
                 CASE WHEN typeof(data) = 'text' THEN data END AS data \
                 FROM part WHERE message_id IN ({placeholders}) \
                 ORDER BY message_id ASC, time_created ASC"
            ),
            &parameters,
        )? {
            parts_by_id
                .entry(string(&part["message_id"]))
                .or_default()
                .push(part);
        }
    }
    let mut messages = Vec::new();
    for row in records {
        let id = string(&row["id"]);
        let Some(data) = json_object(&row["data"]) else {
            diagnostics(RecoverableDiagnostic::MessageDataParseFailed(id))?;
            continue;
        };
        if internal(&data["type"]) {
            continue;
        }
        let mut message = Message::new(
            id.clone(),
            text(&data["role"]),
            integer(&row["time_created"]),
            Vec::new(),
        );
        message.agent = data["agent"].as_str().map(str::to_owned);
        message.mode = data["mode"].as_str().map(str::to_owned);
        message.model = data["modelID"].as_str().map(std::convert::Into::into);
        message.provider = data["providerID"].as_str().map(str::to_owned);
        message.time_completed = data["time"]["completed"].clone();
        message.tokens = object(&data["tokens"]);
        message.cost =
            serde_json::Number::from_f64(float(&data["cost"])).unwrap();
        for row in parts_by_id.remove(&id).unwrap_or_default() {
            let Some(data) = json_object(&row["data"]) else {
                diagnostics(RecoverableDiagnostic::PartDataParseFailed(
                    string(&row["id"]),
                ))?;
                continue;
            };
            message
                .parts
                .extend(part(&data, integer(&row["time_created"])));
        }
        messages.push(message);
    }
    crate::providers::text::clean_messages(&mut messages);
    messages.retain(|message| message.parts.iter().any(visible));
    let mut stats = Stats {
        total_cost: serde_json::Number::from_f64(0.0).unwrap(),
        ..Stats::default()
    };
    for message in &messages {
        add_usage(
            &mut stats,
            message.cost.as_f64().unwrap_or_default(),
            &message.tokens,
        );
    }
    if descendants {
        descendant_usage(connection, &session.id, &mut stats)?;
    }
    stats.message_count = messages.len();
    let row = &session.source_metadata["row"];
    let title = crate::providers::sqlite::display_title(
        row,
        crate::providers::sqlite::user_title(&messages),
    );
    let mut payload = session.payload(messages, stats);
    payload.title = title;
    payload.slug = row["slug"].clone();
    payload.directory = row["directory"].clone();
    payload.summary_files = row["summary_files"].clone();
    Ok(payload)
}

pub fn facts(
    connection: &Connection,
    sessions: &str,
    parameters: &[&dyn ToSql],
) -> crate::Result<HashMap<String, Facts>> {
    struct Entry {
        session: String,
        time: i64,
        user: bool,
        visible: bool,
        title: Option<(i64, String)>,
    }
    let mut entries = Vec::new();
    let mut by_id = HashMap::new();
    each_row(
        connection,
        &format!(
            "SELECT id, session_id, time_created, \
             CASE WHEN typeof(data) = 'text' THEN data END AS data \
             FROM message WHERE session_id IN ({sessions})"
        ),
        parameters,
        |row| {
            if let Some(data) = json_object(&row["data"])
                && !internal(&data["type"])
            {
                by_id.insert(string(&row["id"]), entries.len());
                entries.push(Entry {
                    session: string(&row["session_id"]),
                    time: integer(&row["time_created"]),
                    user: data["role"] == "user",
                    visible: false,
                    title: None,
                });
            }
            Ok(())
        },
    )?;
    each_row(
        connection,
        &format!(
            "SELECT message_id, time_created, \
             CASE WHEN typeof(data) = 'text' THEN data END AS data \
             FROM part WHERE message_id IN \
             (SELECT id FROM message WHERE session_id IN ({sessions}))"
        ),
        parameters,
        |row| {
            let Some(entry) = by_id
                .get(&string(&row["message_id"]))
                .map(|index| &mut entries[*index])
            else {
                return Ok(());
            };
            let time = integer(&row["time_created"]);
            let Some(part) = json_object(&row["data"])
                .and_then(|data| part(&data, time))
                .filter(visible)
            else {
                return Ok(());
            };
            entry.visible = true;
            if entry.user
                && entry.title.as_ref().is_none_or(|(first, _)| time < *first)
                && let Part::Text(text) = &part
                && let Some(title) = crate::providers::sqlite::title(&text.text)
            {
                entry.title = Some((time, title));
            }
            Ok(())
        },
    )?;
    let mut facts: HashMap<String, (Facts, i64)> = HashMap::new();
    for entry in entries.into_iter().filter(|entry| entry.visible) {
        let (facts, first) = facts.entry(entry.session).or_default();
        facts.count += 1;
        if let Some((_, title)) = entry.title
            && (facts.title.is_none() || entry.time < *first)
        {
            facts.title = Some(title);
            *first = entry.time;
        }
    }
    Ok(facts
        .into_iter()
        .map(|(session, (facts, _))| (session, facts))
        .collect())
}

fn internal(kind: &Value) -> bool {
    kind.as_str().is_some_and(|kind| {
        matches!(
            kind.trim().to_lowercase().replace(['_', '-'], " ").as_str(),
            "progress"
                | "file history snapshot"
                | "queue operation"
                | "last prompt"
        )
    })
}

fn visible(part: &Part) -> bool {
    match part {
        Part::Text(part) | Part::Reasoning(part) => {
            !clean(&part.text).is_empty()
        }
        Part::Plan(part) => !clean(&part.input).is_empty(),
        Part::Image(_) | Part::Tool(_) => true,
        Part::StepStart(_) | Part::StepFinish(_) | Part::Unknown(_) => false,
    }
}

fn add_usage(stats: &mut Stats, cost: f64, tokens: &Map<String, Value>) {
    stats.total_cost = crate::compat::json::float(
        crate::compat::json::nonfinite(&stats.total_cost)
            .or_else(|| stats.total_cost.as_f64())
            .unwrap()
            + cost,
    );
    let token = |name: &str| tokens.get(name).unwrap_or(&Value::Null);
    let cache = token("cache");
    for value in [token("input"), &cache["read"], &cache["write"]] {
        crate::compat::value::add_integer(&mut stats.total_input_tokens, value);
    }
    for value in [token("output"), token("reasoning")] {
        crate::compat::value::add_integer(
            &mut stats.total_output_tokens,
            value,
        );
    }
}

fn descendant_usage(
    connection: &Connection,
    id: &str,
    stats: &mut Stats,
) -> crate::Result<()> {
    if !has_column(connection, "session", "parent_id")? {
        return Ok(());
    }
    let mut children: HashMap<String, Vec<String>> = HashMap::new();
    for row in rows(
        connection,
        "SELECT id, parent_id FROM session WHERE parent_id IS NOT NULL",
        &[],
    )? {
        if let Some(parent) = row["parent_id"].as_str() {
            children
                .entry(parent.into())
                .or_default()
                .push(string(&row["id"]));
        }
    }
    let mut seen = HashSet::from([id.to_owned()]);
    let mut pending = children.get(id).cloned().unwrap_or_default();
    let mut descendants = Vec::new();
    while let Some(child) = pending.pop() {
        if seen.insert(child.clone()) {
            pending.extend(children.get(&child).into_iter().flatten().cloned());
            descendants.push(child);
        }
    }
    for chunk in descendants.chunks(500) {
        let parameters: Vec<&dyn ToSql> =
            chunk.iter().map(|id| id as &dyn ToSql).collect();
        let placeholders = vec!["?"; chunk.len()].join(", ");
        each_row(
            connection,
            &format!(
                "SELECT CASE WHEN typeof(data) = 'text' THEN data END AS data
                 FROM message WHERE session_id IN ({placeholders})"
            ),
            &parameters,
            |row| {
                if let Some(data) = json_object(&row["data"])
                    && !internal(&data["type"])
                {
                    add_usage(
                        stats,
                        float(&data["cost"]),
                        &object(&data["tokens"]),
                    );
                }
                Ok(())
            },
        )?;
    }
    Ok(())
}

fn part(data: &Value, time: i64) -> Option<Part> {
    let kind = data["type"].as_str().unwrap_or("unknown");
    Some(match kind {
        "text" => Part::text(text(&data["text"]).into(), time),
        "reasoning" => Part::Reasoning(TextPart {
            text: text(&data["text"]).into(),
            time_created: time,
        }),
        "plan" => {
            let failed = data["approval_status"] == "fail";
            let source = if data["text"].is_null() {
                &data[if failed { "output" } else { "input" }]
            } else {
                &data["text"]
            };
            Part::Plan(PlanPart {
                input: plan_text(source),
                output: data["output"].clone(),
                approval_status: if failed { "fail" } else { "success" }.into(),
                time_created: time,
            })
        }
        "image" => {
            let field = |name: &str| {
                data[name].as_str().filter(|value| !value.is_empty())
            };
            let mime_type = field("mime_type");
            let ((Some(content), Some(_), _) | (_, _, Some(content))) =
                (field("data"), mime_type, field("url"))
            else {
                return None;
            };
            Part::Image(ImagePart {
                mime_type: mime_type.map(str::to_owned),
                data: content.into(),
                time_created: time,
            })
        }
        "tool" => tool(data, time)?,
        "step-start" | "step-finish" => {
            let step = StepPart {
                time_created: time,
                reason: data["reason"].clone(),
                tokens: data["tokens"].clone(),
                cost: data["cost"].clone(),
            };
            if kind == "step-start" {
                Part::StepStart(step)
            } else {
                Part::StepFinish(step)
            }
        }
        _ => Part::Unknown(UnknownPart {
            data: None,
            kind: kind.into(),
            time_created: time,
        }),
    })
}

fn plan_text(value: &Value) -> String {
    if let Some(text) = value.as_str() {
        return text.into();
    }
    ["text", "plan", "content"]
        .iter()
        .find_map(|name| value.get(name))
        .map(plan_text)
        .unwrap_or_default()
}

fn tool(data: &Value, time: i64) -> Option<Part> {
    let title = text(&data["title"]);
    let mut name = text(&data["tool"]).trim();
    if name.is_empty() {
        name = match title.get(..5) {
            Some(prefix) if prefix.eq_ignore_ascii_case("tool:") => &title[5..],
            _ => title,
        }
        .trim();
    }
    if name.is_empty() {
        return None;
    }
    let mut state = data["state"].as_object().cloned().unwrap_or_default();
    let first = |state: &Map<String, Value>, names: [&str; 2]| {
        names
            .iter()
            .find_map(|name| state.get(*name))
            .or_else(|| data.get(names[0]))
            .cloned()
    };
    let input = first(&state, ["input", "arguments"]);
    let output = first(&state, ["output", "result"]);
    let failed = state.get("error").is_some_and(|error| !error.is_null());
    let status = match state.get("status").and_then(Value::as_str) {
        Some("running") => "running",
        Some("error") => "error",
        Some("completed" | "success") => "completed",
        _ if failed => "error",
        _ if output.is_some() => "completed",
        _ => "running",
    };
    state.remove("arguments");
    state.remove("result");
    state.insert("status".into(), status.into());
    for (key, value) in [("input", input), ("output", output)] {
        if let Some(value) = value {
            state.insert(key.into(), value);
        }
    }
    Some(Part::Tool(Box::new(ToolPart {
        subagent_type: None,
        tool: name.into(),
        call_id: text(&data["callID"]).into(),
        title: title.into(),
        state,
        time_created: time,
        nickname: None,
        subagent_id: None,
    })))
}

fn object(value: &Value) -> Map<String, Value> {
    value.as_object().cloned().unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn convert(data: &Value) -> Option<Value> {
        part(data, 1).map(|part| serde_json::to_value(part).unwrap())
    }

    #[test]
    fn plan_and_image_parts_keep_their_content() {
        for (data, input, status) in [
            (json!({"input": {"plan": "Do it"}}), "Do it", "success"),
            (
                json!({"approval_status": "fail", "input": "x", "output": "No"}),
                "No",
                "fail",
            ),
            (json!({"text": "Text", "input": "x"}), "Text", "success"),
        ] {
            let mut data = data;
            data["type"] = "plan".into();
            let plan = convert(&data).unwrap();
            assert_eq!(
                (plan["input"].as_str(), plan["approval_status"].as_str()),
                (Some(input), Some(status))
            );
        }
        let inline = convert(
            &json!({"type": "image", "data": "aGk=", "mime_type": "image/png"}),
        )
        .unwrap();
        assert_eq!(
            (inline["data"].as_str(), inline["mime_type"].as_str()),
            (Some("aGk="), Some("image/png"))
        );
        let linked =
            convert(&json!({"type": "image", "url": "https://x/y.png"}))
                .unwrap();
        assert_eq!(linked["data"], "https://x/y.png");
        assert!(convert(&json!({"type": "image", "data": "aGk="})).is_none());
    }

    #[test]
    fn tool_parts_fall_back_to_arguments_results_and_title() {
        let tool = convert(&json!({
            "type": "tool",
            "title": "Tool: read",
            "state": {"arguments": {"path": "a"}, "result": "ok"},
        }))
        .unwrap();
        assert_eq!(tool["tool"], "read");
        assert_eq!(
            tool["state"],
            json!({"status": "completed", "input": {"path": "a"}, "output": "ok"})
        );
        for (state, status) in [
            (json!({"status": "success"}), "completed"),
            (json!({"error": "failed"}), "error"),
            (json!({}), "running"),
        ] {
            let tool = convert(
                &json!({"type": "tool", "tool": "bash", "state": state}),
            )
            .unwrap();
            assert_eq!(tool["state"]["status"], status);
        }
        assert!(
            convert(&json!({"type": "tool", "tool": 7, "state": []})).is_none()
        );
    }
}
