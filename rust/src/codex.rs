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
}

impl Codex {
    pub fn open() -> crate::Result<Self> {
        let root = file_sessions::environment_root("CODEX_HOME", ".codex")?;
        let roots = SourceRoots::resolve(root.clone(), "sessions", "data/codex");
        let mut titles = HashMap::new();
        let index = root.join("session_index.jsonl");
        if index.exists() {
            jsonl::scan(&index, |record| {
                let id = text(&record["id"]);
                if !id.trim().is_empty()
                    && let Some(title) = normalize_title(text(&record["thread_name"]))
                {
                    titles.insert(id.to_owned(), title);
                }
                Ok(())
            })?;
        }
        Ok(Self { roots, titles })
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
    fn discover(&mut self, days: i64) -> crate::Result<Vec<Session>> {
        if !self.roots.base.exists() {
            return Err("No Codex sessions found".into());
        }
        file_sessions::discover(&self.files()?, days, true, |path, _| self.parse(path))
    }

    fn find(&mut self, id: &str) -> crate::Result<Session> {
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

    fn read(&self, session: &Session, zh: bool) -> crate::Result<SessionData> {
        super::codex_transcript::read(session, zh)
    }

    fn json_payload(&self, data: &SessionData) -> SessionData {
        super::codex_enrichment::json_payload(data)
    }

    fn source_root(&self) -> &Path {
        &self.roots.owned
    }
}
