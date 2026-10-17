pub(super) mod transcript;

use crate::compat::value::{field, text, truthy};
use crate::providers::contract::{Provider, Window};
use crate::providers::error::LocalizedText;
use crate::providers::files::{
    self as file_sessions, Located, SourceFiles, SourceRoots,
};
use crate::providers::title::{basename, normalize_title};
use crate::session::timestamp::Timestamp;
use crate::session::{Session, SessionData, epoch_seconds, parse_timestamp};
use serde_json::Value;
use std::path::{Path, PathBuf};

/// Providers that keep Pi's session tree format.
#[derive(Clone, Copy)]
pub enum Kind {
    Pi,
    Omp,
}

impl Kind {
    fn roots(self) -> SourceRoots {
        match self {
            Self::Pi => SourceRoots::located(session_directory, "data/pi"),
            Self::Omp => SourceRoots::located(omp_directory, "data/omp"),
        }
    }

    const fn agent(self) -> &'static str {
        match self {
            Self::Pi => "pi",
            Self::Omp => "omp",
        }
    }

    const fn display_name(self) -> &'static str {
        match self {
            Self::Pi => "Pi",
            Self::Omp => "oh-my-pi",
        }
    }

    const fn location_hint(self) -> LocalizedText {
        match self {
            Self::Pi => [
                "Confirm the Pi session file is still under the Pi session directory or the local development data directory.",
                "确认 Pi 会话文件仍在 Pi 会话目录或本地开发数据目录。",
            ],
            Self::Omp => [
                "Confirm the oh-my-pi session file is still under the oh-my-pi session directory or the local development data directory.",
                "确认 oh-my-pi 会话文件仍在 oh-my-pi 会话目录或本地开发数据目录。",
            ],
        }
    }
}

pub struct Pi {
    kind: Kind,
    roots: SourceRoots,
}

struct Summary {
    header: Value,
    updated_at: Option<Timestamp>,
    model: String,
    title: Option<String>,
    message_count: Option<usize>,
}

fn session_directory() -> crate::Result<Located> {
    let independent = |sessions: PathBuf, label| Located {
        owner: sessions.clone(),
        sessions,
        label,
    };
    if let Some(sessions) =
        file_sessions::environment_path("PI_CODING_AGENT_SESSION_DIR")?
    {
        return Ok(independent(sessions, "PI_CODING_AGENT_SESSION_DIR"));
    }
    let (owner, agent, label) = if let Some(agent) =
        file_sessions::environment_path("PI_CODING_AGENT_DIR")?
    {
        (agent.clone(), agent, "PI_CODING_AGENT_DIR/sessions")
    } else {
        let home = file_sessions::environment_root("PI_HOME", ".pi")?;
        (home.clone(), home.join("agent"), "PI_HOME/agent/sessions")
    };
    if let Some(sessions) = settings_session_directory(&agent)? {
        return Ok(independent(sessions, "Pi settings.json sessionDir"));
    }
    Ok(Located {
        owner,
        sessions: agent.join("sessions"),
        label,
    })
}

fn omp_directory() -> crate::Result<Located> {
    if !cfg!(windows)
        && let Some(data) = file_sessions::environment_path("XDG_DATA_HOME")?
    {
        let owner = data.join("omp");
        if owner.exists() {
            return Ok(Located {
                sessions: owner.join("sessions"),
                owner,
                label: "XDG_DATA_HOME/omp/sessions",
            });
        }
    }
    let owner = file_sessions::environment_root("HOME", ".omp")?;
    Ok(Located {
        sessions: owner.join("agent/sessions"),
        owner,
        label: "~/.omp/agent/sessions",
    })
}

fn settings_session_directory(agent: &Path) -> crate::Result<Option<PathBuf>> {
    let Ok(bytes) =
        crate::storage::source_io::read(&agent.join("settings.json"))
    else {
        return Ok(None);
    };
    let Ok(settings) = crate::compat::json::from_slice(&bytes) else {
        return Ok(None);
    };
    let Some(directory) = settings["sessionDir"]
        .as_str()
        .map(str::trim)
        .filter(|directory| !directory.is_empty())
    else {
        return Ok(None);
    };
    // Pi resolves a relative sessionDir from its own working directory.
    let directory = file_sessions::expand_home(directory)?;
    Ok(directory.is_absolute().then_some(directory))
}

