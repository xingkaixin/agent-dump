mod log;
mod transcript;

use crate::compat::value::{integer, text};
use crate::providers::contract::{
    DiagnosticSink, Discovery, Lookup, Provider, Window, source_roots,
};
use crate::providers::error::ProviderError;
use crate::providers::files::{
    self as file_sessions, SourceFiles, SourceRoots,
};
use crate::session::timestamp::Timestamp;
use crate::session::{Session, SessionData, Stats, epoch_seconds};
use std::collections::{BTreeMap, HashSet};
use std::path::{Path, PathBuf};
use std::time::SystemTime;

pub struct Dsh {
    roots: SourceRoots,
}

#[allow(
    clippy::cast_precision_loss,
    reason = "DSH stores times as safe integers, which f64 holds exactly"
)]
fn timestamp(milliseconds: i64) -> crate::Result<Timestamp> {
    epoch_seconds(milliseconds as f64 / 1000.0)
        .ok_or_else(|| "DSH session time is out of range".into())
}

/// A session migrated to a newer format keeps its older files beside the new
/// one, so each session directory contributes its newest generation.
fn newest(paths: Vec<PathBuf>) -> Vec<PathBuf> {
    let mut newest: BTreeMap<PathBuf, ((u64, SystemTime), PathBuf)> =
        BTreeMap::new();
    for path in paths {
        let Some((version, _)) = path
            .file_name()
            .and_then(|name| log::generation(&name.to_string_lossy()))
        else {
            continue;
        };
        let Ok(metadata) = std::fs::metadata(&path) else {
            continue;
        };
        let Ok(modified) = metadata.modified() else {
            continue;
        };
        if !metadata.is_file() {
            continue;
        }
        let order = (version, modified);
        let directory = path.parent().unwrap_or(&path).to_owned();
        if newest
            .get(&directory)
            .is_none_or(|(latest, _)| order > *latest)
        {
            newest.insert(directory, (order, path));
        }
    }
    newest.into_values().map(|(_, path)| path).collect()
}

/// DSH files a session under directories named after its working directory
/// and id; a log found anywhere else is not that session.
fn filed(sessions: &Path, path: &Path, header: &serde_json::Value) -> bool {
    let project = if header.get("cwd").is_some() {
        log::project(text(&header["cwd"]))
    } else {
        Some("_no-cwd".into())
    };
    let (Some(project), Some(id), Some(name)) =
        (project, log::encode(text(&header["id"])), path.file_name())
    else {
        return false;
    };
    let expected = sessions.join(project).join(id).join(name);
    path == expected
        || matches!(
            (path.canonicalize(), expected.canonicalize()),
            (Ok(path), Ok(expected)) if path == expected
        )
}

impl Dsh {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; source access is deferred"
    )]
    pub fn open() -> crate::Result<Self> {
        Ok(Self {
            roots: SourceRoots::new(
                || file_sessions::environment_root("DSH_HOME", ".dsh"),
                "sessions",
                "data/dsh",
                "DSH_HOME/sessions",
            ),
        })
    }

    fn files(&mut self) -> crate::Result<SourceFiles> {
        let mut files = self.roots.files(Some(3), |path, base| {
            path.file_name().is_some_and(|name| {
                log::generation(&name.to_string_lossy()).is_some()
            }) && path
                .strip_prefix(base)
                .is_ok_and(|path| path.components().count() == 3)
        })?;
        files.paths = newest(files.paths);
        Ok(files)
    }

    fn scan(sessions: &Path, path: &Path) -> crate::Result<Option<Session>> {
        let Some(log) =
            log::read(path)?.filter(|log| filed(sessions, path, &log.header))
        else {
            return Ok(None);
        };
        let Some(transcript) = transcript::project(&log, None) else {
            return Ok(None);
        };
        if transcript.messages.is_empty() {
            return Ok(None);
        }
        let header = &log.header;
        let directory = text(&header["cwd"]).to_owned();
        let title = transcript
            .title
            .as_deref()
            .and_then(transcript::title)
            .or_else(|| crate::providers::title::basename(&directory))
            .unwrap_or_else(|| "Untitled Session".into());
        Ok(Some(Session {
            directory,
            model: transcript.model.unwrap_or_default(),
            message_count: Some(transcript.messages.len()),
            ..Session::new(
                text(&header["id"]).to_owned(),
                title,
                path.to_owned(),
                timestamp(integer(&header["createdAt"]))?,
                timestamp(transcript.updated)?,
            )
        }))
    }

    fn missing(&self, path: &Path) -> crate::Result<crate::Error> {
        Ok(ProviderError::missing(
            ["session source file is missing"; 2],
            path,
            Vec::new(),
            source_roots(self)?,
            vec![
                [
                    "Confirm the DSH session log has not been moved or cleaned up.",
                    "确认 DSH 会话日志没有被移动或清理。",
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

impl Provider for Dsh {
    fn discover(
        &mut self,
        window: Window,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Discovery> {
        let files = self.files()?;
        let sessions = self.roots.base.clone().unwrap_or_default();
        let mut seen = HashSet::new();
        file_sessions::discover(
            files,
            window,
            true,
            |path| Self::scan(&sessions, path),
            |_, session, _| {
                Ok(session.filter(|session| seen.insert(session.id.clone())))
            },
        )
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Lookup> {
        let files = self.files()?;
        let sessions = self.roots.base.clone();
        let directory = log::encode(id);
        file_sessions::find(
            sessions.as_deref(),
            files,
            id,
            |path| {
                path.parent().and_then(Path::file_name).is_some_and(|name| {
                    directory
                        .as_deref()
                        .is_some_and(|directory| name == directory)
                })
            },
            |path| {
                let sessions = sessions.as_deref();
                Self::scan(sessions.unwrap_or_else(|| Path::new("")), path)
            },
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
        let log = log::read(path)?.ok_or("invalid DSH session log")?;
        // <root>/sessions/<project>/<session>/<log>
        let attachments = path
            .ancestors()
            .nth(4)
            .map(|root| root.join("attachments/v1"));
        let transcript = transcript::project(&log, attachments.as_deref())
            .ok_or("invalid DSH session log")?;
        let mut messages = transcript.messages;
        crate::providers::text::clean_messages(&mut messages);
        let (input, output) = (transcript.input, transcript.output);
        let stats = Stats {
            message_count: messages.len(),
            total_input_tokens: input.into(),
            total_output_tokens: output.into(),
            total_tokens: Some(input.saturating_add(output).into()),
            ..Stats::default()
        };
        Ok(session.payload(messages, stats))
    }

    fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>> {
        self.roots.search_roots()
    }

    fn source_root(&self) -> &Path {
        self.roots.owned()
    }

    fn select_source(&mut self) -> crate::Result<Option<&Path>> {
        self.roots.select()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_selection_retries_absence_and_keeps_selected_root() {
        crate::providers::source_tests::source_selection(
            "sessions",
            false,
            |roots| Dsh { roots },
            |base| {
                let path = base.join("_no-cwd/kept/session.jsonl");
                std::fs::create_dir_all(path.parent().unwrap()).unwrap();
                std::fs::write(
                    &path,
                    concat!(
                        r#"{"type":"session","version":0,"id":"kept","createdAt":1768478400000,"delegationDepth":0}"#,
                        "\n",
                        r#"{"type":"user/message","seq":0,"time":1768478400000,"surfaceOp":"append","data":{"source":{"kind":"user"},"content":[{"type":"text","text":"Keep"}]}}"#,
                        "\n",
                    ),
                )
                .unwrap();
                path
            },
        );
    }
}
