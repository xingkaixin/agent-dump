use crate::file_sessions::{self, SourceRoots};
use crate::provider::Provider;
use crate::session::{Session, SessionData, epoch_seconds, parse_timestamp};
use crate::title::{basename, normalize_title};
use crate::value::{field, text, truthy};
use jiff::Timestamp;
use serde_json::Value;
use std::path::{Path, PathBuf};

pub struct Pi {
    roots: SourceRoots,
}

impl Pi {
    pub fn open() -> crate::Result<Self> {
        let root = file_sessions::environment_root("PI_HOME", ".pi")?;
        Ok(Self {
            roots: SourceRoots::resolve(
                root,
                "agent/sessions",
                "data/pi",
                "PI_HOME/agent/sessions",
            ),
        })
    }

    fn files(&self) -> crate::Result<Vec<PathBuf>> {
        self.roots.files(None, |path| {
            path.extension().is_some_and(|ext| ext == "jsonl")
        })
    }

    fn parse(path: &Path) -> crate::Result<Option<Session>> {
        let scan = crate::jsonl::metadata(path, 20)?;
        let Some(header) = scan.header.filter(|header| header["type"] == "session") else {
            return Ok(None);
        };
        let id = if truthy(&header["id"]) {
            field(&header, "id").trim().to_owned()
        } else {
            path.file_stem()
                .unwrap_or_default()
                .to_string_lossy()
                .trim()
                .to_owned()
        };
        if id.is_empty() {
            return Ok(None);
        }
        let created_at = datetime(&header["timestamp"])
            .unwrap_or(Timestamp::try_from(path.metadata()?.modified()?)?);
        let mut updated_at = created_at;
        let mut message_count = 0;
        let mut model = String::new();
        let mut title = None;
        for record in scan.records.iter().chain(scan.tail.iter()) {
            if let Some(timestamp) = datetime(&record["timestamp"]) {
                updated_at = updated_at.max(timestamp);
            }
            if record["type"] == "message" {
                message_count += 1;
                if model.is_empty() {
                    model = text(&record["message"]["model"]).trim().to_owned();
                }
            }
            if let Some(name) = session_name(record) {
                title = Some(name);
            }
        }
        let title = title
            .or_else(|| {
                scan.records.iter().find_map(|record| {
                    (record["type"] == "message" && record["message"]["role"] == "user")
                        .then(|| normalize_title(&content_text(&record["message"]["content"])))
                        .flatten()
                })
            })
            .or_else(|| basename(text(&header["cwd"])))
            .or_else(|| {
                path.parent()
                    .and_then(|path| basename(&path.to_string_lossy()))
            })
            .unwrap_or_else(|| "Untitled Session".into());
        Ok(Some(Session {
            id,
            title,
            created_at,
            updated_at,
            subtargets: Vec::new(),
            source_metadata: serde_json::Value::Null,
            source_path: path.to_owned(),
            directory: text(&header["cwd"]).into(),
            version: header["version"].clone(),
            model,
            project: None,
            message_count: scan.complete.then_some(message_count),
        }))
    }
}

impl Provider for Pi {
    fn discover(
        &mut self,
        days: i64,
        _diagnostics: &mut crate::provider::DiagnosticSink<'_>,
    ) -> crate::Result<crate::provider::Discovery> {
        file_sessions::discover(&self.files()?, days, true, |path, _| Self::parse(path))
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut crate::provider::DiagnosticSink<'_>,
    ) -> crate::Result<crate::provider::Lookup> {
        let suffix = format!("{id}.jsonl");
        file_sessions::find(
            &self.roots.base,
            &self.files()?,
            id,
            |path| {
                path.file_name()
                    .is_some_and(|name| name.to_string_lossy().ends_with(&suffix))
            },
            Self::parse,
        )
    }

    fn read(
        &self,
        session: &Session,
        _zh: bool,
        diagnostics: &mut crate::provider::DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        if !session.source_path.exists() {
            return Err(crate::provider_error::ProviderError::missing(
                ["session source file is missing"; 2],
                &session.source_path,
                Vec::new(),
                crate::provider::source_roots(self),
                vec![
                    ["Confirm the Pi session file is still under `PI_HOME/agent/sessions` or the local development data directory.", "确认 Pi 会话文件仍在 `PI_HOME/agent/sessions` 或本地开发数据目录。"],
                    ["Re-run `agent-dump --list` to confirm the session id still exists.", "重新运行 `agent-dump --list` 确认会话 ID 是否仍存在。"],
                ],
            ).into());
        }
        crate::pi_transcript::read(session, diagnostics)
    }

    fn search_roots(&self) -> Vec<(&'static str, PathBuf)> {
        self.roots.search_roots()
    }

    fn source_root(&self) -> &Path {
        &self.roots.owned
    }
}

pub fn datetime(value: &Value) -> Option<Timestamp> {
    if let Some(number) = value.as_f64() {
        return epoch_seconds(number / 1000.0);
    }
    parse_timestamp(value.as_str()?.trim())
}

pub fn session_name(record: &Value) -> Option<String> {
    (record["type"] == "session_info")
        .then(|| normalize_title(text(&record["name"])))
        .flatten()
}

fn content_text(content: &Value) -> String {
    if let Some(text) = content.as_str() {
        return text.into();
    }
    let Some(items) = content.as_array() else {
        return String::new();
    };
    items
        .iter()
        .filter_map(|item| {
            if let Some(text) = item.as_str() {
                return Some(text.to_owned());
            }
            match text(&item["type"]) {
                "text" => Some(field(item, "text")),
                "thinking" => Some(field(item, "thinking")),
                _ => None,
            }
        })
        .filter(|text| !text.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn removed_source_keeps_provider_diagnostic() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("agent/sessions/kept.jsonl");
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(
            &path,
            "{\"type\":\"session\",\"id\":\"kept\",\"timestamp\":\"2026-01-15T00:00:00Z\"}\n",
        )
        .unwrap();
        let provider = Pi {
            roots: SourceRoots::resolve(
                directory.path().into(),
                "agent/sessions",
                "data/pi",
                "PI_HOME/agent/sessions",
            ),
        };
        crate::source_tests::removed_file(provider, &path, "kept", "PI_HOME/agent/sessions");
    }
}
