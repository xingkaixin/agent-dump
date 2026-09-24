use crate::file_sessions::{self, SourceRoots};
use crate::jsonl;
use crate::provider::{DiagnosticSink, Provider, RecoverableDiagnostic};
use crate::session::{Session, SessionData, parse_timestamp};
use crate::timestamp::Timestamp;
use crate::title::{basename, normalize_title};
use crate::value::text;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub struct Codex {
    roots: SourceRoots,
    titles: Option<HashMap<String, String>>,
}

impl Codex {
    pub fn open() -> crate::Result<Self> {
        let roots = SourceRoots::new(
            || file_sessions::environment_root("CODEX_HOME", ".codex"),
            "sessions",
            "data/codex",
            "CODEX_HOME/sessions",
        );
        Ok(Self {
            roots,
            titles: None,
        })
    }

    fn title(
        &mut self,
        id: &str,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Option<String>> {
        if self.titles.is_none() {
            let mut titles = HashMap::new();
            let index = self.roots.configured_root()?.join("session_index.jsonl");
            if index.exists()
                && let Err(error) = jsonl::scan(&index, &mut |_| Ok(()), |record, _| {
                    let id = text(&record["id"]);
                    if !id.trim().is_empty()
                        && let Some(title) = normalize_title(text(&record["thread_name"]))
                    {
                        titles.insert(id.to_owned(), title);
                    }
                    Ok(())
                })
            {
                diagnostics(RecoverableDiagnostic::TitleCacheFailed(error.to_string()))?;
            }
            self.titles = Some(titles);
        }
        Ok(self
            .titles
            .as_ref()
            .and_then(|titles| titles.get(id))
            .cloned())
    }

    fn files(&mut self) -> crate::Result<Vec<PathBuf>> {
        self.roots.files(None, |path, _| {
            path.extension().is_some_and(|ext| ext == "jsonl")
        })
    }

    fn parse(
        &mut self,
        path: &Path,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Option<Session>> {
        let scan = jsonl::metadata(path, 10)?;
        let Some(header) = scan.header else {
            return Ok(None);
        };
        let payload = &header["payload"];
        if !payload.is_null() && !payload.is_object() {
            return Err(format!(
                "'{}' object has no attribute 'get'",
                crate::value::type_name(payload)
            )
            .into());
        }
        let mut id = text(&payload["id"]).to_owned();
        if id.is_empty() {
            let stem = path.file_stem().unwrap_or_default().to_string_lossy();
            let parts: Vec<_> = stem.split('-').collect();
            id = parts[parts.len().saturating_sub(5)..].join("-");
        }
        let created_at = parse_timestamp(text(&payload["timestamp"]))
            .unwrap_or(Timestamp::try_from(path.metadata()?.modified()?)?);
        let explicit_title = self.title(&id, diagnostics)?;
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
        let title = explicit_title
            .or(message_title)
            .or_else(|| crate::title::value_basename(&payload["cwd"]))
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
            if p["type"].is_array() || p["type"].is_object() {
                return Err(
                    format!("unhashable type: '{}'", crate::value::type_name(&p["type"])).into(),
                );
            }
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
            source_metadata: serde_json::json!({"cwd": payload.get("cwd").cloned().unwrap_or_else(|| "".into())}),
            source_path: path.to_owned(),
            directory: text(&payload["cwd"]).to_owned(),
            version: payload
                .get("cli_version")
                .cloned()
                .unwrap_or_else(|| "".into()),
            model,
            project: None,
            message_count: scan.complete.then_some(count),
        }))
    }
}

impl Provider for Codex {
    fn discover(
        &mut self,
        days: i64,
        diagnostics: &mut crate::provider::DiagnosticSink<'_>,
    ) -> crate::Result<crate::provider::Discovery> {
        self.titles = None;
        file_sessions::discover(&self.files()?, days, true, |path, _| {
            self.parse(path, diagnostics)
        })
    }

