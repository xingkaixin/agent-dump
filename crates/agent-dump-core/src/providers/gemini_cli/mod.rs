mod chat;

use crate::providers::contract::{
    DiagnosticSink, Discovery, Lookup, Provider, source_roots,
};
use crate::providers::error::ProviderError;
use crate::providers::files::{
    self as file_sessions, SourceFiles, SourceRoots,
};
use crate::session::{Session, SessionData, Stats};
use std::path::{Path, PathBuf};

pub struct GeminiCli {
    roots: SourceRoots,
}

fn data_root() -> crate::Result<PathBuf> {
    match file_sessions::environment_path("GEMINI_CLI_HOME")? {
        Some(home) => Ok(home.join(".gemini")),
        None => file_sessions::environment_root("HOME", ".gemini"),
    }
}

/// Chats live in `<project>/chats/`, and subagent chats one level deeper in
/// `<project>/chats/<parent session id>/`. A legacy `.json` chat resumed as
/// `.jsonl` keeps both files, so only the `.jsonl` one counts.
fn is_source(base: &Path, path: &Path) -> bool {
    let Ok(relative) = path.strip_prefix(base) else {
        return false;
    };
    let components: Vec<_> = relative.components().collect();
    matches!(components.len(), 3 | 4)
        && components[1].as_os_str() == "chats"
        && path.extension().is_some_and(|extension| {
            extension == "jsonl"
                || (extension == "json"
                    && !path.with_extension("jsonl").exists())
        })
}

fn directory(base: &Path, path: &Path) -> crate::Result<String> {
    let Some(project) = path
        .strip_prefix(base)
        .ok()
        .and_then(|relative| relative.components().next())
    else {
        return Ok(String::new());
    };
    let marker = base.join(project).join(".project_root");
    match std::fs::read_to_string(&marker) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            Ok(String::new())
        }
        result => Ok(crate::storage::source_io::at(&marker, result)?
            .trim()
            .to_owned()),
    }
}

fn scan(base: &Path, path: &Path) -> crate::Result<Option<Session>> {
    let Some(chat) = chat::read(path)? else {
        return Ok(None);
    };
    Ok(Some(Session {
        directory: directory(base, path)?,
        model: chat.model.unwrap_or_default(),
        message_count: Some(chat.messages.len()),
        ..Session::new(
            chat.id,
            chat.title.unwrap_or_else(|| "Untitled Session".into()),
            path.to_owned(),
            chat.created,
            chat.updated,
        )
    }))
}

impl GeminiCli {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; source access is deferred"
    )]
    pub fn open() -> crate::Result<Self> {
        Ok(Self {
            roots: SourceRoots::new(
                data_root,
                "tmp",
                "data/gemini-cli",
                "GEMINI_CLI_HOME/.gemini/tmp",
            ),
        })
    }

    fn files(&mut self) -> crate::Result<(PathBuf, SourceFiles)> {
        let files = self
            .roots
            .files(Some(4), |path, base| is_source(base, path))?;
        Ok((self.roots.base.clone().unwrap_or_default(), files))
    }

    fn missing(&self, path: &Path) -> crate::Result<crate::Error> {
        Ok(ProviderError::missing(
            ["session source file is missing"; 2],
            path,
            Vec::new(),
            source_roots(self)?,
            vec![
                [
                    "Confirm the Gemini CLI chat file is still under the `tmp/<project>/chats` directory.",
                    "确认 Gemini CLI 会话文件仍位于 `tmp/<project>/chats` 目录下。",
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

impl Provider for GeminiCli {
    fn discover(
        &mut self,
        days: Option<i64>,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Discovery> {
        let (base, files) = self.files()?;
        file_sessions::discover(
            files,
            days,
            true,
            |path| scan(&base, path),
            |_, session, _| Ok(session),
        )
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Lookup> {
        let (base, files) = self.files()?;
        // Gemini CLI names a chat after the first eight characters of its id.
        let prefix = id.get(..8).unwrap_or(id);
        file_sessions::find(
            self.roots.base.as_deref(),
            files,
            id,
            |path| {
                path.file_stem()
                    .and_then(|stem| stem.to_str())
                    .is_some_and(|stem| stem == id || stem.ends_with(prefix))
            },
            |path| scan(&base, path),
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
        let chat =
            chat::read(path)?.ok_or("Gemini CLI chat has no session id")?;
        let stats = Stats {
            message_count: chat.messages.len(),
            total_input_tokens: chat.input.into(),
            total_output_tokens: chat.output.into(),
            total_tokens: Some(chat.input.saturating_add(chat.output).into()),
            ..Stats::default()
        };
        Ok(session.payload(chat.messages, stats))
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
            "tmp",
            false,
            |roots| GeminiCli { roots },
            |base| {
                let path = base.join("project/chats/session-kept.jsonl");
                std::fs::create_dir_all(path.parent().unwrap()).unwrap();
                std::fs::write(
                    &path,
                    concat!(
                        r#"{"sessionId":"kept","projectHash":"hash"}"#,
                        "\n",
                        r#"{"id":"u","type":"user","content":"Keep"}"#,
                    ),
                )
                .unwrap();
                path
            },
        );
    }
}
