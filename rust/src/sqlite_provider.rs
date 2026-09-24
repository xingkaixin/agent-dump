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
    fn discover(
        &mut self,
        days: i64,
        _diagnostics: &mut crate::provider::DiagnosticSink<'_>,
    ) -> crate::Result<crate::provider::Discovery> {
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

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut crate::provider::DiagnosticSink<'_>,
    ) -> crate::Result<crate::provider::Lookup> {
        let Some(path) = self.database.as_deref() else {
            return Ok(crate::provider::Lookup::default());
        };
        Ok(crate::provider::Lookup::new(
            self.select(&connect(path)?, path, "s.id = ?", &[&id])?
                .into_iter()
                .next(),
        ))
    }

    fn read(
        &self,
        session: &Session,
        _zh: bool,
        diagnostics: &mut crate::provider::DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        if !session.source_path.exists() {
            let (summary, steps) = match self.kind {
                Kind::OpenCode => (
                    "OpenCode database is missing",
                    vec![
                        [
                            "Confirm OpenCode has produced a session database on this machine.",
                            "确认 OpenCode 已在本机生成会话数据库。",
                        ],
                        [
                            "In a test or development environment, check whether `data/opencode/opencode.db` exists.",
                            "若在测试或开发环境，检查 `data/opencode/opencode.db` 是否存在。",
                        ],
                    ],
                ),
                Kind::ZCode => (
                    "ZCode database is missing",
                    vec![
                        [
                            "Confirm ZCode has produced a session database on this macOS or Windows machine.",
                            "确认 ZCode 已在 macOS 或 Windows 本机生成会话数据库。",
                        ],
                        [
                            "On macOS check `~/.zcode/cli/db/db.sqlite`; on Windows check `%USERPROFILE%\\.zcode\\cli\\db\\db.sqlite`.",
                            "macOS 检查 `~/.zcode/cli/db/db.sqlite`；Windows 检查 `%USERPROFILE%\\.zcode\\cli\\db\\db.sqlite`。",
                        ],
                        [
                            "Linux has no default ZCode session path.",
                            "Linux 暂无 ZCode 默认会话路径。",
                        ],
                    ],
                ),
            };
            return Err(crate::provider_error::ProviderError::missing(
                [summary; 2],
                &session.source_path,
                Vec::new(),
                crate::provider::source_roots(self),
                steps,
            )
            .into());
        }
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
            if session.source_metadata["schema"] == "v2" || !has_table(&connection, "session")? {
                return Err(format!("OpenCode session is missing: {}", session.id).into());
            }
        } else if session.source_metadata["schema"] == "v2" {
            return Err(format!("OpenCode V2 session source is missing: {}", session.id).into());
        }
        crate::sqlite_legacy::read(&connection, session, diagnostics)
    }

    fn search_roots(&self) -> Vec<(&'static str, PathBuf)> {
        self.search_roots.clone()
    }

    fn source_root(&self) -> &Path {
        &self.root
    }

    fn raw_export(&self, _session: &Session) -> crate::Result<RawExport> {
        Ok(RawExport::Session)
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

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture(path: &Path, kind: Kind, v2: bool) -> SqliteProvider {
        let connection = Connection::open(path).unwrap();
        connection.execute_batch("CREATE TABLE session (id TEXT, title TEXT, time_created INTEGER, time_updated INTEGER, slug TEXT, directory TEXT, version TEXT, summary_files TEXT); INSERT INTO session VALUES ('kept', 'Kept', 1768478400000, 1768478400000, NULL, '/project', NULL, NULL);").unwrap();
        if v2 {
            connection.execute_batch("CREATE TABLE session_v2 (id TEXT, title TEXT, time_created INTEGER, time_updated INTEGER, slug TEXT, directory TEXT, version TEXT, summary_files TEXT, model TEXT, project_id TEXT, parent_id TEXT); INSERT INTO session_v2 VALUES ('kept', 'V2', 1768478400000, 1768478400000, NULL, '/project', NULL, NULL, NULL, NULL, NULL);").unwrap();
        }
        SqliteProvider {
            kind,
            database: Some(path.into()),
            root: path.parent().unwrap().into(),
            search_roots: vec![("Synthetic database", path.into())],
        }
    }

    #[test]
    fn missing_snapshot_database_does_not_use_new_provider_database() {
        for (kind, summary) in [
            (Kind::OpenCode, "OpenCode database is missing"),
            (Kind::ZCode, "ZCode database is missing"),
        ] {
            let directory = tempfile::tempdir().unwrap();
            let path = directory.path().join("source.sqlite");
            let mut provider = fixture(&path, kind, false);
            let session = provider
                .find("kept", &mut |_| Ok(()))
                .unwrap()
                .session
                .unwrap();
            std::fs::remove_file(&path).unwrap();
            let alternative = directory.path().join("unrelated.sqlite");
            std::fs::write(&alternative, b"must not read or change").unwrap();
            provider.database = Some(alternative.clone());
            let error = provider
                .read(&session, false, &mut |_| Ok(()))
                .err()
                .unwrap();
            crate::source_tests::assert_missing(
                error.as_ref(),
                summary,
                &path,
                &crate::provider::source_roots(&provider),
                "session database",
            );
            assert!(!path.exists());
            assert_eq!(
                std::fs::read(alternative).unwrap(),
                b"must not read or change"
            );
        }
    }

    #[test]
    fn missing_v2_snapshot_never_reads_legacy_duplicate() {
        for (sql, expected) in [
            (
                "DELETE FROM session_v2",
                "OpenCode session is missing: kept",
            ),
            (
                "DROP TABLE session_v2",
                "OpenCode V2 session source is missing: kept",
            ),
        ] {
            let directory = tempfile::tempdir().unwrap();
            let path = directory.path().join("source.sqlite");
            let mut provider = fixture(&path, Kind::OpenCode, true);
            let session = provider
                .find("kept", &mut |_| Ok(()))
                .unwrap()
                .session
                .unwrap();
            assert_eq!(session.title, "V2");
            Connection::open(&path).unwrap().execute_batch(sql).unwrap();
            let before = std::fs::read(&path).unwrap();
            let error = provider
                .read(&session, false, &mut |_| Ok(()))
                .err()
                .unwrap();
            assert_eq!(error.to_string(), expected);
            assert_eq!(std::fs::read(path).unwrap(), before);
        }
    }
}
