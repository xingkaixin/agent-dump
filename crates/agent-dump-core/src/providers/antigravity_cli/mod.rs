mod proto;
mod transcript;

use crate::output::formats::OutputFormat;
use crate::providers::contract::{
    DiagnosticSink, Discovery, Lookup, Provider, SessionFailure, Window,
    source_roots,
};
use crate::providers::error::ProviderError;
use crate::providers::files::{self as file_sessions, Located, SourceRoots};
use crate::providers::sqlite::connection::{
    change_sources, connect, has_table,
};
use crate::session::timestamp::Timestamp;
use crate::session::{Part, Session, SessionData, Stats};
use proto::Message as _;
use rusqlite::Connection;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use transcript::Transcript;

const SUMMARIES: &str = "conversation_summaries.db";

pub struct AntigravityCli {
    roots: SourceRoots,
    profiles: Box<dyn Fn() -> crate::Result<Option<PathBuf>> + Send + Sync>,
}

#[derive(Default)]
struct Summary {
    title: Option<String>,
    directory: String,
    time: Option<i64>,
}

fn stem(path: &Path) -> String {
    path.file_stem()
        .unwrap_or_default()
        .to_string_lossy()
        .into_owned()
}

fn directory(workspaces: Vec<String>) -> Option<String> {
    workspaces
        .into_iter()
        .find_map(|uri| url::Url::parse(&uri).ok()?.to_file_path().ok())
        .map(|path| crate::storage::source_io::path_text(&path))
}

fn read_summaries(
    conversations: &Path,
) -> crate::Result<HashMap<String, Summary>> {
    let mut summaries = HashMap::new();
    let path = conversations
        .parent()
        .unwrap_or(conversations)
        .join(SUMMARIES);
    if !path.is_file() {
        return Ok(summaries);
    }
    let connection = connect(&path)?;
    let mut statement = connection.prepare(
        "SELECT conversation_id, title, workspace_uris, last_modified_time \
         FROM conversation_summaries",
    )?;
    let mut rows = statement.query([])?;
    while let Some(row) = rows.next()? {
        let modified = row.get::<_, Option<String>>(3)?;
        summaries.insert(
            row.get(0)?,
            Summary {
                title: row.get(1)?,
                directory: row
                    .get::<_, Option<String>>(2)?
                    .as_deref()
                    .and_then(|uris| serde_json::from_str(uris).ok())
                    .and_then(directory)
                    .unwrap_or_default(),
                time: modified
                    .and_then(|time| time.replacen(' ', "T", 1).parse().ok())
                    .map(Timestamp::as_millisecond),
            },
        );
    }
    Ok(summaries)
}

fn timestamp(milliseconds: i64) -> crate::Result<Timestamp> {
    Timestamp::from_microsecond(
        milliseconds
            .checked_mul(1000)
            .ok_or("Antigravity CLI time is out of range")?,
    )
}

fn load(
    connection: &Connection,
    id: &str,
    fallback: i64,
) -> crate::Result<Option<Transcript>> {
    let mut transcript = transcript::read(connection, id, fallback)?;
    if transcript.messages.is_empty() && transcript.unsupported == 0 {
        return Ok(None);
    }
    crate::providers::text::clean_messages(&mut transcript.messages);
    Ok(Some(transcript))
}

fn trajectory_directory(
    connection: &Connection,
) -> crate::Result<Option<String>> {
    if !has_table(connection, "trajectory_metadata_blob")? {
        return Ok(None);
    }
    let mut statement =
        connection.prepare("SELECT data FROM trajectory_metadata_blob")?;
    let mut rows = statement.query([])?;
    while let Some(row) = rows.next()? {
        let metadata =
            proto::TrajectoryMetadata::decode(&row.get::<_, Vec<u8>>(0)?)
                .map_err(|error| {
                    format!(
                        "invalid Antigravity CLI workspace metadata: {error}"
                    )
                })?;
        if let Some(directory) = directory(metadata.workspaces) {
            return Ok(Some(directory));
        }
    }
    Ok(None)
}

