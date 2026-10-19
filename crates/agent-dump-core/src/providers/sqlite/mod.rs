pub mod connection;
pub mod legacy;
pub mod v2;

use crate::compat::value::{json_object, string, text};
use crate::providers::contract::{Provider, RawExport, Window};
use crate::providers::sqlite::connection::{
    Readers, connect, has_column, has_table, rows,
};
use crate::session::timestamp::Timestamp;
use crate::session::{Message, Part, Session, SessionData, epoch_seconds};
use rusqlite::{Connection, ToSql};
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    OpenCode,
    ZCode,
}

#[derive(Default)]
pub struct Facts {
    pub count: usize,
    pub title: Option<String>,
}

struct Layout {
    v2: bool,
    legacy: Option<Legacy>,
}

enum Legacy {
    All,
    Unmigrated(Option<String>),
}

impl Legacy {
    fn filter(&self) -> (&'static str, Option<&dyn ToSql>) {
        match self {
            Self::All => ("1", None),
            Self::Unmigrated(None) => (
                "NOT EXISTS (SELECT 1 FROM session_v2 v WHERE v.id = s.id)",
                None,
            ),
            Self::Unmigrated(Some(cursor)) => (
                "NOT EXISTS (SELECT 1 FROM session_v2 v WHERE v.id = s.id) AND s.id < ?",
                Some(cursor),
            ),
        }
    }
}

pub struct SqliteProvider {
    kind: Kind,
    database: Option<PathBuf>,
    root: PathBuf,
    search_roots: crate::providers::contract::SourceResolver,
    readers: Readers,
}

