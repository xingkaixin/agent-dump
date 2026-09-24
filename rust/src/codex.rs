use crate::file_sessions::{self, SourceRoots};
use crate::jsonl;
use crate::provider::Provider;
use crate::session::{Session, SessionData, parse_timestamp};
use crate::title::{basename, normalize_title};
use crate::value::text;
use jiff::Timestamp;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub struct Codex {
    roots: SourceRoots,
    titles: HashMap<String, String>,
    index: PathBuf,
}

impl Codex {
    pub fn open() -> crate::Result<Self> {
        let root = file_sessions::environment_root("CODEX_HOME", ".codex")?;
        let roots = SourceRoots::resolve(
            root.clone(),
            "sessions",
            "data/codex",
            "CODEX_HOME/sessions",
        );
        Ok(Self {
            roots,
            titles: HashMap::new(),
            index: root.join("session_index.jsonl"),
        })
    }

    fn prepare(&mut self) -> crate::Result<()> {
        self.titles.clear();
        if self.index.exists() {
            jsonl::scan(&self.index, &mut |_| Ok(()), |record| {
                let id = text(&record["id"]);
                if !id.trim().is_empty()
                    && let Some(title) = normalize_title(text(&record["thread_name"]))
                {
                    self.titles.insert(id.to_owned(), title);
                }
                Ok(())
            })?;
        }
        Ok(())
    }

    fn files(&self) -> crate::Result<Vec<PathBuf>> {
        self.roots.files(None, |path| {
            path.extension().is_some_and(|ext| ext == "jsonl")
        })
    }

    fn parse(&self, path: &Path) -> crate::Result<Option<Session>> {
        let scan = jsonl::metadata(path, 10)?;
        let Some(header) = scan.header else {
            return Ok(None);
        };
        let payload = &header["payload"];
        if !payload.is_null() && !payload.is_object() {
            return Err("Invalid Codex session header payload".into());
        }
        let mut id = text(&payload["id"]).to_owned();
        if id.is_empty() {
            let stem = path.file_stem().unwrap_or_default().to_string_lossy();
            let parts: Vec<_> = stem.split('-').collect();
            id = parts[parts.len().saturating_sub(5)..].join("-");
        }
        let created_at = parse_timestamp(text(&payload["timestamp"]))
            .unwrap_or(Timestamp::try_from(path.metadata()?.modified()?)?);
        let mut user_count = 0;
        let message_title = scan.records.iter().take(10).find_map(|record| {
            let p = &record["payload"];
            if p["type"] != "message" || p["role"] != "user" {
                return None;
            }
            user_count += 1;
            if user_count < 2 {
                return None;
            }
            let parts = p["content"].as_array()?;
            normalize_title(
                &parts
                    .iter()
                    .map(|part| {
                        if part.is_string() {
                            text(part)
                        } else {
                            text(&part["text"])
                        }
                    })
                    .collect::<Vec<_>>()
                    .join(" "),
            )
        });
        let title = self
            .titles
            .get(&id)
            .cloned()
            .or(message_title)
            .or_else(|| basename(text(&payload["cwd"])))
            .or_else(|| {
                path.parent()
                    .and_then(|parent| basename(&parent.to_string_lossy()))
            })
            .unwrap_or_else(|| "Untitled Session".into());
        let mut updated_at = created_at;
        let mut count = 0;
        let mut model = String::new();
        for record in scan.records.iter().chain(scan.tail.iter()) {
            if let Some(time) = parse_timestamp(text(&record["timestamp"])) {
                updated_at = time;
            }
            let p = &record["payload"];
            if matches!(
                text(&p["type"]),
                "message" | "function_call" | "function_call_output"
            ) {
                count += 1;
            }
            if model.is_empty() {
                model = text(&p["model"]).trim().to_owned();
                if model.is_empty() {
                    model = text(&p["arguments"]["model"]).trim().to_owned();
                }
            }
        }
        if model.is_empty() {
            model = text(&payload["model_provider"]).to_owned();
        }
        Ok(Some(Session {
            id,
            title,
            created_at,
            updated_at,
            subtargets: Vec::new(),
            source_metadata: serde_json::Value::Null,
            source_path: path.to_owned(),
            directory: text(&payload["cwd"]).to_owned(),
            version: text(&payload["cli_version"]).into(),
            model,
            project: None,
            message_count: scan.complete.then_some(count),
        }))
    }
}

impl Provider for Codex {
    fn discover(&mut self, days: i64) -> crate::Result<crate::provider::Discovery> {
        self.prepare()?;
        file_sessions::discover(&self.files()?, days, true, |path, _| self.parse(path))
    }

    fn find(&mut self, id: &str) -> crate::Result<crate::provider::Lookup> {
        self.prepare()?;
        let suffix = format!("-{id}.jsonl");
        file_sessions::find(
            &self.roots.base,
            &self.files()?,
            id,
            |path| {
                path.file_name()
                    .is_some_and(|name| name.to_string_lossy().ends_with(&suffix))
            },
            |path| self.parse(path),
        )
    }

    fn read(
        &self,
        session: &Session,
        zh: bool,
        diagnostics: &mut crate::provider::DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        if !session.source_path.exists() {
            return Err(crate::provider_error::ProviderError::missing(
                ["session source file is missing"; 2],
                &session.source_path,
                Vec::new(),
                crate::provider::source_roots(self),
                vec![
                    ["Confirm the Codex session file is still under `CODEX_HOME/sessions` or the local development data directory.", "确认 Codex 会话文件仍在 `CODEX_HOME/sessions` 或本地开发数据目录。"],
                    ["Re-run `agent-dump --list` to confirm the session id still exists.", "重新运行 `agent-dump --list` 确认会话 ID 是否仍存在。"],
                ],
            ).into());
        }
        super::codex_transcript::read(session, zh, diagnostics)
    }

    fn json_payload(&self, data: &SessionData) -> serde_json::Value {
        serde_json::to_value(super::codex_enrichment::json_payload(data)).unwrap()
    }

    fn search_roots(&self) -> Vec<(&'static str, PathBuf)> {
        self.roots.search_roots()
    }

    fn source_root(&self) -> &Path {
        &self.roots.owned
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn removed_source_keeps_provider_diagnostic() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("sessions/rollout-kept.jsonl");
        std::fs::create_dir(path.parent().unwrap()).unwrap();
        std::fs::write(&path, "{\"type\":\"session_meta\",\"payload\":{\"id\":\"kept\",\"timestamp\":\"2026-01-15T00:00:00Z\"}}\n").unwrap();
        let provider = Codex {
            roots: SourceRoots::resolve(
                directory.path().into(),
                "sessions",
                "data/codex",
                "CODEX_HOME/sessions",
            ),
            titles: HashMap::new(),
            index: directory.path().join("session_index.jsonl"),
        };
        crate::source_tests::removed_file(provider, &path, "kept", "CODEX_HOME/sessions");
    }
}