fn session(
    path: &Path,
    summaries: &HashMap<String, Summary>,
) -> crate::Result<Option<Session>> {
    let id = stem(path);
    let summary = summaries.get(&id);
    let fallback = match summary.and_then(|summary| summary.time) {
        Some(time) => time,
        None => {
            Timestamp::try_from(path.metadata()?.modified()?)?.as_millisecond()
        }
    };
    let connection = connect(path)?;
    let Some(transcript) = load(&connection, &id, fallback)? else {
        return Ok(None);
    };
    let prompt = transcript
        .messages
        .iter()
        .find(|message| message.role == "user")
        .and_then(|message| message.parts.first())
        .and_then(Part::content);
    let title = [
        transcript
            .title
            .as_deref()
            .or_else(|| summary.and_then(|summary| summary.title.as_deref())),
        prompt,
    ]
    .into_iter()
    .flatten()
    .find_map(crate::providers::kimi::title)
    .unwrap_or_else(|| "Untitled Session".into());
    let times = transcript
        .messages
        .iter()
        .map(|message| message.time_created);
    let created = timestamp(times.clone().fold(fallback, i64::min))?;
    let updated = timestamp(times.fold(fallback, i64::max))?;
    Ok(Some(Session {
        directory: match summary
            .map(|summary| &summary.directory)
            .filter(|directory| !directory.is_empty())
        {
            Some(directory) => directory.clone(),
            None => trajectory_directory(&connection)?.unwrap_or_default(),
        },
        model: transcript.model.unwrap_or_default(),
        message_count: Some(transcript.messages.len()),
        source_metadata: serde_json::json!({ "fallback_time": fallback }),
        ..Session::new(id, title, path.to_owned(), created, updated)
    }))
}

impl AntigravityCli {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; \
                  source access is deferred"
    )]
    pub fn open() -> crate::Result<Self> {
        Ok(Self {
            roots: SourceRoots::located(
                || {
                    let sessions = match file_sessions::environment_path(
                        "AGY_CONVERSATIONS_DIR",
                    )? {
                        Some(path) => path,
                        None => file_sessions::environment_root(
                            "HOME",
                            ".gemini/antigravity-cli",
                        )?
                        .join("conversations"),
                    };
                    Ok(Located {
                        owner: sessions
                            .parent()
                            .filter(|owner| !owner.as_os_str().is_empty())
                            .unwrap_or(&sessions)
                            .to_owned(),
                        sessions,
                        label: "AGY_CONVERSATIONS_DIR",
                    })
                },
                "data/antigravity-cli/conversations",
            ),
            profiles: Box::new(|| {
                if file_sessions::environment_value("AGY_CONVERSATIONS_DIR")
                    .is_some()
                {
                    return Ok(None);
                }
                Ok(Some(
                    file_sessions::environment_root("T3CODE_HOME", ".t3")?
                        .join("userdata/providers/antigravity"),
                ))
            }),
        })
    }

    fn stores(&mut self) -> crate::Result<(Vec<PathBuf>, Vec<SessionFailure>)> {
        self.roots.select()?;
        let mut stores: Vec<_> = self.roots.base.clone().into_iter().collect();
        let mut failures = Vec::new();
        if let Some(profiles) = (self.profiles)()? {
            let entries = match std::fs::read_dir(&profiles) {
                Ok(entries) => entries,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    return Ok((stores, failures));
                }
                Err(error) => {
                    failures.push(SessionFailure {
                        source: crate::storage::source_io::path_text(&profiles),
                        error: error.into(),
                    });
                    return Ok((stores, failures));
                }
            };
            for entry in entries {
                match entry.and_then(|entry| {
                    Ok(entry.file_type()?.is_dir().then(|| {
                        entry.path().join("antigravity-acp/conversations")
                    }))
                }) {
                    Ok(Some(path)) => stores.push(path),
                    Ok(None) => {}
                    Err(error) => failures.push(SessionFailure {
                        source: crate::storage::source_io::path_text(&profiles),
                        error: error.into(),
                    }),
                }
            }
        }
        stores.sort();
        Ok((stores, failures))
    }

    fn missing(&self, path: &Path) -> crate::Result<crate::Error> {
        Ok(ProviderError::missing(
            ["session source file is missing"; 2],
            path,
            Vec::new(),
            source_roots(self)?,
            vec![
                [
                    "Confirm the Antigravity CLI conversation database has \
                     not been moved or cleaned up.",
                    "确认 Antigravity CLI 会话数据库没有被移动或清理。",
                ],
                [
                    "Re-run `agent-dump --list` to check whether the session is still visible.",
                    "重新运行 `agent-dump --list` 检查该会话是否仍可见。",
                ],
            ],
        )
        .into())
    }
}

