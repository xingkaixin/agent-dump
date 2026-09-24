use crate::file_sessions::{self, SourceRoots};
use crate::jsonl;
use crate::provider::{DiagnosticSink, Provider, RecoverableDiagnostic};
use crate::session::{Session, SessionData, parse_timestamp};
use crate::timestamp::Timestamp;
use crate::title::{basename, normalize_title};
use crate::value::{field, text, truthy};
use serde_json::Value;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub struct Claude {
    roots: SourceRoots,
    titles: HashMap<PathBuf, HashMap<String, Value>>,
}

impl Claude {
    pub fn open() -> crate::Result<Self> {
        Ok(Self {
            roots: SourceRoots::new(
                || file_sessions::environment_root("CLAUDE_CONFIG_DIR", ".claude"),
                "projects",
                "data/claudecode",
                "CLAUDE_CONFIG_DIR/projects",
            ),
            titles: HashMap::new(),
        })
    }

    fn files(&mut self) -> crate::Result<Vec<PathBuf>> {
        let files = self.roots.files(Some(2), |path, base| {
            path.extension().is_some_and(|ext| ext == "jsonl") && path.parent() != Some(base)
        })?;
        if let Some(base) = &self.roots.base {
            crate::source_io::at(base, std::fs::read_dir(base))?;
        }
        Ok(files)
    }