impl SqliteProvider {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; \
                  source access is deferred"
    )]
    pub fn open(kind: Kind) -> crate::Result<Self> {
        Ok(Self {
            kind,
            database: None,
            root: PathBuf::from("."),
            search_roots: Box::new(move || database_paths(kind)),
            readers: Readers::default(),
        })
    }

    fn ensure_database(&mut self) -> crate::Result<()> {
        if self.database.is_none() {
            self.database = (self.search_roots)()?
                .iter()
                .map(|(_, path)| path)
                .find(|path| path.exists())
                .cloned();
            if let Some(path) = &self.database {
                self.root =
                    path.parent().unwrap_or_else(|| Path::new(".")).to_owned();
            }
        }
        Ok(())
    }

    fn layout(&self, connection: &Connection) -> crate::Result<Layout> {
        let v2 =
            self.kind == Kind::OpenCode && has_table(connection, "session_v2")?;
        if !v2 {
            return Ok(Layout {
                v2,
                legacy: Some(Legacy::All),
            });
        }
        if !has_table(connection, "session")? {
            return Ok(Layout { v2, legacy: None });
        }
        let state = if has_table(connection, "kv")? {
            rows(
                connection,
                "SELECT value FROM kv WHERE key = 'migration.v1-v2'",
                &[],
            )?
            .first()
            .and_then(|row| row["value"].as_str())
            .map(crate::compat::json::from_str)
            .transpose()?
            .unwrap_or_default()
        } else {
            Value::Null
        };
        // OpenCode copies V1 sessions in descending ID order and records the
        // last copied ID; V1 IDs at or above it were copied or deleted in V2.
        Ok(Layout {
            v2,
            legacy: (state["phase"] != "completed").then(|| {
                Legacy::Unmigrated(state["cursor"].as_str().map(str::to_owned))
            }),
        })
    }

    fn select(
        &self,
        connection: &Connection,
        source: &Path,
        condition: &str,
        parameters: &[&dyn ToSql],
    ) -> crate::Result<Vec<Session>> {
        let layout = self.layout(connection)?;
        let mut sessions = Vec::new();
        if layout.v2 {
            let selected = selected(connection, "session_v2", "1", &[], true)?;
            let facts = if has_table(connection, "session_message")? {
                Some(v2::facts(
                    connection,
                    &format!("SELECT s.id FROM session_v2 s WHERE {condition}"),
                    parameters,
                )?)
            } else {
                None
            };
            for row in rows(
                connection,
                &format!(
                    "SELECT s.id, s.title, s.time_created, s.time_updated, \
                     s.slug, s.directory, s.version, s.summary_files, s.model, \
                     s.project_id, s.parent_id FROM session_v2 s \
                     WHERE {condition}"
                ),
                parameters,
            )? {
                sessions.extend(listed(
                    &row,
                    source,
                    true,
                    &selected,
                    facts.as_ref(),
                ));
            }
        }
        if let Some(legacy) = &layout.legacy {
            let (filter, cursor) = legacy.filter();
            let scope = format!("({condition}) AND {filter}");
            let mut bound = parameters.to_vec();
            bound.extend(cursor);
            let selected = selected(
                connection,
                "session",
                filter,
                &Vec::from_iter(cursor),
                layout.v2,
            )?;
            let messages = has_table(connection, "message")?;
            let facts = if messages {
                Some(legacy::facts(
                    connection,
                    &format!("SELECT s.id FROM session s WHERE {scope}"),
                    &bound,
                )?)
            } else {
                None
            };
            let model = if messages {
                "(SELECT m.data FROM message m \
                 WHERE m.session_id = s.id \
                 AND m.data LIKE '%\"modelID\"%' \
                 ORDER BY m.time_created DESC LIMIT 1)"
            } else {
                "NULL"
            };
            for row in rows(
                connection,
                &format!(
                    "SELECT s.id, s.title, s.time_created, s.time_updated, \
                     s.slug, s.directory, s.version, s.summary_files, \
                     {model} AS model_message_data FROM session s \
                     WHERE {scope} ORDER BY s.time_created DESC"
                ),
                &bound,
            )? {
                sessions.extend(listed(
                    &row,
                    source,
                    false,
                    &selected,
                    facts.as_ref(),
                ));
            }
        }
        sessions.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        Ok(sessions)
    }

    fn read_session(
        &self,
        connection: &Connection,
        session: &Session,
        diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        let layout = self.layout(connection)?;
        if layout.v2 {
            if let Some(row) = rows(
                connection,
                "SELECT * FROM session_v2 WHERE id = ?",
                &[&session.id],
            )?
            .into_iter()
            .next()
            {
                return crate::providers::sqlite::v2::read(
                    connection, session, &row,
                );
            }
        } else if session.source_metadata["schema"] == "v2" {
            return Err(format!(
                "OpenCode V2 session source is missing: {}",
                session.id
            )
            .into());
        }
        let legacy = layout
            .legacy
            .as_ref()
            .filter(|_| session.source_metadata["schema"] != "v2");
        let present = if let Some(legacy) = legacy {
            let (filter, cursor) = legacy.filter();
            let mut bound: Vec<&dyn ToSql> = vec![&session.id];
            bound.extend(cursor);
            !rows(
                connection,
                &format!("SELECT 1 FROM session s WHERE s.id = ? AND {filter}"),
                &bound,
            )?
            .is_empty()
        } else {
            false
        };
        if !present {
            let name = match self.kind {
                Kind::OpenCode => "OpenCode",
                Kind::ZCode => "ZCode",
            };
            return Err(
                format!("{name} session is missing: {}", session.id).into()
            );
        }
        crate::providers::sqlite::legacy::read(
            connection,
            session,
            !layout.v2,
            diagnostics,
        )
    }
}

fn selected(
    connection: &Connection,
    table: &str,
    filter: &str,
    parameters: &[&dyn ToSql],
    orphans: bool,
) -> crate::Result<HashSet<String>> {
    let parent = has_column(connection, table, "parent_id")?;
    let task = !parent && has_column(connection, table, "task_type")?;
    let rows = rows(
        connection,
        &format!(
            "SELECT s.id, {} AS parent_id, {} AS task_type FROM {table} s WHERE {filter}",
            if parent { "s.parent_id" } else { "NULL" },
            if task { "s.task_type" } else { "NULL" },
        ),
        parameters,
    )?;
    let known: HashSet<_> = rows.iter().map(|row| string(&row["id"])).collect();
    let mut children: HashMap<&str, Vec<String>> = HashMap::new();
    let mut selected = HashSet::new();
    for row in &rows {
        let id = string(&row["id"]);
        let child = row["parent_id"].as_str().filter(|parent| {
            !orphans
                || (!parent.is_empty()
                    && *parent != id
                    && known.contains(*parent))
        });
        if let Some(parent) = child {
            children.entry(parent).or_default().push(id);
        } else if orphans || parent || row["task_type"] != "subagent_child" {
            selected.insert(id);
        }
    }
    let mut pending: Vec<_> = selected.iter().cloned().collect();
    while let Some(id) = pending.pop() {
        for child in children.get(id.as_str()).into_iter().flatten() {
            if selected.insert(child.clone()) {
                pending.push(child.clone());
            }
        }
    }
    Ok(selected)
}