impl Provider for AntigravityCli {
    fn discover(
        &mut self,
        window: Window,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Discovery> {
        let (stores, failures) = self.stores()?;
        let mut discovery = Discovery {
            failures,
            ..Discovery::default()
        };
        for store in stores {
            let result = (|| {
                let files = file_sessions::files(&store, None, |path, _| {
                    path.extension().is_some_and(|extension| extension == "db")
                })?;
                let summaries = read_summaries(&store)?;
                // Native step times can be newer than a WAL database's file time.
                file_sessions::discover(
                    files,
                    window,
                    false,
                    |path| session(path, &summaries),
                    |_, session, _| Ok(session),
                )
            })();
            match result {
                Ok(found) => {
                    discovery.available |= found.available;
                    discovery.sessions.extend(found.sessions);
                    discovery.failures.extend(found.failures);
                }
                Err(error) => discovery.failures.push(SessionFailure {
                    source: crate::storage::source_io::path_text(&store),
                    error,
                }),
            }
        }
        discovery
            .sessions
            .sort_by(|a, b| b.created_at.cmp(&a.created_at));
        Ok(discovery)
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Lookup> {
        let (stores, failures) = self.stores()?;
        let mut lookup = Lookup {
            failures,
            ..Lookup::default()
        };
        for store in stores {
            let result = (|| {
                let files = file_sessions::files(&store, None, |path, _| {
                    path.extension().is_some_and(|extension| extension == "db")
                })?;
                let summaries = read_summaries(&store)?;
                file_sessions::find(
                    Some(&store),
                    files,
                    id,
                    |path| stem(path) == id,
                    |path| session(path, &summaries),
                )
            })();
            match result {
                Ok(found) => {
                    lookup.failures.extend(found.failures);
                    if found.session.is_some() {
                        lookup.session = found.session;
                        break;
                    }
                }
                Err(error) => lookup.failures.push(SessionFailure {
                    source: crate::storage::source_io::path_text(&store),
                    error,
                }),
            }
        }
        Ok(lookup)
    }

    fn read(
        &self,
        session: &Session,
        _zh: bool,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        let path = &session.source_path;
        if !path.is_file() {
            return Err(self.missing(path)?);
        }
        let fallback = session.source_metadata["fallback_time"]
            .as_i64()
            .unwrap_or_else(|| session.updated_at.as_millisecond());
        let transcript =
            load(&connect(path)?, &session.id, fallback)?.unwrap_or_default();
        let stats = Stats {
            message_count: transcript.messages.len(),
            total_input_tokens: transcript.input.into(),
            total_output_tokens: transcript.output.into(),
            total_tokens: transcript.total.map(Into::into),
            ..Stats::default()
        };
        Ok(session.payload(transcript.messages, stats))
    }

    fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>> {
        let mut roots = self.roots.search_roots()?;
        if let Some(profiles) = (self.profiles)()? {
            roots.push(("T3CODE_HOME", profiles));
        }
        Ok(roots)
    }

    fn protected_roots(&mut self) -> crate::Result<Vec<PathBuf>> {
        let mut roots: Vec<_> = self
            .roots
            .select()?
            .into_iter()
            .map(Path::to_owned)
            .collect();
        if let Some(profiles) = (self.profiles)()? {
            roots.push(profiles);
        }
        Ok(roots)
    }

    fn change_sources(&self, session: &Session) -> Vec<PathBuf> {
        change_sources(&session.source_path)
    }

    fn source_root(&self) -> &Path {
        self.roots.owned()
    }

    fn select_source(&mut self) -> crate::Result<Option<&Path>> {
        self.roots.select()
    }

    fn supports_format(&self, format: OutputFormat) -> bool {
        format != OutputFormat::Raw
    }
}

#[cfg(test)]
mod tests;
