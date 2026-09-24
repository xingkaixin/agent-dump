use crate::provider::{Provider, RawExport};
use crate::session::{Session, SessionData, epoch_seconds};
use crate::sqlite::{connect, has_table, rows};
use crate::value::{json_object, string, text};
use jiff::{SignedDuration, Timestamp};
use rusqlite::{Connection, ToSql};
use serde_json::Value;
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, PartialEq)]
pub enum Kind {
    OpenCode,
    ZCode,
}

pub struct SqliteProvider {
    kind: Kind,
    database: Option<PathBuf>,
    root: PathBuf,
    search_roots: Vec<(&'static str, PathBuf)>,
}

impl SqliteProvider {
    pub fn open(kind: Kind) -> crate::Result<Self> {
        let candidates = database_paths(kind)?;
        let database = candidates
            .iter()
            .map(|(_, path)| path)
            .find(|path| path.exists())
            .cloned();
        let root = database
            .as_deref()
            .and_then(Path::parent)
            .unwrap_or(Path::new("."))
            .to_owned();
        Ok(Self {
            kind,
            database,
            root,
            search_roots: candidates,
        })
    }

    fn select(
        &self,
        connection: &Connection,
        source: &Path,
        condition: &str,
        parameters: &[&dyn ToSql],
    ) -> crate::Result<Vec<Session>> {
        let v2 = self.kind == Kind::OpenCode && has_table(connection, "session_v2")?;
        let mut sessions = Vec::new();
        if v2 {
            let count = if has_table(connection, "session_message")? {
                "(SELECT COUNT(*) FROM session_message m WHERE m.session_id = s.id)"
            } else {
                "NULL"
            };
            for row in rows(
                connection,
                &format!(
                    "SELECT s.id, s.title, s.time_created, s.time_updated, s.slug, s.directory, s.version, s.summary_files, s.model, s.project_id, s.parent_id, {count} AS message_count FROM session_v2 s WHERE {condition}"
                ),
                parameters,
            )? {
                sessions.push(build_session(row, source, true));
            }
        }
        if !v2 || has_table(connection, "session")? {
            let metadata = if has_table(connection, "message")? {
                "(SELECT COUNT(*) FROM message m WHERE m.session_id = s.id) AS message_count,
                 (SELECT m.data FROM message m WHERE m.session_id = s.id AND m.data LIKE '%\"modelID\"%' ORDER BY m.time_created DESC LIMIT 1) AS model_message_data"
            } else {
                "NULL AS message_count, NULL AS model_message_data"
            };
            let exclude = if v2 {
                " AND NOT EXISTS (SELECT 1 FROM session_v2 v WHERE v.id = s.id)"
            } else {
                ""
            };
            let sql = format!(
                "SELECT s.id, s.title, s.time_created, s.time_updated, s.slug, s.directory, s.version, s.summary_files, {metadata} FROM session s WHERE ({condition}){exclude} ORDER BY s.time_created DESC"
            );
            for row in rows(connection, &sql, parameters)? {
                sessions.push(build_session(row, source, false));
            }
        }
        if v2 {
            sessions.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        }
        Ok(sessions)
    }
}

impl Provider for SqliteProvider {
    fn discover(&mut self, days: i64) -> crate::Result<crate::provider::Discovery> {
        let Some(path) = &self.database else {
            return Ok(crate::provider::Discovery::default());
        };
        let cutoff = Timestamp::now()
            .checked_sub(SignedDuration::from_secs(
                days.checked_mul(86400).ok_or("days is out of range")?,
            ))?
            .as_millisecond();
        self.select(&connect(path)?, path, "s.time_created >= ?", &[&cutoff])
            .map(crate::provider::Discovery::available)
    }

    fn find(&mut self, id: &str) -> crate::Result<crate::provider::Lookup> {
        let Some(path) = self.database.as_deref() else {
            return Ok(crate::provider::Lookup::default());
        };
        Ok(crate::provider::Lookup::new(
            self.select(&connect(path)?, path, "s.id = ?", &[&id])?
                .into_iter()
                .next(),
        ))
    }

    fn read(&self, session: &Session, _zh: bool) -> crate::Result<SessionData> {
        let connection = connect(&session.source_path)?;
        if self.kind == Kind::OpenCode && has_table(&connection, "session_v2")? {
            if let Some(row) = rows(
                &connection,
                "SELECT * FROM session_v2 WHERE id = ?",
                &[&session.id],
            )?
            .into_iter()
            .next()
            {
                return crate::opencode_v2::read(&connection, session, row);
            }
            if !has_table(&connection, "session")? {
                return Err("OpenCode session is missing".into());
            }
        }
        if session.source_metadata["schema"] == "v2" {
            return Err("OpenCode V2 session source is missing".into());
        }
        crate::sqlite_legacy::read(&connection, session)
    }