fn listed(
    row: &Value,
    source: &Path,
    v2: bool,
    selected: &HashSet<String>,
    facts: Option<&HashMap<String, Facts>>,
) -> Option<Session> {
    let id = string(&row["id"]);
    if !selected.contains(&id) {
        return None;
    }
    let facts = match facts {
        Some(facts) => Some(facts.get(&id)?),
        None => None,
    };
    Some(build_session(row, source, v2, facts))
}

pub fn title(text: &str) -> Option<String> {
    let text = crate::providers::text::clean(text);
    crate::providers::title::normalize_title(
        text.lines().find(|line| !line.trim().is_empty())?,
    )
}

pub fn user_title(messages: &[Message]) -> Option<String> {
    messages
        .iter()
        .filter(|message| message.role == "user")
        .flat_map(|message| &message.parts)
        .find_map(|part| match part {
            Part::Text(part) => title(&part.text),
            _ => None,
        })
}

pub fn display_title(row: &Value, fallback: Option<String>) -> String {
    row["title"]
        .as_str()
        .and_then(title)
        .or(fallback)
        .unwrap_or_else(|| "Untitled Session".into())
}

impl Provider for SqliteProvider {
    fn discover(
        &mut self,
        window: Window,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Discovery> {
        self.ensure_database()?;
        let Some(path) = &self.database else {
            return Ok(crate::providers::contract::Discovery::default());
        };
        let cutoff = window
            .created_days()
            .map(Timestamp::days_ago)
            .transpose()?
            .map(Timestamp::as_millisecond);
        let connection = connect(path)?;
        if let Some(cutoff) = cutoff {
            self.select(&connection, path, "s.time_created >= ?", &[&cutoff])
        } else {
            self.select(&connection, path, "1", &[])
        }
        .map(crate::providers::contract::Discovery::available)
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Lookup> {
        self.ensure_database()?;
        let Some(path) = self.database.as_deref() else {
            return Ok(crate::providers::contract::Lookup::default());
        };
        Ok(crate::providers::contract::Lookup::new(
            self.select(&connect(path)?, path, "s.id = ?", &[&id])?
                .into_iter()
                .next(),
        ))
    }

    fn read(
        &self,
        session: &Session,
        _zh: bool,
        diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
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
                            "In a test or development environment, check \
                             whether `data/opencode/opencode.db` exists.",
                            "若在测试或开发环境，\
                             检查 `data/opencode/opencode.db` 是否存在。",
                        ],
                    ],
                ),
                Kind::ZCode => (
                    "ZCode database is missing",
                    vec![
                        [
                            "Confirm ZCode has produced a session database \
                             on this macOS or Windows machine.",
                            "确认 ZCode 已在 macOS 或 Windows 本机生成会话数据库。",
                        ],
                        [
                            "On macOS check `~/.zcode/cli/db/db.sqlite`; \
                             on Windows check \
                             `%USERPROFILE%\\.zcode\\cli\\db\\db.sqlite`.",
                            "macOS 检查 `~/.zcode/cli/db/db.sqlite`；\
                             Windows 检查 \
                             `%USERPROFILE%\\.zcode\\cli\\db\\db.sqlite`。",
                        ],
                        [
                            "Linux has no default ZCode session path.",
                            "Linux 暂无 ZCode 默认会话路径。",
                        ],
                    ],
                ),
            };
            return Err(crate::providers::error::ProviderError::missing(
                [summary; 2],
                &session.source_path,
                Vec::new(),
                crate::providers::contract::source_roots(self)?,
                steps,
            )
            .into());
        }
        self.readers.read(&session.source_path, |connection| {
            self.read_session(connection, session, diagnostics)
        })
    }

    fn search_roots(
        &self,
    ) -> crate::Result<crate::providers::contract::SearchRoots> {
        (self.search_roots)()
    }

    fn change_sources(&self, session: &Session) -> Vec<PathBuf> {
        crate::providers::sqlite::connection::change_sources(
            &session.source_path,
        )
    }

    fn source_root(&self) -> &Path {
        &self.root
    }

    fn select_source(&mut self) -> crate::Result<Option<&Path>> {
        self.ensure_database()?;
        Ok(self.database.is_some().then_some(self.root.as_path()))
    }

    fn raw_export(&self, _session: &Session) -> crate::Result<RawExport> {
        Ok(RawExport::Session)
    }
}

