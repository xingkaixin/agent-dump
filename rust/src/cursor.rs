use crate::output_formats::OutputFormat;
use crate::provider::Provider;
use crate::session::{Session, SessionData, epoch_seconds, parse_timestamp};
use crate::value::{string, text, truthy};
use jiff::{SignedDuration, Timestamp};
use rusqlite::{Connection, ToSql, types::ValueRef};
use serde_json::{Value, json};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub struct Cursor {
    database: PathBuf,
}

impl Cursor {
    pub fn open() -> crate::Result<Self> {
        let root = if cfg!(target_os = "linux") {
            crate::file_sessions::environment_root("HOME", "")?.join(".config/Cursor")
        } else {
            crate::desktop::app_data("Cursor")?
        };
        Ok(Self {
            database: root.join("User/globalStorage/state.vscdb"),
        })
    }

    fn sessions(
        &self,
        connection: &Connection,
        cutoff: Option<Timestamp>,
    ) -> crate::Result<Vec<Session>> {
        let mut sessions = Vec::new();
        for (key, data) in records(
            connection,
            "SELECT key, value FROM cursorDiskKV WHERE key >= 'composerData:' AND key < 'composerData;' ORDER BY rowid DESC",
            &[],
        )? {
            let Some(data) = data else {
                continue;
            };
            let id = key.split_once(':').unwrap().1;
            let session = build_session(&self.database, id, id, &data);
            if cutoff.is_none_or(|cutoff| session.created_at >= cutoff) {
                sessions.push(session);
            }
        }
        let ids: Vec<_> = sessions
            .iter()
            .map(|s| text(&s.source_metadata["composer_id"]))
            .collect();
        let summaries = summaries(connection, &ids)?;
        for session in &mut sessions {
            let summary = &summaries[text(&session.source_metadata["composer_id"])];
            apply_summary(session, summary, true);
        }
        Ok(sessions)
    }
}

impl Provider for Cursor {
    fn discover(&mut self, days: i64) -> crate::Result<crate::provider::Discovery> {
        if !self.database.exists() {
            return Ok(crate::provider::Discovery::default());
        }
        let cutoff = Timestamp::now().checked_sub(SignedDuration::from_secs(
            days.checked_mul(86400).ok_or("days is out of range")?,
        ))?;
        self.sessions(&crate::sqlite::connect(&self.database)?, Some(cutoff))
            .map(crate::provider::Discovery::available)
    }
    fn find(&mut self, id: &str) -> crate::Result<crate::provider::Lookup> {
        if !self.database.exists() {
            return Ok(crate::provider::Lookup::default());
        }
        let connection = crate::sqlite::connect(&self.database)?;
        for (key, data) in records(
            &connection,
            "SELECT key, value FROM cursorDiskKV WHERE key >= 'bubbleId:' AND key < 'bubbleId;' AND instr(value, ?) > 0 ORDER BY rowid DESC",
            &[&id],
        )? {
            if data.as_ref().is_some_and(|v| v["requestId"] == id) {
                let composer_id = key.split(':').nth(1).unwrap_or("");
                if let Some(composer) = composer(&connection, composer_id)? {
                    let mut session = build_session(&self.database, composer_id, id, &composer);
                    apply_summary(
                        &mut session,
                        &summaries(&connection, &[composer_id])?[composer_id],
                        false,
                    );
                    return Ok(crate::provider::Lookup::new(Some(session)));
                }
                break;
            }
        }
        Ok(crate::provider::Lookup::new(
            self.sessions(&connection, None)?
                .into_iter()
                .find(|s| s.id == id),
        ))
    }
    fn read(&self, session: &Session, _zh: bool) -> crate::Result<SessionData> {
        crate::cursor_transcript::read(&crate::sqlite::connect(&session.source_path)?, session)
    }
    fn search_roots(&self) -> Vec<(&'static str, PathBuf)> {
        vec![("Cursor global state.vscdb", self.database.clone())]
    }