    fn search_roots(&self) -> Vec<(&'static str, PathBuf)> {
        self.search_roots.clone()
    }

    fn source_root(&self) -> &Path {
        &self.root
    }

    fn raw_export(&self, _session: &Session) -> RawExport {
        RawExport::Session
    }
}

pub fn build_session(row: Value, path: &Path, v2: bool) -> Session {
    let timestamp = |name: &str| {
        row[name]
            .as_f64()
            .and_then(|value| epoch_seconds(value / 1000.0))
            .unwrap_or(Timestamp::UNIX_EPOCH)
    };
    let model = if v2 {
        json_object(&row["model"])
            .and_then(|value| value["id"].as_str().map(str::to_owned))
            .unwrap_or_default()
    } else {
        json_object(&row["model_message_data"])
            .map(|value| text(&value["modelID"]).trim().to_owned())
            .unwrap_or_default()
    };
    Session {
        id: string(&row["id"]),
        title: if crate::value::truthy(&row["title"]) {
            string(&row["title"])
        } else {
            "Untitled".into()
        },
        created_at: timestamp("time_created"),
        updated_at: timestamp("time_updated"),
        source_path: path.to_owned(),
        directory: text(&row["directory"]).into(),
        version: row["version"].clone(),
        model,
        project: v2
            .then(|| text(&row["project_id"]).trim().to_owned())
            .filter(|text| !text.is_empty()),
        message_count: row["message_count"]
            .as_u64()
            .and_then(|count| count.try_into().ok()),
        subtargets: if v2 {
            Vec::new()
        } else {
            summary_targets(&row["summary_files"])
        },
        source_metadata: serde_json::json!({"schema": if v2 { "v2" } else { "legacy" }, "row": row}),
    }
}

fn summary_targets(raw: &Value) -> Vec<String> {
    let parsed;
    let value = if let Some(text) = raw.as_str() {
        if text.trim().is_empty() {
            return Vec::new();
        }
        parsed = serde_json::from_str::<Value>(text).unwrap_or(Value::Null);
        if parsed.is_array() {
            &parsed
        } else {
            return vec![text.trim().into()];
        }
    } else {
        raw
    };
    match value {
        Value::Null => Vec::new(),
        Value::Array(items) => items
            .iter()
            .map(string)
            .filter(|text| !text.trim().is_empty())
            .collect(),
        value => vec![string(value)],
    }
}

fn database_paths(kind: Kind) -> crate::Result<Vec<(&'static str, PathBuf)>> {
    if kind == Kind::ZCode {
        return if cfg!(any(target_os = "macos", target_os = "windows")) {
            Ok(vec![(
                if cfg!(target_os = "macos") {
                    "macOS ~/.zcode db.sqlite"
                } else {
                    "Windows %USERPROFILE%\\.zcode db.sqlite"
                },
                crate::file_sessions::environment_root("HOME", "")?.join(".zcode/cli/db/db.sqlite"),
            )])
        } else {
            Ok(Vec::new())
        };
    }
    let root =
        crate::file_sessions::environment_root("XDG_DATA_HOME", ".local/share")?.join("opencode");
    if let Some(explicit) = std::env::var_os("OPENCODE_DB").filter(|value| !value.is_empty()) {
        return Ok(if explicit == ":memory:" {
            Vec::new()
        } else {
            vec![("OPENCODE_DB", root.join(explicit))]
        });
    }
    let mut paths = vec![("XDG/default opencode.db", root.join("opencode.db"))];
    if cfg!(target_os = "windows")
        && std::env::var_os("XDG_DATA_HOME").is_none_or(|value| value.is_empty())
        && let Some(base) = ["LOCALAPPDATA", "APPDATA"]
            .iter()
            .find_map(|name| std::env::var_os(name).filter(|value| !value.is_empty()))
    {
        paths.push((
            "LOCALAPPDATA/APPDATA compatibility",
            PathBuf::from(base).join("opencode/opencode.db"),
        ));
    }
    paths.push((
        "local development fallback",
        "data/opencode/opencode.db".into(),
    ));
    Ok(paths)
}
