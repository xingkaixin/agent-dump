pub(super) mod wire;

use crate::providers::contract::{Provider, RawExport, Window, source_roots};
use crate::providers::error::ProviderError;
use crate::providers::files::{
    self as file_sessions, SourceFiles, SourceRoots,
};
use crate::providers::kimi::{timestamp, title};
use crate::session::timestamp::Timestamp;
use crate::session::{Session, SessionData, Stats};
use serde_json::Value;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

const WIRE: &str = "agents/main/wire.jsonl";

pub struct KimiCode {
    roots: SourceRoots,
    work_dirs: Option<HashMap<PathBuf, String>>,
}

struct Scan {
    state: Value,
    message_count: usize,
    prompt: Option<String>,
    model: Option<String>,
}

fn modified(path: &Path) -> crate::Result<Timestamp> {
    Timestamp::try_from(path.metadata()?.modified()?)
}

fn work_dirs(sessions: &Path) -> HashMap<PathBuf, String> {
    let mut work_dirs = HashMap::new();
    let index = sessions
        .parent()
        .unwrap_or(sessions)
        .join("session_index.jsonl");
    if index.is_file() {
        // The index only fills a missing working directory, so an unreadable
        // index leaves sessions listed without one.
        crate::providers::jsonl::scan(&index, &mut |_| Ok(()), |record, _| {
            if let (Some(session), Some(cwd)) =
                (record["sessionDir"].as_str(), record["workDir"].as_str())
                && let Ok(session) = std::path::absolute(session)
            {
                work_dirs.insert(session, cwd.to_owned());
            }
            Ok(())
        })
        .ok();
    }
    work_dirs
}

