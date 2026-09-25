pub(super) mod transcript;

use crate::compat::value::{string, text, truthy};
use crate::output::formats::OutputFormat;
use crate::providers::contract::Provider;
use crate::session::timestamp::Timestamp;
use crate::session::{Session, SessionData, epoch_seconds, parse_timestamp};
use jiff::SignedDuration;
use rusqlite::{Connection, ToSql, types::ValueRef};
use serde_json::{Value, json};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub struct Cursor {
    database: PathBuf,
    resolve_database: Box<dyn Fn() -> crate::Result<PathBuf> + Send + Sync>,
}

impl Cursor {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; source access is deferred"
    )]
    pub fn open() -> crate::Result<Self> {
        Ok(Self {
            database: PathBuf::from("."),
            resolve_database: Box::new(database_path),
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
            let summary =
                &summaries[text(&session.source_metadata["composer_id"])];
            apply_summary(session, summary, true);
        }
        Ok(sessions)
    }
}

impl Provider for Cursor {
    fn discover(
        &mut self,
        days: i64,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Discovery> {
        self.database = (self.resolve_database)()?;
        if !self.database.exists() {
            return Ok(crate::providers::contract::Discovery::default());
        }
        let cutoff =
            Timestamp::now().checked_sub(SignedDuration::from_secs(
                days.checked_mul(86400).ok_or("days is out of range")?,
            ))?;
        self.sessions(
            &crate::providers::sqlite::connection::connect(&self.database)?,
            Some(cutoff),
        )
        .map(crate::providers::contract::Discovery::available)
    }
    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Lookup> {
        self.database = (self.resolve_database)()?;
        if !self.database.exists() {
            return Ok(crate::providers::contract::Lookup::default());
        }
        let connection =
            crate::providers::sqlite::connection::connect(&self.database)?;
        for (key, data) in records(
            &connection,
            "SELECT key, value FROM cursorDiskKV WHERE key >= 'bubbleId:' AND key < 'bubbleId;' AND instr(value, ?) > 0 ORDER BY rowid DESC",
            &[&id],
        )? {
            if data.as_ref().is_some_and(|v| v["requestId"] == id) {
                let composer_id = key.split(':').nth(1).unwrap_or("");
                if let Some(composer) = composer(&connection, composer_id)? {
                    let mut session = build_session(
                        &self.database,
                        composer_id,
                        id,
                        &composer,
                    );
                    apply_summary(
                        &mut session,
                        &summaries(&connection, &[composer_id])?[composer_id],
                        false,
                    );
                    return Ok(crate::providers::contract::Lookup::new(Some(
                        session,
                    )));
                }
                break;
            }
        }
        Ok(crate::providers::contract::Lookup::new(
            self.sessions(&connection, None)?
                .into_iter()
                .find(|s| s.id == id),
        ))
    }
    fn read(
        &self,
        session: &Session,
        _zh: bool,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        let path = (self.resolve_database)()?;
        if !path.exists() {
            return Err(crate::providers::error::ProviderError::missing(
                ["Cursor global database is missing"; 2],
                &path,
                Vec::new(),
                crate::providers::contract::source_roots(self)?,
                vec![
                    ["Confirm `globalStorage/state.vscdb` still exists under the Cursor user directory.", "确认 Cursor 用户目录下的 globalStorage/state.vscdb 仍存在。"],
                    ["Re-run `agent-dump --list --agent cursor` to check whether sessions are still visible.", "重新运行 `agent-dump --list --agent cursor` 检查会话是否仍可见。"],
                ],
            ).into());
        }
        crate::providers::cursor::transcript::read(
            &crate::providers::sqlite::connection::connect(&path)?,
            session,
        )
    }
    fn search_roots(
        &self,
    ) -> crate::Result<crate::providers::contract::SearchRoots> {
        Ok(vec![(
            "Cursor global state.vscdb",
            (self.resolve_database)()?,
        )])
    }

    fn change_sources(&self, session: &Session) -> Vec<PathBuf> {
        crate::providers::sqlite::connection::change_sources(
            &session.source_path,
        )
    }

    fn source_root(&self) -> &Path {
        self.database.parent().unwrap()
    }
    fn supports_format(&self, format: OutputFormat) -> bool {
        matches!(format, OutputFormat::Json | OutputFormat::Print)
    }
}

fn database_path() -> crate::Result<PathBuf> {
    let root = if cfg!(target_os = "linux") {
        crate::providers::files::environment_root("HOME", "")?
            .join(".config/Cursor")
    } else {
        crate::providers::desktop::app_data("Cursor")?
    };
    Ok(root.join("User/globalStorage/state.vscdb"))
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
            ValueRef::Text(bytes) | ValueRef::Blob(bytes) => {
                crate::compat::json::from_slice(bytes)
                    .ok()
                    .filter(Value::is_object)
            }
            _ => None,
        };
        result.push((row.get(0)?, value));
    }
    Ok(result)
}