    fn titles(
        &mut self,
        directory: &Path,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<&HashMap<String, Value>> {
        if !self.titles.contains_key(directory) {
            let titles = Self::load_titles(&directory.join("sessions-index.json"), diagnostics)?;
            self.titles.insert(directory.to_owned(), titles);
        }
        Ok(&self.titles[directory])
    }

    fn load_titles(
        path: &Path,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<HashMap<String, Value>> {
        let mut titles = HashMap::new();
        if !path.exists() {
            return Ok(titles);
        }
        let result = (|| -> crate::Result<Value> {
            let value: Value = crate::python_json::from_slice(&crate::source_io::read(path)?)?;
            if !value.is_object() {
                return Err("sessions index root must be an object".into());
            }
            if value
                .get("entries")
                .is_some_and(|entries| !entries.is_array())
            {
                return Err("sessions index entries must be an array".into());
            }
            Ok(value)
        })();
        let value = match result {
            Ok(value) => value,
            Err(error) => {
                diagnostics(RecoverableDiagnostic::TitleCacheFailed(error.to_string()))?;
                return Ok(titles);
            }
        };
        let mut skipped = 0;
        for entry in value["entries"].as_array().into_iter().flatten() {
            let id = text(&entry["sessionId"]);
            if id.trim().is_empty() {
                skipped += 1;
                continue;
            }
            titles.insert(id.to_owned(), entry["summary"].clone());
        }
        if skipped > 0 {
            diagnostics(RecoverableDiagnostic::TitleCacheEntriesSkipped {
                path: path.to_owned(),
                count: skipped,
            })?;
        }
        Ok(titles)
    }

    fn parse(
        &mut self,
        path: &Path,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Option<Session>> {
        let scan = jsonl::metadata(path, 20)?;
        let Some(header) = scan.header else {
            return Ok(None);
        };
        let project = path.parent().ok_or("Session has no project directory")?;
        let id = path
            .file_stem()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned();
        let created_at = parse_timestamp(text(&header["timestamp"]))
            .unwrap_or(Timestamp::try_from(path.metadata()?.modified()?)?);
        let explicit = match self
            .titles(project, diagnostics)?
            .get(&id)
            .filter(|value| truthy(value))
        {
            Some(Value::String(title)) => normalize_title(title),
            Some(value) => {
                let kind = crate::value::type_name(value);
                return Err(format!("expected string or bytes-like object, got '{kind}'").into());
            }
            None => None,
        };
        let first_user = scan
            .records
            .iter()
            .take(20)
            .find_map(|record| {
                let message = &record["message"];
                if message["role"] != "user" || !crate::value::truthy(&message["content"]) {
                    return None;
                }
                let content = &message["content"];
                let text = match content.as_array() {
                    Some(items) => items
                        .iter()
                        .filter_map(|item| {
                            if item.is_object() {
                                Some(field(item, "text"))
                            } else {
                                item.as_str().map(str::to_owned)
                            }
                        })
                        .collect::<Vec<_>>()
                        .join(" "),
                    None => text(content).to_owned(),
                };
                Some(normalize_title(&text))
            })
            .flatten();
        let title = explicit
            .or(first_user)
            .or_else(|| crate::title::value_basename(&header["cwd"]))
            .or_else(|| basename(&project.to_string_lossy()))
            .unwrap_or_else(|| "Untitled Session".into());
        let mut updated_at = created_at;
        let mut count = 0;
        let mut model = String::new();
        for record in scan.records.iter().chain(scan.tail.iter()) {
            if let Some(timestamp) = parse_timestamp(text(&record["timestamp"])) {
                updated_at = timestamp;
            }
            let message = &record["message"];
            if !text(&message["role"]).trim().is_empty() {
                count += 1;
            }
            if model.is_empty() {
                model = text(&message["model"]).trim().into();
            }
        }
        Ok(Some(Session {
            id,
            title,
            created_at,
            updated_at,
            subtargets: Vec::new(),
            source_metadata: serde_json::json!({"cwd": header.get("cwd").cloned().unwrap_or_else(|| "".into())}),
            source_path: path.to_owned(),
            directory: text(&header["cwd"]).to_owned(),
            version: header.get("version").cloned().unwrap_or_else(|| "".into()),
            model,
            project: project
                .file_name()
                .map(|name| name.to_string_lossy().into_owned()),
            message_count: scan.complete.then_some(count),
        }))
    }
}

impl Provider for Claude {
    fn discover(
        &mut self,
        days: i64,
        diagnostics: &mut crate::provider::DiagnosticSink<'_>,
    ) -> crate::Result<crate::provider::Discovery> {
        self.titles.clear();
        file_sessions::discover(&self.files()?, days, true, |path, _| {
            self.parse(path, diagnostics)
        })
    }

    fn find(
        &mut self,
        id: &str,
        diagnostics: &mut crate::provider::DiagnosticSink<'_>,
    ) -> crate::Result<crate::provider::Lookup> {
        self.titles.clear();
        let files = self.files()?;
        file_sessions::find(
            self.roots.base.clone().as_deref(),
            &files,
            id,
            |path| path.file_stem().is_some_and(|name| name == id),
            |path| self.parse(path, diagnostics),
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
                crate::provider::source_roots(self)?,
                vec![
                    ["Confirm the Claude Code session file is still under the projects directory.", "确认 Claude Code 会话文件仍位于 projects 目录下。"],
                    ["Re-run `agent-dump --list` to confirm the session still exists.", "重新运行 `agent-dump --list` 确认该会话是否仍存在。"],
                ],
            ).into());
        }
        crate::claude_transcript::read(session, diagnostics)
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
    fn source_selection_retries_absence_and_keeps_selected_root() {
        crate::source_tests::source_selection(
            "projects",
            true,
            |roots| Claude {
                roots,
                titles: HashMap::new(),
            },
            |base| {
                let path = base.join("project/kept.jsonl");
                std::fs::create_dir_all(path.parent().unwrap()).unwrap();
                std::fs::write(&path, concat!(r#"{"type":"user","timestamp":"2026-01-15T00:00:00Z","message":{"role":"user","content":"Keep"}}"#, "\n")).unwrap();
                path
            },
        );
    }

    #[test]
    fn title_cache_is_per_project_and_refreshes_after_recovery() {
        let directory = tempfile::tempdir().unwrap();
        let projects = directory.path().join("projects");
        for (project, id) in [
            ("first", "kept"),
            ("first", "other"),
            ("second", "separate"),
        ] {
            let path = projects.join(project).join(format!("{id}.jsonl"));
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(&path, serde_json::json!({"type": "user", "timestamp": "2026-01-15T00:00:00Z", "message": {"role": "user", "content": "Fallback"}}).to_string()).unwrap();
        }
        let index = projects.join("first/sessions-index.json");
        std::fs::write(&index, "[]").unwrap();
        std::fs::write(
            projects.join("second/sessions-index.json"),
            r#"{"entries":[{"sessionId":"separate","summary":"Separate"}]}"#,
        )
        .unwrap();
        let mut provider = Claude {
            roots: SourceRoots::fixed(
                directory.path().into(),
                "projects",
                "data/claudecode",
                "CLAUDE_CONFIG_DIR/projects",
            ),
            titles: HashMap::new(),
        };
        let mut warnings = Vec::new();
        let discovery = provider
            .discover(36500, &mut |warning| {
                warnings.push(warning);
                Ok(())
            })
            .unwrap();
        assert!(discovery.available && discovery.failures.is_empty());
        assert_eq!(discovery.sessions.len(), 3);
        assert!(
            discovery
                .sessions
                .iter()
                .any(|session| session.title == "Separate")
        );
        assert!(matches!(
            warnings.as_slice(),
            [RecoverableDiagnostic::TitleCacheFailed(_)]
        ));

        let updated = r#"{"entries":[{"sessionId":"kept","summary":"Updated"}]}"#;
        std::fs::write(&index, updated).unwrap();
        let session = provider
            .find("kept", &mut |_| panic!("healthy index must not warn"))
            .unwrap()
            .session
            .unwrap();
        assert_eq!(session.title, "Updated");
        assert_eq!(std::fs::read_to_string(&index).unwrap(), updated);

        std::fs::remove_file(&index).unwrap();
        let session = provider
            .find("kept", &mut |_| panic!("absent index must not warn"))
            .unwrap()
            .session
            .unwrap();
        assert_eq!(session.title, "Fallback");
        assert!(!index.exists());
    }

    #[test]
    fn removed_source_keeps_provider_diagnostic() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("projects/project/kept.jsonl");
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, "{\"type\":\"user\",\"sessionId\":\"kept\",\"timestamp\":\"2026-01-15T00:00:00Z\",\"message\":{\"role\":\"user\",\"content\":\"hello\"}}\n").unwrap();
        let provider = Claude {
            roots: SourceRoots::fixed(
                directory.path().into(),
                "projects",
                "data/claudecode",
                "CLAUDE_CONFIG_DIR/projects",
            ),
            titles: HashMap::new(),
        };
        crate::source_tests::removed_file(provider, &path, "kept", "projects directory");
    }
}
