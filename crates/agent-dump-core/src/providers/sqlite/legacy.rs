use crate::compat::value::{float, integer, json_object, string, text};
use crate::providers::contract::{DiagnosticSink, RecoverableDiagnostic};
use crate::providers::sqlite::connection::rows;
use crate::session::{
    Message, Part, Session, SessionData, Stats, StepPart, TextPart, ToolPart,
    UnknownPart,
};
use rusqlite::{Connection, ToSql};
use serde_json::Value;
use std::collections::HashMap;

pub fn read(
    connection: &Connection,
    session: &Session,
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
                "SELECT id, message_id, time_created, CASE WHEN typeof(data) = 'text' THEN data END AS data
                 FROM part WHERE message_id IN ({placeholders}) ORDER BY message_id ASC, time_created ASC"
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
            diagnostics(RecoverableDiagnostic::MessageDataParseFailed(id))?;
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
        message.model = data["modelID"].as_str().map(std::convert::Into::into);
        message.provider = data["providerID"].as_str().map(str::to_owned);
        message.time_completed = data["time"]["completed"].clone();
        message.tokens =
            data["tokens"].as_object().cloned().unwrap_or_default();
        let cost = float(&data["cost"]);
        message.cost = serde_json::Number::from_f64(cost).unwrap();
        stats.total_cost = crate::compat::json::float(
            crate::compat::json::nonfinite(&stats.total_cost)
                .or_else(|| stats.total_cost.as_f64())
                .unwrap()
                + cost,
        );
        stats
            .add_tokens(&data["tokens"]["input"], &data["tokens"]["output"])?;
        for row in parts_by_id.remove(&id).unwrap_or_default() {
            let Some(data) = json_object(&row["data"]) else {
                diagnostics(RecoverableDiagnostic::PartDataParseFailed(
                    string(&row["id"]),
                ))?;
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
