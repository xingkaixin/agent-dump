mod proto;
mod transcript;

use crate::output::formats::OutputFormat;
use crate::providers::contract::{
    DiagnosticSink, Discovery, Lookup, Provider, source_roots,
};
use crate::providers::error::ProviderError;
use crate::providers::files::{
    self as file_sessions, Located, SourceFiles, SourceRoots,
};
use crate::providers::sqlite::connection::{change_sources, connect};
use crate::session::timestamp::Timestamp;
use crate::session::{Part, Session, SessionData, Stats};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use transcript::Transcript;

const SUMMARIES: &str = "conversation_summaries.db";

pub struct AntigravityCli {
    roots: SourceRoots,
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

fn directory(workspaces: &str) -> Option<String> {
    serde_json::from_str::<Vec<String>>(workspaces)
        .ok()?
        .into_iter()
        .find_map(|uri| url::Url::parse(&uri).ok()?.to_file_path().ok())
        .map(|path| crate::storage::source_io::path_text(&path))
}

fn read_summaries(
    conversations: Option<&Path>,
) -> crate::Result<HashMap<String, Summary>> {
    let mut summaries = HashMap::new();
    let Some(conversations) = conversations else {
        return Ok(summaries);
    };
    let path = conversations
        .parent()
        .unwrap_or(conversations)
        .join(SUMMARIES);
    if !path.is_file() {
        return Ok(summaries);
    }
    let connection = connect(&path)?;
    let mut statement = connection.prepare(
        "SELECT conversation_id, title, workspace_uris, last_modified_time FROM conversation_summaries",
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

fn load(path: &Path, fallback: i64) -> crate::Result<Option<Transcript>> {
    let connection = connect(path)?;
    let mut transcript = transcript::read(&connection, &stem(path), fallback)?;
    if transcript.messages.is_empty() && transcript.unsupported == 0 {
        return Ok(None);
    }
    crate::providers::text::clean_messages(&mut transcript.messages);
    Ok(Some(transcript))
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
    let Some(transcript) = load(path, fallback)? else {
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
        directory: summary
            .map(|summary| summary.directory.clone())
            .unwrap_or_default(),
        model: transcript.model.unwrap_or_default(),
        message_count: Some(transcript.messages.len()),
        source_metadata: serde_json::json!({ "fallback_time": fallback }),
        ..Session::new(id, title, path.to_owned(), created, updated)
    }))
}

impl AntigravityCli {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; source access is deferred"
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
        })
    }

    fn files(&mut self) -> crate::Result<SourceFiles> {
        self.roots.files(None, |path, _| {
            path.extension().is_some_and(|extension| extension == "db")
        })
    }

    fn missing(&self, path: &Path) -> crate::Result<crate::Error> {
        Ok(ProviderError::missing(
            ["session source file is missing"; 2],
            path,
            Vec::new(),
            source_roots(self)?,
            vec![
                [
                    "Confirm the Antigravity CLI conversation database has not been moved or cleaned up.",
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
        days: Option<i64>,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Discovery> {
        let files = self.files()?;
        let summaries = read_summaries(self.roots.base.as_deref())?;
        // Native step times can be newer than a WAL database's file time.
        file_sessions::discover(
            files,
            days,
            false,
            |path| session(path, &summaries),
            |_, session, _| Ok(session),
        )
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Lookup> {
        let files = self.files()?;
        let summaries = read_summaries(self.roots.base.as_deref())?;
        file_sessions::find(
            self.roots.base.as_deref(),
            files,
            id,
            |path| stem(path) == id,
            |path| session(path, &summaries),
        )
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
        let transcript = load(path, fallback)?.unwrap_or_default();
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
        self.roots.search_roots()
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