    fn source_root(&self) -> &Path {
        self.database.parent().unwrap()
    }
    fn supports_format(&self, format: OutputFormat) -> bool {
        matches!(format, OutputFormat::Json | OutputFormat::Print)
    }
}

pub fn records(
    connection: &Connection,
    sql: &str,
    parameters: &[&dyn ToSql],
) -> crate::Result<Vec<(String, Option<Value>)>> {
    let mut statement = connection.prepare(sql)?;
    let mut rows = statement.query(parameters)?;
    let mut result = Vec::new();
    while let Some(row) = rows.next()? {
        let value = match row.get_ref(1)? {
            ValueRef::Text(bytes) | ValueRef::Blob(bytes) => serde_json::from_slice::<Value>(bytes)
                .ok()
                .filter(Value::is_object),
            _ => None,
        };
        result.push((row.get(0)?, value));
    }
    Ok(result)
}

pub fn composer(connection: &Connection, id: &str) -> crate::Result<Option<Value>> {
    Ok(records(
        connection,
        "SELECT key, value FROM cursorDiskKV WHERE key = ?",
        &[&format!("composerData:{id}")],
    )?
    .into_iter()
    .next()
    .and_then(|(_, value)| value))
}

pub fn bubbles(
    connection: &Connection,
    id: &str,
    transcript: bool,
    bounded: bool,
) -> crate::Result<Vec<(String, Option<Value>)>> {
    let order = if transcript { "rowid ASC" } else { "key" };
    let limit = if bounded { " LIMIT 20" } else { "" };
    Ok(records(
        connection,
        &format!(
            "SELECT key, value FROM cursorDiskKV WHERE key >= ? AND key < ? ORDER BY {order}{limit}"
        ),
        &[&format!("bubbleId:{id}:"), &format!("bubbleId:{id};")],
    )?
    .into_iter()
    .map(|(key, value)| (key.rsplit(':').next().unwrap().to_owned(), value))
    .collect())
}

struct Summary {
    request: Option<String>,
    model: String,
    count: usize,
}

fn summaries(connection: &Connection, ids: &[&str]) -> crate::Result<HashMap<String, Summary>> {
    let mut counts = HashMap::new();
    let mut fallback = false;
    for batch in ids.chunks(100) {
        let ranges = vec!["(key >= ? AND key < ?)"; batch.len()].join(" OR ");
        let parameters: Vec<String> = batch
            .iter()
            .flat_map(|id| [format!("bubbleId:{id}:"), format!("bubbleId:{id};")])
            .collect();
        let parameters: Vec<&dyn ToSql> = parameters.iter().map(|v| v as &dyn ToSql).collect();
        match crate::sqlite::rows(
            connection,
            &format!(
                "SELECT substr(key, 10, instr(substr(key, 10), ':') - 1) AS composer_id, COUNT(*) AS message_count FROM cursorDiskKV WHERE ({ranges}) AND json_extract(value, '$.type') IN (1, 2) GROUP BY composer_id"
            ),
            &parameters,
        ) {
            Ok(rows) => {
                for row in rows {
                    counts.insert(
                        string(&row["composer_id"]),
                        row["message_count"].as_u64().unwrap_or(0) as usize,
                    );
                }
            }
            Err(_) => {
                fallback = true;
                break;
            }
        }
    }
    let mut result: HashMap<String, Summary> = ids
        .iter()
        .map(|id| {
            (
                (*id).to_owned(),
                Summary {
                    request: None,
                    model: String::new(),
                    count: if fallback {
                        0
                    } else {
                        *counts.get(*id).unwrap_or(&0)
                    },
                },
            )
        })
        .collect();
    if fallback {
        for id in ids {
            for (_, value) in bubbles(connection, id, false, false)? {
                if let Some(value) = value {
                    let summary = result.get_mut(*id).unwrap();
                    if value["type"].as_f64().is_some_and(|v| v == 1.0 || v == 2.0)
                        || value["type"] == true
                    {
                        summary.count += 1;
                    }
                    summary.metadata(&value);
                }
            }
        }
    } else {
        for batch in ids.chunks(100) {
            // Python projects only the first 20 bubbles, even if later ones have request IDs.
            let sql = vec!["SELECT * FROM (SELECT ? AS composer_id, value, key FROM cursorDiskKV WHERE key >= ? AND key < ? ORDER BY key LIMIT 20)"; batch.len()].join(" UNION ALL ") + " ORDER BY composer_id, key";
            let parameters: Vec<String> = batch
                .iter()
                .flat_map(|id| {
                    [
                        (*id).to_owned(),
                        format!("bubbleId:{id}:"),
                        format!("bubbleId:{id};"),
                    ]
                })
                .collect();
            let parameters: Vec<&dyn ToSql> = parameters.iter().map(|v| v as &dyn ToSql).collect();
            for (id, value) in records(connection, &sql, &parameters)? {
                if let Some(value) = value
                    && let Some(summary) = result.get_mut(&id)
                {
                    summary.metadata(&value);
                }
            }
        }
    }
    Ok(result)
}