    fn find(
        &mut self,
        id: &str,
        diagnostics: &mut crate::provider::DiagnosticSink<'_>,
    ) -> crate::Result<crate::provider::Lookup> {
        self.titles = None;
        let suffix = format!("-{id}.jsonl");
        let files = self.files()?;
        file_sessions::find(
            self.roots.base.clone().as_deref(),
            &files,
            id,
            |path| {
                path.file_name()
                    .is_some_and(|name| name.to_string_lossy().ends_with(&suffix))
            },
            |path| self.parse(path, diagnostics),
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
                crate::provider::source_roots(self)?,
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

    fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>> {
        self.roots.search_roots()
    }

    fn source_root(&self) -> &Path {
        self.roots.owned()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn title_index_follows_configuration_while_session_root_stays_selected() {
        let directory = tempfile::tempdir().unwrap();
        let first = directory.path().join("first");
        let second = directory.path().join("second");
        for (root, title) in [(&first, "First"), (&second, "Second")] {
            std::fs::create_dir_all(root.join("sessions")).unwrap();
            std::fs::write(
                root.join("session_index.jsonl"),
                serde_json::json!({"id":"kept", "thread_name":title}).to_string(),
            )
            .unwrap();
        }
        let source = first.join("sessions/rollout-kept.jsonl");
        std::fs::write(
            &source,
            r#"{"type":"session_meta","payload":{"id":"kept","timestamp":"2026-01-15T00:00:00Z"}}"#,
        )
        .unwrap();
        let configured = std::rc::Rc::new(std::cell::RefCell::new(first.clone()));
        let mut provider = Codex {
            roots: SourceRoots::new(
                {
                    let configured = configured.clone();
                    move || Ok(configured.borrow().clone())
                },
                "sessions",
                directory.path().join("fallback"),
                "Synthetic Codex",
            ),
            titles: None,
        };
        assert_eq!(
            provider
                .find("kept", &mut |_| Ok(()))
                .unwrap()
                .session
                .unwrap()
                .title,
            "First"
        );
        *configured.borrow_mut() = second.clone();
        let session = provider
            .find("kept", &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap();
        assert_eq!(session.title, "Second");
        assert_eq!(session.source_path, source);
        assert_eq!(provider.source_root(), first);
        std::fs::remove_file(second.join("session_index.jsonl")).unwrap();
        assert_ne!(
            provider.discover(36500, &mut |_| Ok(())).unwrap().sessions[0].title,
            "Second"
        );
        assert_eq!(
            provider.search_roots().unwrap()[0].1,
            second.join("sessions")
        );
    }

    #[test]
    fn source_selection_retries_absence_and_keeps_selected_root() {
        crate::source_tests::source_selection(
            "sessions",
            false,
            |roots| Codex {
                roots,
                titles: None,
            },
            |base| {
                let path = base.join("rollout-kept.jsonl");
                std::fs::create_dir_all(base).unwrap();
                std::fs::write(&path, concat!(r#"{"type":"session_meta","payload":{"id":"kept","timestamp":"2026-01-15T00:00:00Z"}}"#, "\n", r#"{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Keep"}]}}"#, "\n")).unwrap();
                path
            },
        );
    }

    #[test]
    fn title_cache_failure_is_recoverable_once_per_operation_and_refreshes() {
        let directory = tempfile::tempdir().unwrap();
        let sessions = directory.path().join("sessions");
        std::fs::create_dir(&sessions).unwrap();
        for id in ["kept", "other"] {
            std::fs::write(sessions.join(format!("rollout-{id}.jsonl")), serde_json::json!({
                "type": "session_meta", "payload": {"id": id, "timestamp": "2026-01-15T00:00:00Z", "cwd": "/fallback"}
            }).to_string()).unwrap();
        }
        let index = directory.path().join("session_index.jsonl");
        std::fs::create_dir(&index).unwrap();
        let mut provider = Codex {
            roots: SourceRoots::fixed(
                directory.path().into(),
                "sessions",
                "data/codex",
                "CODEX_HOME/sessions",
            ),
            titles: None,
        };
        let mut warnings = Vec::new();
        let discovery = provider
            .discover(36500, &mut |warning| {
                warnings.push(warning);
                Ok(())
            })
            .unwrap();
        assert!(discovery.available && discovery.failures.is_empty());
        assert_eq!(discovery.sessions.len(), 2);
        assert!(
            discovery
                .sessions
                .iter()
                .all(|session| session.title == "fallback")
        );
        assert!(matches!(
            warnings.as_slice(),
            [RecoverableDiagnostic::TitleCacheFailed(_)]
        ));

        std::fs::remove_dir(&index).unwrap();
        let updated = b"{\"id\":\"kept\",\"thread_name\":\"Updated\"}\n";
        std::fs::write(&index, updated).unwrap();
        let session = provider
            .find("kept", &mut |_| panic!("healthy index must not warn"))
            .unwrap()
            .session
            .unwrap();
        assert_eq!(session.title, "Updated");
        assert_eq!(std::fs::read(&index).unwrap(), updated);

        std::fs::remove_file(&index).unwrap();
        let discovery = provider
            .discover(36500, &mut |_| panic!("absent index must not warn"))
            .unwrap();
        assert!(
            discovery
                .sessions
                .iter()
                .all(|session| session.title == "fallback")
        );
        assert!(!index.exists());
    }

    #[test]
    fn removed_source_keeps_provider_diagnostic() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("sessions/rollout-kept.jsonl");
        std::fs::create_dir(path.parent().unwrap()).unwrap();
        std::fs::write(&path, "{\"type\":\"session_meta\",\"payload\":{\"id\":\"kept\",\"timestamp\":\"2026-01-15T00:00:00Z\"}}\n").unwrap();
        let provider = Codex {
            roots: SourceRoots::fixed(
                directory.path().into(),
                "sessions",
                "data/codex",
                "CODEX_HOME/sessions",
            ),
            titles: None,
        };
        crate::source_tests::removed_file(provider, &path, "kept", "CODEX_HOME/sessions");
    }
}
