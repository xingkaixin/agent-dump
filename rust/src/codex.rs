use crate::jsonl;
use crate::session::{Session, SessionData, parse_timestamp};
use jiff::{SignedDuration, Timestamp};
use serde_json::Value;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use walkdir::WalkDir;

pub struct Codex {
    base: PathBuf,
    source_root: PathBuf,
    titles: HashMap<String, String>,
}

pub fn normalize_title(text: &str) -> Option<String> {
    let title: String = text
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(100)
        .collect();
    if title.is_empty() { None } else { Some(title) }
}

fn basename(text: &str) -> Option<String> {
    Path::new(text.trim().trim_end_matches(['/', '\\']))
        .file_name()
        .and_then(|name| name.to_str())
        .and_then(normalize_title)
}

pub fn text(value: &Value) -> &str {
    value.as_str().unwrap_or("")
}

impl Codex {
    pub fn open() -> crate::Result<Self> {
        let home = std::env::var_os("HOME")
            .or_else(|| std::env::var_os("USERPROFILE"))
            .ok_or("HOME or USERPROFILE is required")?;
        let home = PathBuf::from(home);
        let root = match std::env::var("CODEX_HOME")
            .ok()
            .filter(|v| !v.trim().is_empty())
        {
            Some(value) if value == "~" => home.clone(),
            Some(value) if value.starts_with("~/") => home.join(&value[2..]),
            Some(value) => PathBuf::from(value),
            None => home.join(".codex"),
        };
        let base = root.join("sessions");
        let (base, source_root) = if base.exists() {
            (base, root.clone())
        } else {
            let local = PathBuf::from("data/codex");
            (local.clone(), local)
        };
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
        Ok(Self {
            base,
            source_root,
            titles,
        })
    }

    fn files(&self) -> impl Iterator<Item = crate::Result<PathBuf>> + '_ {
        WalkDir::new(&self.base)
            .into_iter()
            .filter_map(|entry| match entry {
                Ok(entry)
                    if entry.path().extension().is_some_and(|ext| ext == "jsonl")
                        && !entry.file_type().is_dir() =>
                {
                    Some(Ok(entry.into_path()))
                }
                Ok(_) => None,
                Err(error) => Some(Err(error.into())),
            })
    }

    pub fn discover(&self, days: i64) -> crate::Result<Vec<Session>> {
        if !self.base.exists() {
            return Err("No Codex sessions found".into());
        }
        let seconds = days.checked_mul(86400).ok_or("days is out of range")?;
        let cutoff = Timestamp::now().checked_sub(SignedDuration::from_secs(seconds))?;
        let mut sessions = Vec::new();
        for path in self.files() {
            let path = path?;
            let modified = Timestamp::try_from(path.metadata()?.modified()?)?;
            if modified < cutoff {
                continue;
            }
            if let Some(session) = self.parse(&path)?
                && session.created_at >= cutoff
            {
                sessions.push(session);
            }
        }
        sessions.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        Ok(sessions)
    }

    pub fn find(&self, id: &str) -> crate::Result<Session> {
        if self.base.exists() {
            let root = self.base.canonicalize()?;
            let paths: Vec<_> = self.files().collect::<crate::Result<_>>()?;
            let suffix = format!("-{id}.jsonl");
            for direct in [true, false] {
                for path in &paths {
                    let matches = path
                        .file_name()
                        .is_some_and(|name| name.to_string_lossy().ends_with(&suffix));
                    if matches != direct || !path.canonicalize()?.starts_with(&root) {
                        continue;
                    }
                    if let Some(session) = self.parse(path)?
                        && session.id == id
                    {
                        return Ok(session);
                    }
                }
            }
        }
        Err(format!("Session not found: codex://{id}").into())
    }

    fn parse(&self, path: &Path) -> crate::Result<Option<Session>> {
        let scan = jsonl::metadata(path)?;
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
            source_path: path.to_owned(),
            directory: text(&payload["cwd"]).to_owned(),
            version: text(&payload["cli_version"]).to_owned(),
            model,
            message_count: scan.complete.then_some(count),
        }))
    }

    pub fn read(&self, session: &Session, zh: bool) -> crate::Result<SessionData> {
        super::codex_transcript::read(session, zh)
    }

    pub fn json_payload(&self, data: &SessionData) -> SessionData {
        super::codex_enrichment::json_payload(data)
    }

    pub fn source_root(&self) -> &Path {
        &self.source_root
    }
}