impl KimiCode {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; \
                  source access is deferred"
    )]
    pub fn open() -> crate::Result<Self> {
        Ok(Self {
            roots: SourceRoots::new(
                || {
                    file_sessions::environment_root(
                        "KIMI_CODE_HOME",
                        ".kimi-code",
                    )
                },
                "sessions",
                "data/kimi-code",
                "KIMI_CODE_HOME/sessions",
            ),
            work_dirs: None,
        })
    }

    fn files(&mut self) -> crate::Result<SourceFiles> {
        self.roots.files(Some(3), |path, base| {
            path.file_name().is_some_and(|name| name == "state.json")
                && path
                    .strip_prefix(base)
                    .is_ok_and(|path| path.components().count() == 3)
                && path
                    .parent()
                    .is_some_and(|session| session.join(WIRE).is_file())
        })
    }

    fn scan(path: &Path) -> crate::Result<Scan> {
        let state = crate::compat::json::from_slice(
            &crate::storage::source_io::read(path)?,
        )?;
        if !state.is_object() {
            return Err("session state must be a JSON object".into());
        }
        let session =
            path.parent().ok_or("Kimi-Code session has no directory")?;
        let transcript = wire::read(&session.join(WIRE), &mut |_| Ok(()))?;
        Ok(Scan {
            state,
            message_count: transcript.messages.len(),
            prompt: transcript.prompt,
            model: transcript.model,
        })
    }

    fn work_dir(&mut self, session: &Path) -> String {
        let sessions = self.roots.base.clone();
        let work_dirs = self.work_dirs.get_or_insert_with(|| {
            sessions.as_deref().map(work_dirs).unwrap_or_default()
        });
        std::path::absolute(session)
            .ok()
            .and_then(|session| work_dirs.get(&session).cloned())
            .unwrap_or_default()
    }

    fn parse(
        &mut self,
        path: &Path,
        scan: Scan,
    ) -> crate::Result<Option<Session>> {
        if scan.message_count == 0 {
            return Ok(None);
        }
        let session =
            path.parent().ok_or("Kimi-Code session has no directory")?;
        let state = &scan.state;
        let created_at = match timestamp(&state["createdAt"])
            .or_else(|| timestamp(&state["created_at"]))
        {
            Some(created_at) => created_at,
            None => modified(path)?,
        };
        let updated_at = timestamp(&state["updatedAt"])
            .or_else(|| timestamp(&state["updated_at"]))
            .unwrap_or(created_at)
            .max(modified(&session.join(WIRE))?);
        let title = title(
            state["title"]
                .as_str()
                .or_else(|| state["customTitle"].as_str())
                .unwrap_or_default(),
        )
        .or(scan.prompt)
        .unwrap_or_else(|| "Untitled Session".into());
        let directory = match state["workDir"]
            .as_str()
            .or_else(|| state["custom"]["cwd"].as_str())
        {
            Some(directory) => directory.to_owned(),
            None => self.work_dir(session),
        };
        let id = session
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned();
        Ok(Some(Session {
            directory,
            model: scan.model.unwrap_or_default(),
            message_count: Some(scan.message_count),
            ..Session::new(
                id,
                title,
                session.to_owned(),
                created_at,
                updated_at,
            )
        }))
    }

    fn missing(
        &self,
        summary: &'static str,
        path: &Path,
    ) -> crate::Result<crate::Error> {
        Ok(ProviderError::missing(
            [summary; 2],
            path,
            Vec::new(),
            source_roots(self)?,
            vec![
                [
                    "Confirm `agents/main/wire.jsonl` in the Kimi-Code \
                     session directory has not been moved or cleaned up.",
                    "确认 Kimi-Code 会话目录中的 \
                     `agents/main/wire.jsonl` 没有被移动或清理。",
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

impl Provider for KimiCode {
    fn discover(
        &mut self,
        window: Window,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Discovery> {
        self.work_dirs = None;
        file_sessions::discover(
            self.files()?,
            window,
            // updated_at follows wire.jsonl, which can be newer than state.json.
            !matches!(window, Window::Updated(_)),
            Self::scan,
            |path, scan, _| self.parse(path, scan),
        )
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Lookup> {
        self.work_dirs = None;
        let files = self.files()?;
        file_sessions::find(
            self.roots.base.clone().as_deref(),
            files,
            id,
            |path| {
                path.parent()
                    .and_then(Path::file_name)
                    .is_some_and(|name| name == id)
            },
            |path| self.parse(path, Self::scan(path)?),
        )
    }

    fn read(
        &self,
        session: &Session,
        _zh: bool,
        diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        let path = session.source_path.join(WIRE);
        if !path.is_file() {
            return Err(self.missing("session source file is missing", &path)?);
        }
        let transcript = wire::read(&path, diagnostics)?;
        let mut messages = transcript.messages;
        crate::providers::text::clean_messages(&mut messages);
        let stats = Stats {
            message_count: messages.len(),
            total_input_tokens: transcript.input.into(),
            total_output_tokens: transcript.output.into(),
            total_tokens: Some(
                transcript.input.saturating_add(transcript.output).into(),
            ),
            ..Stats::default()
        };
        Ok(session.payload(messages, stats))
    }

    fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>> {
        self.roots.search_roots()
    }

    fn change_sources(&self, session: &Session) -> Vec<PathBuf> {
        vec![
            session.source_path.join("state.json"),
            session.source_path.join(WIRE),
        ]
    }

    fn source_root(&self) -> &Path {
        self.roots.owned()
    }

    fn select_source(&mut self) -> crate::Result<Option<&Path>> {
        self.roots.select()
    }

    fn raw_export(&self, session: &Session) -> crate::Result<RawExport> {
        let path = session.source_path.join(WIRE);
        if !path.is_file() {
            return Err(self.missing("raw session source is missing", &path)?);
        }
        Ok(RawExport::File(path))
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
            |roots| KimiCode {
                roots,
                work_dirs: None,
            },
            |base| {
                let path = base.join("hash/kept");
                std::fs::create_dir_all(path.join("agents/main")).unwrap();
                std::fs::write(path.join("state.json"), "{}").unwrap();
                std::fs::write(
                    path.join(WIRE),
                    concat!(
                        r#"{"type":"context.append_message","#,
                        r#""message":{"role":"user","content":"Keep"}}"#,
                    ),
                )
                .unwrap();
                path
            },
        );
    }
}
