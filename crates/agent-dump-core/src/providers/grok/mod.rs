mod transcript;

use crate::providers::contract::{Provider, RawExport, Window, source_roots};
use crate::providers::error::ProviderError;
use crate::providers::files::{
    self as file_sessions, SourceFiles, SourceRoots,
};
use crate::providers::kimi::title;
use crate::session::timestamp::Timestamp;
use crate::session::{Session, SessionData, parse_timestamp};
use serde_json::Value;
use std::path::{Path, PathBuf};

const SUMMARY: &str = "summary.json";
const UPDATES: &str = "updates.jsonl";

pub struct Grok {
    roots: SourceRoots,
}

fn string(value: &Value) -> Option<String> {
    value
        .as_str()
        .map(str::trim)
        .filter(|text| !text.is_empty())
        .map(str::to_owned)
}

fn timestamp(value: &Value) -> Option<Timestamp> {
    value.as_str().and_then(parse_timestamp)
}

fn model(session: &Session) -> Option<String> {
    string(&session.source_metadata["model"])
}

impl Grok {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; \
                  source access is deferred"
    )]
    pub fn open() -> crate::Result<Self> {
        Ok(Self {
            roots: SourceRoots::new(
                || file_sessions::environment_root("GROK_HOME", ".grok"),
                "sessions",
                "data/grok",
                "GROK_HOME/sessions",
            ),
        })
    }

    fn files(&mut self) -> crate::Result<SourceFiles> {
        self.roots.files(None, |path, _| {
            path.file_name().is_some_and(|name| name == SUMMARY)
        })
    }

    fn session(path: &Path) -> crate::Result<Option<Session>> {
        let Ok(summary) = crate::compat::json::from_slice(
            &crate::storage::source_io::read(path)?,
        ) else {
            return Ok(None);
        };
        let info = &summary["info"];
        let (Some(id), Some(directory)) =
            (string(&info["id"]), string(&info["cwd"]))
        else {
            return Ok(None);
        };
        let created_at = match timestamp(&summary["created_at"]) {
            Some(created_at) => created_at,
            None => Timestamp::try_from(path.metadata()?.modified()?)?,
        };
        let updated_at = timestamp(&summary["last_active_at"])
            .or_else(|| timestamp(&summary["updated_at"]))
            .unwrap_or(created_at);
        let initial = string(&summary["current_model_id"]);
        let updates = path.with_file_name(UPDATES);
        if !updates.exists() {
            return Ok(None);
        }
        let transcript = transcript::read(
            &updates,
            &id,
            created_at.as_millisecond(),
            initial.clone(),
            &mut |_| Ok(()),
        )?;
        if transcript.messages.is_empty() {
            return Ok(None);
        }
        let title = string(&summary["generated_title"])
            .or_else(|| string(&summary["session_summary"]))
            .and_then(|text| title(&text))
            .or(transcript.prompt)
            .or_else(|| crate::providers::title::basename(&directory))
            .unwrap_or_else(|| "Untitled Session".into());
        let source = path.parent().ok_or("Grok session has no directory")?;
        Ok(Some(Session {
            directory,
            model: transcript.model.unwrap_or_default(),
            message_count: Some(transcript.messages.len()),
            source_metadata: serde_json::json!({ "model": initial }),
            ..Session::new(id, title, source.to_owned(), created_at, updated_at)
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
                    "Confirm `updates.jsonl` in the Grok session directory \
                     has not been moved or cleaned up.",
                    "确认 Grok 会话目录中的 `updates.jsonl` 没有被移动或清理。",
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

impl Provider for Grok {
    fn discover(
        &mut self,
        window: Window,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Discovery> {
        file_sessions::discover(
            self.files()?,
            window,
            true,
            Self::session,
            |_, session, _| Ok(session),
        )
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Lookup> {
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
            Self::session,
        )
    }

    fn read(
        &self,
        session: &Session,
        _zh: bool,
        diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        let path = session.source_path.join(UPDATES);
        if !path.is_file() {
            return Err(self.missing("session source file is missing", &path)?);
        }
        let transcript = transcript::read(
            &path,
            &session.id,
            session.created_at.as_millisecond(),
            model(session),
            diagnostics,
        )?;
        Ok(session.payload(transcript.messages, transcript.stats))
    }

    fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>> {
        self.roots.search_roots()
    }

    fn change_sources(&self, session: &Session) -> Vec<PathBuf> {
        vec![
            session.source_path.join(SUMMARY),
            session.source_path.join(UPDATES),
        ]
    }

    fn source_root(&self) -> &Path {
        self.roots.owned()
    }

    fn select_source(&mut self) -> crate::Result<Option<&Path>> {
        self.roots.select()
    }

    fn raw_export(&self, session: &Session) -> crate::Result<RawExport> {
        let path = session.source_path.join(UPDATES);
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
        crate::providers::tests::source_selection(
            "sessions",
            false,
            |roots| Grok { roots },
            |base| {
                let path = base.join("project/kept");
                std::fs::create_dir_all(&path).unwrap();
                std::fs::write(
                    path.join(SUMMARY),
                    r#"{"info":{"id":"kept","cwd":"/workspace"}}"#,
                )
                .unwrap();
                std::fs::write(
                    path.join(UPDATES),
                    concat!(
                        r#"{"params":{"update":{"#,
                        r#""sessionUpdate":"user_message_chunk","#,
                        r#""content":{"type":"text","text":"Keep"}}}}"#,
                    ),
                )
                .unwrap();
                path
            },
        );
    }
}