pub fn composer(
    connection: &Connection,
    id: &str,
) -> crate::Result<Option<Value>> {
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

#[allow(
    clippy::float_cmp,
    reason = "Numeric role tags must equal 1 or 2 exactly, including floating-point encodings"
)]
fn summaries(
    connection: &Connection,
    ids: &[&str],
) -> crate::Result<HashMap<String, Summary>> {
    let mut counts = HashMap::new();
    let mut fallback = false;
    for batch in ids.chunks(100) {
        let ranges = vec!["(key >= ? AND key < ?)"; batch.len()].join(" OR ");
        let parameters: Vec<String> = batch
            .iter()
            .flat_map(|id| {
                [format!("bubbleId:{id}:"), format!("bubbleId:{id};")]
            })
            .collect();
        let parameters: Vec<&dyn ToSql> =
            parameters.iter().map(|v| v as &dyn ToSql).collect();
        if let Ok(rows) = crate::providers::sqlite::connection::rows(
            connection,
            &format!(
                "SELECT substr(key, 10, instr(substr(key, 10), ':') - 1) AS composer_id, COUNT(*) AS message_count FROM cursorDiskKV WHERE ({ranges}) AND json_extract(value, '$.type') IN (1, 2) GROUP BY composer_id"
            ),
            &parameters,
        ) {
            for row in rows {
                counts.insert(
                    string(&row["composer_id"]),
                    usize::try_from(row["message_count"].as_u64().unwrap_or(0))
                        .unwrap_or(usize::MAX),
                );
            }
        } else {
            fallback = true;
            break;
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
                    if value["type"]
                        .as_f64()
                        .is_some_and(|v| v == 1.0 || v == 2.0)
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
            let parameters: Vec<&dyn ToSql> =
                parameters.iter().map(|v| v as &dyn ToSql).collect();
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
        if self.request.is_none()
            && !text(&value["requestId"]).trim().is_empty()
        {
            self.request = Some(text(&value["requestId"]).trim().into());
        }
        if self.model.is_empty() {
            self.model = text(&value["modelInfo"]["modelName"]).trim().into();
        }
    }
}

fn apply_summary(session: &mut Session, summary: &Summary, use_request: bool) {
    if use_request && let Some(id) = &summary.request {
        session.id.clone_from(id);
        session.source_metadata["request_id"] = id.clone().into();
    }
    if session.model.is_empty() {
        session.model.clone_from(&summary.model);
    }
    session.message_count = Some(summary.count);
}

pub fn build_session(
    path: &Path,
    composer_id: &str,
    request_id: &str,
    data: &Value,
) -> Session {
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
        .map_or_else(
            || {
                format!(
                    "Cursor Session {}",
                    composer_id.chars().take(8).collect::<String>()
                )
            },
            str::to_owned,
        );
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reading_previous_session_uses_current_database_and_missing_path() {
        let directory = tempfile::tempdir().unwrap();
        let first = directory.path().join("first.sqlite");
        let second = directory.path().join("second.sqlite");
        let missing = directory.path().join("missing.sqlite");
        for (path, body) in [(&first, "First"), (&second, "Second")] {
            let connection = Connection::open(path).unwrap();
            connection.execute_batch("CREATE TABLE cursorDiskKV (key TEXT, value TEXT); INSERT INTO cursorDiskKV VALUES ('composerData:kept', '{\"name\":\"Kept\",\"createdAt\":1768478400000}');").unwrap();
            connection
                .execute(
                    "INSERT INTO cursorDiskKV VALUES ('bubbleId:kept:message', ?)",
                    [
                        serde_json::json!({"type":1,"text":body,"createdAt":1_768_478_400_000_i64})
                            .to_string(),
                    ],
                )
                .unwrap();
        }
        let configured =
            std::sync::Arc::new(std::sync::Mutex::new(first.clone()));
        let mut provider = Cursor {
            database: PathBuf::from("."),
            resolve_database: Box::new({
                let configured = configured.clone();
                move || Ok(configured.lock().unwrap().clone())
            }),
        };
        let session = provider
            .find("kept", &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap();
        let data = provider.read(&session, false, &mut |_| Ok(())).unwrap();
        assert_eq!(
            serde_json::to_value(data).unwrap()["messages"][0]["parts"][0]["text"],
            "First"
        );
        let cache = crate::session::cache::SessionDataCache::default();
        let cached = cache
            .get("cursor", &provider, &session, false, &mut |_| Ok(()))
            .unwrap();
        *configured.lock().unwrap() = second.clone();
        let unchanged = cache
            .get("cursor", &provider, &session, false, &mut |_| Ok(()))
            .unwrap();
        assert!(std::sync::Arc::ptr_eq(&cached, &unchanged));
        std::fs::remove_file(&first).unwrap();
        let before = std::fs::read(&second).unwrap();
        let data = provider.read(&session, false, &mut |_| Ok(())).unwrap();
        assert_eq!(
            serde_json::to_value(data).unwrap()["messages"][0]["parts"][0]["text"],
            "Second"
        );
        assert_eq!(session.source_path, first);
        let refreshed = cache
            .get("cursor", &provider, &session, false, &mut |_| Ok(()))
            .unwrap();
        assert_eq!(
            serde_json::to_value(refreshed.as_ref()).unwrap()["messages"][0]["parts"]
                [0]["text"],
            "Second"
        );
        *configured.lock().unwrap() = missing.clone();
        let error = provider
            .read(&session, false, &mut |_| Ok(()))
            .err()
            .unwrap();
        crate::providers::source_tests::assert_missing(
            error.as_ref(),
            "Cursor global database is missing",
            &missing,
            &crate::providers::contract::source_roots(&provider).unwrap(),
            "globalStorage/state.vscdb",
        );
        assert!(!missing.exists() && !first.exists());
        assert_eq!(std::fs::read(second).unwrap(), before);
    }

    #[test]
    fn discovery_and_lookup_follow_current_database_configuration() {
        let directory = tempfile::tempdir().unwrap();
        let first = directory.path().join("first.sqlite");
        let second = directory.path().join("second.sqlite");
        for path in [&first, &second] {
            Connection::open(path).unwrap().execute_batch("CREATE TABLE cursorDiskKV (key TEXT, value TEXT); INSERT INTO cursorDiskKV VALUES ('composerData:kept', '{\"name\":\"Kept\",\"createdAt\":1768478400000}');").unwrap();
        }
        let configured = std::sync::Arc::new(std::sync::Mutex::new(
            directory.path().join("missing.sqlite"),
        ));
        let mut provider = Cursor {
            database: PathBuf::from("."),
            resolve_database: Box::new({
                let configured = configured.clone();
                move || Ok(configured.lock().unwrap().clone())
            }),
        };
        assert!(!provider.discover(36500, &mut |_| Ok(())).unwrap().available);
        assert!(
            provider
                .find("kept", &mut |_| Ok(()))
                .unwrap()
                .session
                .is_none()
        );
        for path in [&first, &second, &first] {
            *configured.lock().unwrap() = path.clone();
            assert_eq!(provider.search_roots().unwrap()[0].1, *path);
            assert_eq!(
                provider
                    .find("kept", &mut |_| Ok(()))
                    .unwrap()
                    .session
                    .unwrap()
                    .source_path,
                *path
            );
            assert_eq!(
                provider.discover(36500, &mut |_| Ok(())).unwrap().sessions[0]
                    .source_path,
                *path
            );
            assert_eq!(provider.source_root(), path.parent().unwrap());
        }
    }

    #[test]
    fn removed_database_keeps_provider_diagnostic() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("state.vscdb");
        let connection = Connection::open(&path).unwrap();
        connection.execute_batch("CREATE TABLE cursorDiskKV (key TEXT, value TEXT); INSERT INTO cursorDiskKV VALUES ('composerData:kept', '{\"name\":\"Kept\",\"createdAt\":1768478400000}');").unwrap();
        drop(connection);
        let mut provider = Cursor {
            resolve_database: Box::new({
                let path = path.clone();
                move || Ok(path.clone())
            }),
            database: path.clone(),
        };
        let session = provider
            .find("kept", &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap();
        std::fs::remove_file(&path).unwrap();
        let error = provider
            .read(&session, false, &mut |_| Ok(()))
            .err()
            .unwrap();
        crate::providers::source_tests::assert_missing(
            error.as_ref(),
            "Cursor global database is missing",
            &path,
            &crate::providers::contract::source_roots(&provider).unwrap(),
            "globalStorage/state.vscdb",
        );
        assert!(!path.exists());
    }
}
