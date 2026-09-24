use crate::file_sessions::{self, SourceRoots};
use crate::jsonl;
use crate::provider::Provider;
use crate::session::{Session, SessionData, parse_timestamp};
use crate::title::{basename, normalize_title};
use crate::value::{field, text};
use jiff::Timestamp;
use serde_json::Value;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub struct Claude {
    roots: SourceRoots,
    titles: HashMap<PathBuf, HashMap<String, String>>,
}

impl Claude {
    pub fn open() -> crate::Result<Self> {
        let root = file_sessions::environment_root("CLAUDE_CONFIG_DIR", ".claude")?;
        Ok(Self {
            roots: SourceRoots::resolve(root, "projects", "data/claudecode"),
            titles: HashMap::new(),
        })
    }

    fn files(&self) -> crate::Result<Vec<PathBuf>> {
        self.roots.files(Some(2), |path| {
            path.extension().is_some_and(|ext| ext == "jsonl")
                && path.parent() != Some(self.roots.base.as_path())
        })
    }

    fn titles(&mut self, directory: &Path) -> &HashMap<String, String> {
        self.titles.entry(directory.to_owned()).or_insert_with(|| {
            let mut titles = HashMap::new();
            let path = directory.join("sessions-index.json");
            if !path.exists() {
                return titles;
            }
            let result = std::fs::read(&path)
                .map_err(|error| error.to_string())
                .and_then(|bytes| {
                    serde_json::from_slice::<Value>(&bytes).map_err(|error| error.to_string())
                });
            match result {
                Ok(value) => {
                    if let Some(entries) = value["entries"].as_array() {
                        for entry in entries {
                            let id = text(&entry["sessionId"]);
                            if id.trim().is_empty() {
                                continue;
                            }
                            titles.insert(id.to_owned(), text(&entry["summary"]).to_owned());
                        }
                    } else {
                        eprintln!(
                            "Warning: invalid Claude sessions index: {}",
                            crate::render::safe_line(&path.display().to_string())
                        );
                    }
                }
                Err(error) => eprintln!(
                    "Warning: invalid Claude sessions index: {}",
                    crate::render::safe_line(&error)
                ),
            }
            titles
        })
    }

    fn parse(&mut self, path: &Path) -> crate::Result<Option<Session>> {
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
        let explicit = self
            .titles(project)
            .get(&id)
            .and_then(|title| normalize_title(title));
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
            .or_else(|| basename(text(&header["cwd"])))
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
            source_metadata: serde_json::Value::Null,
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
    fn discover(&mut self, days: i64) -> crate::Result<Vec<Session>> {
        self.titles.clear();
        file_sessions::discover(&self.files()?, days, true, |path, _| self.parse(path))
    }

    fn find(&mut self, id: &str) -> crate::Result<Session> {
        self.titles.clear();
        file_sessions::find(
            &self.roots.base.clone(),
            &self.files()?,
            id,
            |path| path.file_stem().is_some_and(|name| name == id),
            |path| self.parse(path),
        )
    }

    fn read(&self, session: &Session, _zh: bool) -> crate::Result<SessionData> {
        crate::claude_transcript::read(session)
    }

    fn source_root(&self) -> &Path {
        &self.roots.owned
    }
}
