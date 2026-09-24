use crate::session::{
    Message, Part, Session, SessionData, Stats, StepPart, TextPart, ToolPart, UnknownPart,
};
use crate::sqlite::rows;
use crate::value::{float, integer, json_object, string, text};
use rusqlite::{Connection, ToSql};
use serde_json::Value;
use std::collections::HashMap;

pub fn read(connection: &Connection, session: &Session) -> crate::Result<SessionData> {
    let records = rows(
        connection,
        "SELECT * FROM message WHERE session_id = ? ORDER BY time_created ASC",
        &[&session.id],
    )?;
    let mut parts_by_id: HashMap<String, Vec<Value>> = HashMap::new();
    for chunk in records.chunks(500) {
        let ids: Vec<_> = chunk.iter().map(|row| string(&row["id"])).collect();
        let parameters: Vec<&dyn ToSql> = ids.iter().map(|id| id as &dyn ToSql).collect();
        let placeholders = vec!["?"; ids.len()].join(", ");
        for part in rows(
            connection,
            &format!(
                "SELECT * FROM part WHERE message_id IN ({placeholders}) ORDER BY message_id ASC, time_created ASC"
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
    let mut stats = Stats {
        total_cost: serde_json::Number::from_f64(0.0).unwrap(),
        ..Stats::default()
    };
    for row in records {
        let id = string(&row["id"]);
        let Some(data) = json_object(&row["data"]) else {
            warn("message", &id);
            continue;
        };
        let mut message = Message::new(
            id.clone(),
            text(&data["role"]),
            integer(&row["time_created"]),
            Vec::new(),
        );
        message.agent = data["agent"].as_str().map(str::to_owned);
        message.mode = data["mode"].as_str().map(str::to_owned);
        message.model = data["modelID"].as_str().map(|model| model.into());
        message.provider = data["providerID"].as_str().map(str::to_owned);
        message.time_completed = data["time"]["completed"].clone();
        message.tokens = data["tokens"].as_object().cloned().unwrap_or_default();
        let cost = float(&data["cost"]);
        message.cost = serde_json::Number::from_f64(cost).unwrap();
        stats.total_cost = serde_json::Number::from_f64(stats.total_cost.as_f64().unwrap() + cost)
            .ok_or("cost total is out of range")?;
        stats.add_tokens(&data["tokens"]["input"], &data["tokens"]["output"])?;
        for row in parts_by_id.remove(&id).unwrap_or_default() {
            let Some(data) = json_object(&row["data"]) else {
                warn("part", &string(&row["id"]));
                continue;
            };
            message
                .parts
                .push(part(&data, integer(&row["time_created"])));
        }
        messages.push(message);
    }
    stats.message_count = messages.len();
    let mut payload = session.payload(messages, stats);
    let row = &session.source_metadata["row"];
    payload.slug = row["slug"].clone();
    payload.directory = row["directory"].clone();
    payload.summary_files = row["summary_files"].clone();
    Ok(payload)
}

fn part(data: &Value, time: i64) -> Part {
    let kind = data["type"].as_str().unwrap_or("unknown");
    match kind {
        "text" => Part::text(text(&data["text"]).into(), time),
        "reasoning" => Part::Reasoning(TextPart {
            text: text(&data["text"]).into(),
            time_created: time,
        }),
        "tool" => Part::Tool(Box::new(ToolPart {
            subagent_type: None,
            tool: text(&data["tool"]).into(),
            call_id: text(&data["callID"]).into(),
            title: text(&data["title"]).into(),
            state: data["state"].as_object().cloned().unwrap_or_default(),
            time_created: time,
            nickname: None,
            subagent_id: None,
        })),
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
    }
}

fn warn(kind: &str, id: &str) {
    eprintln!(
        "Warning: invalid {kind} data: {}",
        crate::render::safe_line(id)
    );
}