impl Summary {
    fn metadata(&mut self, value: &Value) {
        if self.request.is_none() && !text(&value["requestId"]).trim().is_empty() {
            self.request = Some(text(&value["requestId"]).trim().into());
        }
        if self.model.is_empty() {
            self.model = text(&value["modelInfo"]["modelName"]).trim().into();
        }
    }
}

fn apply_summary(session: &mut Session, summary: &Summary, use_request: bool) {
    if use_request && let Some(id) = &summary.request {
        session.id = id.clone();
        session.source_metadata["request_id"] = id.clone().into();
    }
    if session.model.is_empty() {
        session.model = summary.model.clone();
    }
    session.message_count = Some(summary.count);
}

pub fn build_session(path: &Path, composer_id: &str, request_id: &str, data: &Value) -> Session {
    let updated = ["updatedAt", "lastUpdatedAt", "lastSendTime"]
        .iter()
        .map(|name| &data[name])
        .find(|value| truthy(value))
        .and_then(cursor_time);
    let created = cursor_time(&data["createdAt"])
        .or(updated)
        .unwrap_or(Timestamp::UNIX_EPOCH);
    let title = ["name", "title"]
        .iter()
        .map(|field| text(&data[field]).trim())
        .find(|v| !v.is_empty())
        .map(str::to_owned)
        .unwrap_or_else(|| {
            format!(
                "Cursor Session {}",
                composer_id.chars().take(8).collect::<String>()
            )
        });
    let mut session = Session::new(
        request_id.into(),
        title,
        path.to_owned(),
        created,
        updated.unwrap_or(created),
    );
    session.model = text(&data["modelConfig"]["modelName"]).trim().into();
    session.subtargets = data["subagentComposerIds"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect();
    let parent = data["subagentInfo"]["parentComposerId"]
        .as_str()
        .filter(|v| !v.is_empty());
    session.source_metadata = json!({"composer_id":composer_id,"request_id":request_id,"parent_composer_id":parent,"subagent_composer_ids":session.subtargets,"usage_data":data["usageData"]});
    session
}

fn cursor_time(value: &Value) -> Option<Timestamp> {
    if let Some(text) = value.as_str().filter(|v| v.contains('T'))
        && let Some(time) = parse_timestamp(text)
    {
        return Some(time);
    }
    if !value.is_number() && !value.is_string() {
        return None;
    }
    if value
        .as_str()
        .is_some_and(|s| s.trim().parse::<f64>().is_err())
    {
        return None;
    }
    let number = value
        .as_f64()
        .or_else(|| value.as_str()?.trim().parse().ok())?;
    // Cursor mixes seconds and milliseconds; preserve the Python reader's cutoff.
    epoch_seconds(if number > 1e12 {
        number / 1000.0
    } else {
        number
    })
}
