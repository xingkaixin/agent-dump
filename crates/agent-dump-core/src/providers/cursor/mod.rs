pub(super) mod transcript;
mod workspace;

use crate::compat::value::{text, truthy};
use crate::output::formats::OutputFormat;
use crate::providers::contract::{Provider, Window};
use crate::session::timestamp::Timestamp;
use crate::session::{
    Message, Part, Session, SessionData, epoch_seconds, parse_timestamp,
};
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

    fn directories(&self) -> HashMap<String, String> {
        self.database
            .parent()
            .and_then(Path::parent)
            .map(workspace::directories)
            .unwrap_or_default()
    }

    fn sessions(
        &self,
        connection: &Connection,
        cutoff: Option<Timestamp>,
    ) -> crate::Result<Vec<Session>> {
        let directories = self.directories();
        let mut sessions = Vec::new();
        for (_, data) in records(
            connection,
            "SELECT key, value FROM cursorDiskKV WHERE key >= 'composerData:' AND key < 'composerData;' ORDER BY rowid DESC",
            &[],
        )? {
            if let Some(data) = data
                && let Some(session) =
                    self.session(connection, &data, &directories, cutoff)?
            {
                sessions.push(session);
            }
        }
        Ok(sessions)
    }

    fn session(
        &self,
        connection: &Connection,
        composer: &Value,
        directories: &HashMap<String, String>,
        cutoff: Option<Timestamp>,
    ) -> crate::Result<Option<Session>> {
        let Some(id) = composer_id(composer) else {
            return Ok(None);
        };
        let updated = ["updatedAt", "lastUpdatedAt", "lastSendTime"]
            .iter()
            .map(|name| &composer[name])
            .find(|value| truthy(value))
            .and_then(cursor_time);
        let created = cursor_time(&composer["createdAt"])
            .or(updated)
            .unwrap_or(Timestamp::UNIX_EPOCH);
        if cutoff.is_some_and(|cutoff| created < cutoff) {
            return Ok(None);
        }
        let messages = transcript::messages(
            &bubbles(connection, id)?,
            model(composer),
            created.as_millisecond(),
        );
        let subagents = composer["subagentInfos"].as_array();
        if messages.is_empty()
            && !subagents
                .is_some_and(|infos| infos.iter().any(Value::is_object))
        {
            return Ok(None);
        }
        let mut session = Session::new(
            id.into(),
            title(composer, &messages),
            self.database.clone(),
            created,
            updated.unwrap_or(created),
        );
        session.model = model(composer)
            .or_else(|| {
                messages
                    .iter()
                    .find_map(|message| message.model.as_ref()?.as_str())
            })
            .unwrap_or_default()
            .into();
        session.message_count = Some(messages.len());
        session.directory = directories.get(id).cloned().unwrap_or_default();
        session.subtargets = subagents
            .into_iter()
            .flatten()
            .map(|info| text(&info["id"]))
            .filter(|id| !id.is_empty())
            .map(str::to_owned)
            .collect();
        session.source_metadata =
            json!({"composer_id":id,"usage_data":composer["usageData"]});
        Ok(Some(session))
    }
}