pub fn build_session(
    row: &Value,
    path: &Path,
    v2: bool,
    facts: Option<&Facts>,
) -> Session {
    let timestamp = |value: &Value| {
        value
            .as_f64()
            .and_then(|value| epoch_seconds(value / 1000.0))
            .unwrap_or(Timestamp::UNIX_EPOCH)
    };
    let created_at = timestamp(&row["time_created"]);
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
        title: display_title(row, facts.and_then(|facts| facts.title.clone())),
        created_at,
        updated_at: if row["time_updated"].is_null() {
            created_at
        } else {
            timestamp(&row["time_updated"])
        },
        source_path: path.to_owned(),
        directory: text(&row["directory"]).into(),
        version: row["version"].clone(),
        model,
        project: v2
            .then(|| text(&row["project_id"]).trim().to_owned())
            .filter(|text| !text.is_empty()),
        message_count: facts.map(|facts| facts.count),
        subtargets: if v2 {
            Vec::new()
        } else {
            summary_targets(&row["summary_files"])
        },
        source_metadata: serde_json::json!({
            "schema": if v2 { "v2" } else { "legacy" },
            "row": row,
        }),
    }
}

fn summary_targets(raw: &Value) -> Vec<String> {
    let parsed;
    let value = if let Some(text) = raw.as_str() {
        if text.trim().is_empty() {
            return Vec::new();
        }
        parsed = crate::compat::json::from_str(text).unwrap_or(Value::Null);
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
                crate::providers::files::environment_root("HOME", "")?
                    .join(".zcode/cli/db/db.sqlite"),
            )])
        } else {
            Ok(Vec::new())
        };
    }
    let root = crate::providers::files::environment_root(
        "XDG_DATA_HOME",
        ".local/share",
    )?
    .join("opencode");
    if let Some(explicit) =
        crate::providers::files::environment_value("OPENCODE_DB")
    {
        return Ok(if explicit == ":memory:" {
            Vec::new()
        } else {
            vec![("OPENCODE_DB", root.join(explicit))]
        });
    }
    let mut paths = vec![("XDG/default opencode.db", root.join("opencode.db"))];
    if cfg!(target_os = "windows")
        && crate::providers::files::environment_value("XDG_DATA_HOME").is_none()
    {
        for name in ["LOCALAPPDATA", "APPDATA"] {
            if let Some(base) = crate::providers::files::environment_path(name)?
            {
                paths.push((
                    "LOCALAPPDATA/APPDATA compatibility",
                    base.join("opencode/opencode.db"),
                ));
                break;
            }
        }
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
    use std::fmt::Write as _;

    #[test]
    fn configuration_changes_retry_missing_sources_without_replacing_selected_database()
     {
        for kind in [Kind::OpenCode, Kind::ZCode] {
            for find_first in [false, true] {
                let directory = tempfile::tempdir().unwrap();
                let first = directory.path().join("first.sqlite");
                let second = directory.path().join("second.sqlite");
                fixture(&first, kind, false);
                fixture(&second, kind, false);
                let roots =
                    std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
                let mut provider = SqliteProvider {
                    kind,
                    database: None,
                    root: PathBuf::from("."),
                    search_roots: Box::new({
                        let roots = roots.clone();
                        move || Ok(roots.lock().unwrap().clone())
                    }),
                    readers: Readers::default(),
                };
                if find_first {
                    assert!(
                        provider
                            .find("kept", &mut |_| Ok(()))
                            .unwrap()
                            .session
                            .is_none()
                    );
                } else {
                    assert!(
                        !provider
                            .discover(Window::Created(36500), &mut |_| Ok(()))
                            .unwrap()
                            .available
                    );
                }
                *roots.lock().unwrap() = vec![("First", first.clone())];
                assert_eq!(
                    provider
                        .find("kept", &mut |_| Ok(()))
                        .unwrap()
                        .session
                        .unwrap()
                        .source_path,
                    first
                );
                *roots.lock().unwrap() = vec![("Second", second.clone())];
                assert_eq!(provider.search_roots().unwrap()[0].1, second);
                assert_eq!(
                    provider
                        .find("kept", &mut |_| Ok(()))
                        .unwrap()
                        .session
                        .unwrap()
                        .source_path,
                    first
                );
                assert_eq!(
                    provider
                        .discover(Window::Created(36500), &mut |_| Ok(()))
                        .unwrap()
                        .sessions[0]
                        .source_path,
                    first
                );
                std::fs::remove_file(&first).unwrap();
                assert!(provider.find("kept", &mut |_| Ok(())).is_err());
                assert!(!first.exists());
                assert_eq!(provider.source_root(), first.parent().unwrap());
            }
        }
    }

    #[test]
    fn database_selection_retries_absence_and_keeps_selected_database() {
        for kind in [Kind::OpenCode, Kind::ZCode] {
            for initial in ["absent", "primary", "fallback", "both"] {
                for find_first in [false, true] {
                    let directory = tempfile::tempdir().unwrap();
                    let primary =
                        directory.path().join("primary/source.sqlite");
                    let fallback =
                        directory.path().join("fallback/source.sqlite");
                    let mut provider = SqliteProvider {
                        kind,
                        database: None,
                        root: PathBuf::from("."),
                        search_roots: Box::new({
                            let primary = primary.clone();
                            let fallback = fallback.clone();
                            move || {
                                Ok(vec![
                                    ("Primary", primary.clone()),
                                    ("Fallback", fallback.clone()),
                                ])
                            }
                        }),
                        readers: Readers::default(),
                    };
                    for (path, present) in [
                        (&primary, matches!(initial, "primary" | "both")),
                        (&fallback, matches!(initial, "fallback" | "both")),
                    ] {
                        std::fs::create_dir_all(path.parent().unwrap())
                            .unwrap();
                        if present {
                            fixture(path, kind, false);
                            Connection::open(path)
                                .unwrap()
                                .execute("DELETE FROM session", [])
                                .unwrap();
                        }
                    }
                    if find_first {
                        assert!(
                            provider
                                .find("kept", &mut |_| panic!(
                                    "unexpected warning"
                                ))
                                .unwrap()
                                .session
                                .is_none()
                        );
                    } else {
                        let found = provider
                            .discover(Window::Created(36500), &mut |_| {
                                panic!("unexpected warning")
                            })
                            .unwrap();
                        assert_eq!(found.available, initial != "absent");
                        assert!(
                            found.sessions.is_empty()
                                && found.failures.is_empty()
                        );
                    }
                    for path in [&primary, &fallback] {
                        if path.exists() {
                            Connection::open(path)
                                .unwrap()
                                .execute_batch(
                                    "INSERT INTO session VALUES \
                                     ('kept', 'Kept', 1768478400000, \
                                     1768478400000, NULL, '/project', NULL, \
                                     NULL);",
                                )
                                .unwrap();
                        } else {
                            fixture(path, kind, false);
                        }
                    }
                    let expected = if initial == "fallback" {
                        &fallback
                    } else {
                        &primary
                    };
                    let session = provider
                        .find("kept", &mut |_| panic!("unexpected warning"))
                        .unwrap()
                        .session
                        .unwrap();
                    assert_eq!(&session.source_path, expected);
                    assert_eq!(
                        provider.source_root(),
                        expected.parent().unwrap()
                    );
                    let found = provider
                        .discover(Window::Created(36500), &mut |_| {
                            panic!("unexpected warning")
                        })
                        .unwrap();
                    assert!(found.available && found.failures.is_empty());
                    assert_eq!(found.sessions.len(), 1);
                    assert_eq!(&found.sessions[0].source_path, expected);

                    let saved = directory.path().join("removed.sqlite");
                    std::fs::rename(expected, &saved).unwrap();
                    assert!(
                        provider
                            .find("kept", &mut |_| panic!("unexpected warning"))
                            .is_err()
                    );
                    assert!(
                        provider
                            .discover(Window::Created(36500), &mut |_| panic!(
                                "unexpected warning"
                            ))
                            .is_err()
                    );
                    assert!(!expected.exists());
                    assert_eq!(
                        provider.source_root(),
                        expected.parent().unwrap()
                    );
                    std::fs::rename(saved, expected).unwrap();
                    let restored = provider
                        .find("kept", &mut |_| panic!("unexpected warning"))
                        .unwrap()
                        .session
                        .unwrap();
                    assert_eq!(&restored.source_path, expected);
                }
            }
        }
    }

    fn fixture(path: &Path, kind: Kind, v2: bool) -> SqliteProvider {
        let connection = Connection::open(path).unwrap();
        connection
            .execute_batch(
                "CREATE TABLE session (id TEXT, title TEXT, \
                 time_created INTEGER, time_updated INTEGER, slug TEXT, \
                 directory TEXT, version TEXT, summary_files TEXT); \
                 INSERT INTO session VALUES ('kept', 'Kept', 1768478400000, \
                 1768478400000, NULL, '/project', NULL, NULL);",
            )
            .unwrap();
        if v2 {
            connection
                .execute_batch(
                    "CREATE TABLE session_v2 (id TEXT, title TEXT, \
                     time_created INTEGER, time_updated INTEGER, slug TEXT, \
                     directory TEXT, version TEXT, summary_files TEXT, \
                     model TEXT, project_id TEXT, parent_id TEXT); \
                     INSERT INTO session_v2 VALUES ('kept', 'V2', \
                     1768478400000, 1768478400000, NULL, '/project', NULL, \
                     NULL, NULL, NULL, NULL);",
                )
                .unwrap();
        }
        SqliteProvider {
            kind,
            database: Some(path.into()),
            root: path.parent().unwrap().into(),
            search_roots: Box::new({
                let path = path.to_owned();
                move || Ok(vec![("Synthetic database", path.clone())])
            }),
            readers: Readers::default(),
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
            crate::providers::tests::assert_missing(
                error.as_ref(),
                summary,
                &path,
                &crate::providers::contract::source_roots(&provider).unwrap(),
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

    #[test]
    fn legacy_session_removed_after_lookup_is_missing() {
        for (kind, expected) in [
            (Kind::OpenCode, "OpenCode session is missing: kept"),
            (Kind::ZCode, "ZCode session is missing: kept"),
        ] {
            let directory = tempfile::tempdir().unwrap();
            let path = directory.path().join("source.sqlite");
            let mut provider = fixture(&path, kind, false);
            let session = provider
                .find("kept", &mut |_| Ok(()))
                .unwrap()
                .session
                .unwrap();
            Connection::open(&path)
                .unwrap()
                .execute_batch(
                    "DELETE FROM session; CREATE TABLE message (id TEXT, \
                     session_id TEXT, time_created INTEGER, data TEXT);",
                )
                .unwrap();
            let error = provider
                .read(&session, false, &mut |_| Ok(()))
                .err()
                .unwrap();
            assert_eq!(error.to_string(), expected);
        }
    }

    const LEGACY: &str = "CREATE TABLE session (id TEXT, title TEXT, \
        time_created INTEGER, time_updated INTEGER, slug TEXT, \
        directory TEXT, version TEXT, summary_files TEXT, parent_id TEXT); \
        CREATE TABLE message (id TEXT, session_id TEXT, \
        time_created INTEGER, data TEXT); \
        CREATE TABLE part (id TEXT, message_id TEXT, \
        time_created INTEGER, data TEXT);";

    fn database(sql: &str, kind: Kind) -> (tempfile::TempDir, SqliteProvider) {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("source.sqlite");
        Connection::open(&path).unwrap().execute_batch(sql).unwrap();
        let provider = SqliteProvider {
            kind,
            database: Some(path.clone()),
            root: directory.path().into(),
            search_roots: Box::new(move || {
                Ok(vec![("Synthetic", path.clone())])
            }),
            readers: Readers::default(),
        };
        (directory, provider)
    }

    fn message(
        id: &str,
        session: &str,
        time: i64,
        data: &str,
        parts: &[&str],
    ) -> String {
        let mut sql = format!(
            "INSERT INTO message VALUES ('{id}', '{session}', {time}, '{data}');"
        );
        for (index, part) in parts.iter().enumerate() {
            write!(
                sql,
                "INSERT INTO part VALUES \
                 ('{id}-{index}', '{id}', {time}, '{part}');"
            )
            .unwrap();
        }
        sql
    }

    fn listed(provider: &mut SqliteProvider) -> Vec<Session> {
        provider
            .discover(Window::All, &mut |_| Ok(()))
            .unwrap()
            .sessions
    }

    #[test]
    fn discovery_lists_reachable_sessions_with_visible_messages() {
        let text = |body: &str| format!(r#"{{"type":"text","text":"{body}"}}"#);
        let user = r#"{"role":"user"}"#;
        let assistant = r#"{"role":"assistant"}"#;
        let sql = [
            LEGACY.to_owned(),
            "INSERT INTO session VALUES \
             ('root', NULL, 10, NULL, NULL, '/p', NULL, NULL, NULL), \
             ('child', 'Child', 9, 9, NULL, '/p', NULL, NULL, 'root'), \
             ('orphan', 'Orphan', 8, 8, NULL, '/p', NULL, NULL, 'gone'), \
             ('empty', 'Empty', 7, 7, NULL, '/p', NULL, NULL, NULL), \
             ('quiet', NULL, 6, 6, NULL, '/p', NULL, NULL, NULL);"
                .into(),
            message(
                "u1",
                "root",
                1,
                user,
                &[&text(
                    r"<system-reminder>x</system-reminder>\n\n  First   line \nsecond",
                )],
            ),
            message("a1", "root", 2, assistant, &[r#"{"type":"step-start"}"#]),
            message(
                "p1",
                "root",
                3,
                r#"{"role":"assistant","type":"progress"}"#,
                &[&text("hidden")],
            ),
            message(
                "a2",
                "root",
                4,
                assistant,
                &[r#"{"type":"tool","title":"Tool: read","state":{}}"#],
            ),
            message("c1", "child", 1, assistant, &[&text("Done")]),
            message("o1", "orphan", 1, user, &[&text("Lost")]),
            message("e1", "empty", 1, assistant, &[r#"{"type":"step-finish"}"#]),
            message("q1", "quiet", 1, assistant, &[&text("ok")]),
        ]
        .concat();
        let (_directory, mut provider) = database(&sql, Kind::OpenCode);
        let sessions = listed(&mut provider);
        let facts: Vec<_> = sessions
            .iter()
            .map(|session| {
                (
                    session.id.as_str(),
                    session.title.as_str(),
                    session.message_count,
                )
            })
            .collect();
        assert_eq!(
            facts,
            [
                ("root", "First line", Some(2)),
                ("child", "Child", Some(1)),
                ("quiet", "Untitled Session", Some(1)),
            ]
        );
        assert_eq!(sessions[0].updated_at, sessions[0].created_at);
        let data = provider.read(&sessions[0], false, &mut |_| Ok(())).unwrap();
        assert_eq!(data.title, "First line");
        assert_eq!(data.stats.message_count, 2);
        let ids: Vec<_> = data
            .messages
            .iter()
            .map(|message| message.id.as_str())
            .collect();
        assert_eq!(ids, ["u1", "a2"]);
    }

    #[test]
    fn zcode_skips_subagent_children_without_parent_column() {
        let sql = [
            "CREATE TABLE session (id TEXT, title TEXT, time_created INTEGER, \
             time_updated INTEGER, slug TEXT, directory TEXT, version TEXT, \
             summary_files TEXT, task_type TEXT); \
             CREATE TABLE message (id TEXT, session_id TEXT, \
             time_created INTEGER, data TEXT); \
             CREATE TABLE part (id TEXT, message_id TEXT, \
             time_created INTEGER, data TEXT);",
            "INSERT INTO session VALUES \
             ('main', 'Main', 2, 2, NULL, '/p', NULL, NULL, 'main'), \
             ('sub', 'Sub', 1, 1, NULL, '/p', NULL, NULL, 'subagent_child');",
            &message(
                "m1",
                "main",
                1,
                r#"{"role":"user"}"#,
                &[r#"{"type":"text","text":"a"}"#],
            ),
            &message(
                "s1",
                "sub",
                1,
                r#"{"role":"user"}"#,
                &[r#"{"type":"text","text":"b"}"#],
            ),
        ]
        .concat();
        let (_directory, mut provider) = database(&sql, Kind::ZCode);
        let ids: Vec<_> = listed(&mut provider)
            .into_iter()
            .map(|session| session.id)
            .collect();
        assert_eq!(ids, ["main"]);
        assert!(
            provider
                .find("sub", &mut |_| Ok(()))
                .unwrap()
                .session
                .is_none()
        );
    }

    #[test]
    fn migration_cursor_keeps_only_uncopied_legacy_sessions() {
        let mut sql = [
            LEGACY,
            "CREATE TABLE session_v2 (id TEXT, title TEXT, \
             time_created INTEGER, time_updated INTEGER, slug TEXT, \
             directory TEXT, version TEXT, summary_files TEXT, model TEXT, \
             project_id TEXT, parent_id TEXT); \
             CREATE TABLE session_message (id TEXT, session_id TEXT, \
             type TEXT, seq INTEGER, time_created INTEGER, data TEXT); \
             CREATE TABLE kv (key TEXT, value TEXT);",
            "INSERT INTO session_v2 VALUES ('ses_c', 'C', 3, 3, NULL, '/p', \
             NULL, NULL, NULL, NULL, NULL); \
             INSERT INTO session_message VALUES \
             ('v1', 'ses_c', 'user', 1, 3, '{\"text\":\"hi\"}');",
            "INSERT INTO kv VALUES ('migration.v1-v2', \
             '{\"phase\":\"copying\",\"cursor\":\"ses_b\"}');",
        ]
        .concat();
        for id in ["ses_a", "ses_b", "ses_c"] {
            write!(
                sql,
                "INSERT INTO session VALUES \
                 ('{id}', '{id}', 1, 1, NULL, '/p', NULL, NULL, NULL);"
            )
            .unwrap();
            sql.push_str(&message(
                id,
                id,
                1,
                r#"{"role":"user"}"#,
                &[r#"{"type":"text","text":"hi"}"#],
            ));
        }
        let (directory, mut provider) = database(&sql, Kind::OpenCode);
        let ids = |provider: &mut SqliteProvider| -> Vec<String> {
            listed(provider)
                .into_iter()
                .map(|session| session.id)
                .collect()
        };
        assert_eq!(ids(&mut provider), ["ses_c", "ses_a"]);
        assert!(
            provider
                .find("ses_b", &mut |_| Ok(()))
                .unwrap()
                .session
                .is_none()
        );
        let legacy = provider
            .find("ses_a", &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap();
        assert!(provider.read(&legacy, false, &mut |_| Ok(())).is_ok());
        Connection::open(directory.path().join("source.sqlite"))
            .unwrap()
            .execute("UPDATE kv SET value = '{\"phase\":\"completed\"}'", [])
            .unwrap();
        assert_eq!(ids(&mut provider), ["ses_c"]);
        let error = provider
            .read(&legacy, false, &mut |_| Ok(()))
            .err()
            .unwrap();
        assert_eq!(error.to_string(), "OpenCode session is missing: ses_a");
    }

    #[test]
    fn legacy_usage_counts_cache_reasoning_and_descendants() {
        let text = r#"{"type":"text","text":"Done"}"#;
        let sql = [
            LEGACY,
            "INSERT INTO session VALUES \
             ('root', 'Root', 3, 3, NULL, '/p', NULL, NULL, NULL), \
             ('child', 'Child', 2, 2, NULL, '/p', NULL, NULL, 'root'), \
             ('grandchild', 'Grandchild', 1, 1, NULL, '/p', NULL, NULL, \
             'child');",
            &message(
                "r1",
                "root",
                1,
                concat!(
                    r#"{"role":"assistant","cost":0.5,"#,
                    r#""tokens":{"input":10,"output":5,"reasoning":2,"#,
                    r#""cache":{"read":3,"write":1}}}"#,
                ),
                &[text],
            ),
            &message(
                "c1",
                "child",
                1,
                concat!(
                    r#"{"role":"assistant","cost":0.25,"#,
                    r#""tokens":{"input":1,"output":1}}"#,
                ),
                &[text],
            ),
            &message(
                "g1",
                "grandchild",
                1,
                concat!(
                    r#"{"role":"assistant","cost":0.25,"#,
                    r#""tokens":{"input":1,"reasoning":1}}"#,
                ),
                &[],
            ),
        ]
        .concat();
        let (_directory, mut provider) = database(&sql, Kind::OpenCode);
        let root = provider
            .find("root", &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap();
        let stats = provider.read(&root, false, &mut |_| Ok(())).unwrap().stats;
        assert_eq!(
            (
                stats.message_count,
                stats.total_cost.as_f64(),
                stats.total_input_tokens.as_u64(),
                stats.total_output_tokens.as_u64(),
            ),
            (1, Some(1.0), Some(16), Some(9))
        );
    }
}