impl Pi {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; source access is deferred"
    )]
    pub fn open(kind: Kind) -> crate::Result<Self> {
        Ok(Self {
            kind,
            roots: kind.roots(),
        })
    }

    fn files(&mut self) -> crate::Result<SourceFiles> {
        self.roots.files(None, |path, _| {
            path.extension().is_some_and(|ext| ext == "jsonl")
        })
    }

    fn scan(path: &Path, kind: Kind) -> crate::Result<Option<Summary>> {
        let scan = crate::providers::jsonl::metadata(path, 20, None)?;
        let mut updated_at = None;
        let mut model = String::new();
        for record in scan.records.iter().chain(scan.tail.iter()) {
            updated_at = updated_at.max(datetime(&record["timestamp"]));
            if model.is_empty() && record["type"] == "message" {
                text(&record["message"]["model"])
                    .trim()
                    .clone_into(&mut model);
            }
        }
        let (header, title, message_count) = if scan.complete {
            let transcript =
                transcript::Transcript::new(scan.records, kind, |_| Ok(()))?;
            let Some(header) = transcript.header else {
                return Ok(None);
            };
            if transcript.messages.is_empty() {
                return Ok(None);
            }
            (header, transcript.title, Some(transcript.messages.len()))
        } else {
            let Some(header) = scan
                .records
                .iter()
                .find(|record| record["type"] == "session")
                .cloned()
            else {
                return Ok(None);
            };
            let mut titles = Titles::default();
            for record in scan.records.iter().chain(scan.tail.iter()) {
                titles.add(record);
            }
            let title = titles.resolve(&header);
            (header, title, None)
        };
        Ok(Some(Summary {
            header,
            updated_at,
            model,
            title,
            message_count,
        }))
    }

    fn parse(
        path: &Path,
        summary: Option<Summary>,
    ) -> crate::Result<Option<Session>> {
        let Some(Summary {
            header,
            updated_at,
            model,
            title,
            message_count,
        }) = summary
        else {
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
        let updated_at = updated_at
            .map_or(created_at, |updated_at| updated_at.max(created_at));
        let title = title
            .or_else(|| crate::providers::title::value_basename(&header["cwd"]))
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
            source_metadata: serde_json::json!({"cwd": header.get("cwd").cloned().unwrap_or_else(|| "".into())}),
            source_path: path.to_owned(),
            directory: text(&header["cwd"]).into(),
            version: header["version"].clone(),
            model,
            project: None,
            message_count,
        }))
    }
}