impl Provider for Cursor {
    fn discover(
        &mut self,
        window: Window,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Discovery> {
        self.database = (self.resolve_database)()?;
        if !self.database.exists() {
            return Ok(crate::providers::contract::Discovery::default());
        }
        let cutoff =
            window.created_days().map(Timestamp::days_ago).transpose()?;
        self.sessions(
            &crate::providers::sqlite::connection::connect(&self.database)?,
            cutoff,
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
        let mut composer = composer(&connection, id)?
            .filter(|composer| composer_id(composer) == Some(id));
        if composer.is_none() {
            composer = request_composer(&connection, id)?;
        }
        if composer.is_none() {
            composer = records(
                &connection,
                "SELECT key, value FROM cursorDiskKV WHERE key >= 'composerData:' AND key < 'composerData;'",
                &[],
            )?
            .into_iter()
            .filter_map(|(_, value)| value)
            .find(|composer| composer_id(composer) == Some(id));
        }
        let session = match composer {
            Some(composer) => {
                self.session(&connection, &composer, &self.directories(), None)?
            }
            None => None,
        };
        Ok(crate::providers::contract::Lookup::new(session))
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

    fn select_source(&mut self) -> crate::Result<Option<&Path>> {
        self.database = (self.resolve_database)()?;
        Ok(self.database.exists().then(|| self.source_root()))
    }
    fn supports_format(&self, format: OutputFormat) -> bool {
        matches!(format, OutputFormat::Json | OutputFormat::Print)
    }
}

fn database_path() -> crate::Result<PathBuf> {
    let user =
        match crate::providers::files::environment_path("CURSOR_DATA_PATH")? {
            Some(user) => user,
            None => crate::providers::desktop::app_data("Cursor")?.join("User"),
        };
    Ok(user.join("globalStorage/state.vscdb"))
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
) -> crate::Result<Vec<(String, Value)>> {
    Ok(records(
        connection,
        "SELECT key, value FROM cursorDiskKV WHERE key >= ? AND key < ? ORDER BY rowid",
        &[&format!("bubbleId:{id}:"), &format!("bubbleId:{id};")],
    )?
    .into_iter()
    .filter_map(|(key, value)| {
        Some((key.rsplit(':').next().unwrap().to_owned(), value?))
    })
    .collect())
}

fn request_composer(
    connection: &Connection,
    request: &str,
) -> crate::Result<Option<Value>> {
    for (key, data) in records(
        connection,
        "SELECT key, value FROM cursorDiskKV WHERE key >= 'bubbleId:' AND key < 'bubbleId;' AND instr(value, ?) > 0 ORDER BY rowid DESC",
        &[&request],
    )? {
        if data.is_some_and(|bubble| bubble["requestId"] == request) {
            return composer(connection, key.split(':').nth(1).unwrap_or(""));
        }
    }
    Ok(None)
}

fn composer_id(composer: &Value) -> Option<&str> {
    [&composer["id"], &composer["composerId"]]
        .into_iter()
        .map(text)
        .find(|id| !id.is_empty())
}

pub fn model(composer: &Value) -> Option<&str> {
    [&composer["modelConfig"]["modelName"], &composer["model"]]
        .into_iter()
        .map(text)
        .find(|model| !model.is_empty())
}

fn title(composer: &Value, messages: &[Message]) -> String {
    [&composer["name"], &composer["title"]]
        .into_iter()
        .map(text)
        .find(|title| !title.is_empty())
        .and_then(title_line)
        .or_else(|| {
            messages
                .iter()
                .filter(|message| message.role == "user")
                .flat_map(|message| &message.parts)
                .find_map(|part| match part {
                    Part::Text(part) => title_line(&part.text),
                    _ => None,
                })
        })
        .or_else(|| title_line(text(&composer["text"])))
        .unwrap_or_else(|| "Untitled Session".into())
}

fn title_line(value: &str) -> Option<String> {
    crate::providers::text::clean(value)
        .lines()
        .find(|line| !line.trim().is_empty())
        .and_then(crate::providers::title::normalize_title)
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
            connection.execute_batch("CREATE TABLE cursorDiskKV (key TEXT, value TEXT); INSERT INTO cursorDiskKV VALUES ('composerData:kept', '{\"composerId\":\"kept\",\"name\":\"Kept\",\"createdAt\":1768478400000}');").unwrap();
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
            Connection::open(path).unwrap().execute_batch("CREATE TABLE cursorDiskKV (key TEXT, value TEXT); INSERT INTO cursorDiskKV VALUES ('composerData:kept', '{\"composerId\":\"kept\",\"name\":\"Kept\",\"createdAt\":1768478400000}'), ('bubbleId:kept:message', '{\"text\":\"Kept\"}');").unwrap();
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
        assert!(
            !provider
                .discover(Window::Created(36500), &mut |_| Ok(()))
                .unwrap()
                .available
        );
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
                provider
                    .discover(Window::Created(36500), &mut |_| Ok(()))
                    .unwrap()
                    .sessions[0]
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
        connection.execute_batch("CREATE TABLE cursorDiskKV (key TEXT, value TEXT); INSERT INTO cursorDiskKV VALUES ('composerData:kept', '{\"composerId\":\"kept\",\"name\":\"Kept\",\"createdAt\":1768478400000}'), ('bubbleId:kept:message', '{\"text\":\"Kept\"}');").unwrap();
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