impl Provider for Pi {
    fn discover(
        &mut self,
        window: Window,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Discovery> {
        let kind = self.kind;
        file_sessions::discover(
            self.files()?,
            window,
            true,
            |path| Self::scan(path, kind),
            |path, summary, _| Self::parse(path, summary),
        )
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Lookup> {
        let suffix = format!("{id}.jsonl");
        let files = self.files()?;
        file_sessions::find(
            self.roots.base.as_deref(),
            files,
            id,
            |path| {
                path.file_name().is_some_and(|name| {
                    name.to_string_lossy().ends_with(&suffix)
                })
            },
            |path| Self::parse(path, Self::scan(path, self.kind)?),
        )
    }

    fn read(
        &self,
        session: &Session,
        _zh: bool,
        diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        if !session.source_path.exists() {
            return Err(crate::providers::error::ProviderError::missing(
                ["session source file is missing"; 2],
                &session.source_path,
                Vec::new(),
                crate::providers::contract::source_roots(self)?,
                vec![
                    self.kind.location_hint(),
                    ["Re-run `agent-dump --list` to confirm the session id still exists.", "重新运行 `agent-dump --list` 确认会话 ID 是否仍存在。"],
                ],
            ).into());
        }
        crate::providers::pi::transcript::read(session, self.kind, diagnostics)
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

pub fn datetime(value: &Value) -> Option<Timestamp> {
    if let Some(number) = value.as_f64() {
        return epoch_seconds(number / 1000.0);
    }
    parse_timestamp(value.as_str()?.trim())
}

#[derive(Default)]
pub struct Titles {
    named: Option<String>,
    slot: Option<String>,
    prompt: Option<String>,
}

impl Titles {
    pub fn add(&mut self, record: &Value) {
        match text(&record["type"]) {
            "session_info" => {
                if let Some(name) = title(text(&record["name"])) {
                    self.named = Some(name);
                }
            }
            "title" => self.slot = title(text(&record["title"])),
            "message"
                if self.prompt.is_none()
                    && record["message"]["role"] == "user" =>
            {
                self.prompt =
                    title(&prompt_text(&record["message"]["content"]));
            }
            _ => {}
        }
    }

    pub fn resolve(self, header: &Value) -> Option<String> {
        self.named
            .or(self.slot)
            .or_else(|| title(text(&header["title"])))
            .or(self.prompt)
    }
}

fn title(value: &str) -> Option<String> {
    crate::providers::text::clean(value)
        .lines()
        .find(|line| !line.trim().is_empty())
        .and_then(normalize_title)
}

fn prompt_text(content: &Value) -> String {
    match content {
        Value::String(prompt) => prompt.clone(),
        Value::Array(items) => items
            .iter()
            .filter(|item| item["type"] == "text")
            .map(|item| text(&item["text"]))
            .collect::<Vec<_>>()
            .join("\n"),
        _ => String::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn write(path: &Path, records: &[Value]) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        let lines: Vec<_> = records.iter().map(Value::to_string).collect();
        std::fs::write(path, lines.join("\n")).unwrap();
    }

    #[test]
    fn active_branch_drives_listing_and_export() {
        let directory = tempfile::tempdir().unwrap();
        let sessions = directory.path().join("agent/sessions");
        write(
            &sessions.join("tree.jsonl"),
            &[
                json!({"type":"title","title":"Slot title"}),
                json!({"type":"session","id":"tree","cwd":"/work/tree","timestamp":"2026-01-15T00:00:00Z"}),
                json!({"type":"message","id":"u","parentId":null,"message":{"role":"user","content":"Prompt"}}),
                json!({"type":"message","id":"old","parentId":"u","message":{"role":"assistant","content":"Abandoned","usage":{"input":1000}}}),
                json!({"type":"session_info","id":"old-name","parentId":"old","name":"Abandoned name"}),
                json!({"type":"message","id":"a","parentId":"u","message":{"role":"assistant","content":[{"type":"toolCall","id":"call","name":"read","arguments":{"path":"a"}}],"usage":{"input":100,"output":20,"cacheRead":10,"cacheWrite":5,"totalTokens":135,"cost":{"total":0.25}}}}),
                json!({"type":"message","id":"r","parentId":"a","message":{"role":"toolResult","toolCallId":"call","toolName":"read","content":[{"type":"text","text":"Result"}],"isError":false,"details":{"lines":1}}}),
                json!({"type":"custom_message","id":"hidden","parentId":"r","display":false,"content":"Hidden"}),
                json!({"type":"message","id":"note","parentId":"hidden","message":{"role":"custom","content":"Hidden note"}}),
                json!({"type":"custom_message","id":"shown","parentId":"note","display":true,"content":"Shown"}),
                json!({"type":"message","id":"b","parentId":"shown","message":{"role":"bashExecution","command":"false","output":"boom","exitCode":1,"cancelled":false,"truncated":false}}),
            ],
        );
        write(
            &sessions.join("empty.jsonl"),
            &[
                json!({"type":"session","id":"empty","timestamp":"2026-01-15T00:00:00Z"}),
                json!({"type":"custom_message","id":"c","parentId":null,"display":false,"content":"Hidden"}),
                json!({"type":"message","id":"a","parentId":"c","message":{"role":"assistant","content":[],"usage":{"input":5}}}),
            ],
        );
        let mut provider = Pi {
            kind: Kind::Pi,
            roots: SourceRoots::fixed(
                directory.path().into(),
                "agent/sessions",
                "data/pi",
                "PI_HOME/agent/sessions",
            ),
        };
        let discovery =
            provider.discover(Window::All, &mut |_| Ok(())).unwrap();
        let [session] = discovery.sessions.as_slice() else {
            panic!("only the visible session is listed");
        };
        assert_eq!(session.title, "Slot title");
        assert_eq!(session.message_count, Some(4));
        let data = serde_json::to_value(
            provider.read(session, false, &mut |_| Ok(())).unwrap(),
        )
        .unwrap();
        let messages = data["messages"].as_array().unwrap();
        let roles: Vec<_> =
            messages.iter().map(|message| &message["role"]).collect();
        assert_eq!(roles, ["user", "assistant", "custom", "tool"]);
        let call = &messages[1]["parts"][0]["state"];
        assert_eq!(call["output"][0]["text"], "Result");
        assert_eq!(call["status"], "completed");
        assert_eq!(call["metadata"], json!({"lines": 1}));
        assert_eq!(
            messages[1]["tokens"],
            json!({"input":115,"output":20,"cache":{"read":10,"write":5},"total":135})
        );
        let bash = &messages[3]["parts"][0]["state"];
        assert_eq!(bash["status"], "error");
        assert_eq!(
            bash["metadata"],
            json!({"exitCode":1,"cancelled":false,"truncated":false})
        );
        assert_eq!(
            data["stats"],
            json!({"total_cost":0.25,"total_input_tokens":115,"total_output_tokens":20,"total_tokens":135,"message_count":4})
        );
    }

    #[test]
    fn titles_prefer_session_info_title_record_header_then_prompt() {
        let header = json!({"type":"session","title":"Header"});
        let prompt = json!({"type":"message","id":"u","parentId":null,"message":{"role":"user","content":"<system-reminder>x</system-reminder>\n  First   line \nSecond"}});
        let slot = json!({"type":"title","title":"Slot"});
        let named = json!({"type":"session_info","id":"n","parentId":"u","name":"Named"});
        for (records, expected) in [
            (
                vec![json!({"type":"session"}), prompt.clone()],
                "First line",
            ),
            (vec![header.clone(), prompt.clone()], "Header"),
            (vec![slot.clone(), header.clone(), prompt.clone()], "Slot"),
            (vec![header, prompt, slot, named], "Named"),
        ] {
            let transcript =
                transcript::Transcript::new(records, Kind::Pi, |_| Ok(()))
                    .unwrap();
            assert_eq!(transcript.title.as_deref(), Some(expected));
        }
    }

    #[test]
    fn source_selection_retries_absence_and_keeps_selected_root() {
        crate::providers::source_tests::source_selection(
            "agent/sessions",
            false,
            |roots| Pi {
                kind: Kind::Pi,
                roots,
            },
            |base| {
                let path = base.join("kept.jsonl");
                std::fs::create_dir_all(base).unwrap();
                std::fs::write(
                    &path,
                    concat!(
                        r#"{"type":"session","id":"kept","timestamp":"2026-01-15T00:00:00Z"}"#,
                        "\n",
                        r#"{"type":"message","message":{"role":"user","content":"Keep"}}"#,
                        "\n"
                    ),
                )
                .unwrap();
                path
            },
        );
    }

    #[test]
    fn removed_source_keeps_provider_diagnostic() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("agent/sessions/kept.jsonl");
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(
            &path,
            concat!(
                r#"{"type":"session","id":"kept","timestamp":"2026-01-15T00:00:00Z"}"#,
                "\n",
                r#"{"type":"message","message":{"role":"user","content":"Keep"}}"#,
                "\n"
            ),
        )
        .unwrap();
        let provider = Pi {
            kind: Kind::Pi,
            roots: SourceRoots::fixed(
                directory.path().into(),
                "agent/sessions",
                "data/pi",
                "PI_HOME/agent/sessions",
            ),
        };
        crate::providers::source_tests::removed_file(
            provider,
            &path,
            "kept",
            "Pi session directory",
        );
    }
}
