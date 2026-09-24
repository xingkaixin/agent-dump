use crate::output_formats::OutputFormat;
use crate::provider::Provider;
use crate::session::{Session, SessionData};
use jiff::{SignedDuration, Timestamp};
use rusqlite::Connection;
use serde_json::Value;
use std::path::{Path, PathBuf};

#[derive(Clone, Copy)]
pub enum Kind {
    DeepChat,
    Cherry,
    MiniMax,
}

pub struct Desktop {
    kind: Kind,
    database: PathBuf,
    search_roots: Vec<(&'static str, PathBuf)>,
}

impl Desktop {
    pub fn open(kind: Kind) -> crate::Result<Self> {
        let search_roots = match kind {
            Kind::DeepChat => {
                let root =
                    match std::env::var_os("DEEPCHAT_USER_DATA_DIR").filter(|v| !v.is_empty()) {
                        Some(root) => PathBuf::from(root),
                        None => app_data("DeepChat")?,
                    };
                vec![(
                    "DeepChat userData/app_db/agent.db",
                    root.join("app_db/agent.db"),
                )]
            }
            Kind::Cherry => crate::cherry::search_roots()?,
            Kind::MiniMax => crate::minimax::search_roots()?,
        };
        let database = search_roots
            .iter()
            .find(|(_, path)| path.exists())
            .unwrap_or_else(|| search_roots.last().unwrap())
            .1
            .clone();
        Ok(Self {
            kind,
            database,
            search_roots,
        })
    }

    fn sessions(
        &self,
        connection: &Connection,
        id: Option<&str>,
        cutoff: Option<i64>,
    ) -> crate::Result<crate::provider::Discovery> {
        match self.kind {
            Kind::DeepChat => crate::deepchat::sessions(connection, &self.database, id, cutoff)
                .map(crate::provider::Discovery::available),
            Kind::Cherry => crate::cherry::sessions(connection, &self.database, id, cutoff),
            Kind::MiniMax => crate::minimax::sessions(connection, &self.database, id, cutoff),
        }
    }
}

impl Provider for Desktop {
    fn discover(&mut self, days: i64) -> crate::Result<crate::provider::Discovery> {
        if !self.database.exists() {
            return Ok(crate::provider::Discovery::default());
        }
        let cutoff = Timestamp::now()
            .checked_sub(SignedDuration::from_secs(
                days.checked_mul(86400).ok_or("days is out of range")?,
            ))?
            .as_millisecond();
        self.sessions(&crate::sqlite::connect(&self.database)?, None, Some(cutoff))
    }

    fn find(&mut self, id: &str) -> crate::Result<Session> {
        self.sessions(&crate::sqlite::connect(&self.database)?, Some(id), None)?
            .sessions
            .into_iter()
            .next()
            .ok_or_else(|| format!("Session not found: {id}").into())
    }

    fn read(&self, session: &Session, _zh: bool) -> crate::Result<SessionData> {
        let connection = crate::sqlite::connect(&session.source_path)?;
        match self.kind {
            Kind::DeepChat => crate::deepchat::read(&connection, session),
            Kind::Cherry => crate::cherry::read(&connection, session),
            Kind::MiniMax => crate::minimax::read(&connection, session),
        }
    }

    fn search_roots(&self) -> Vec<(&'static str, PathBuf)> {
        self.search_roots.clone()
    }

    fn source_root(&self) -> &Path {
        self.database.parent().unwrap()
    }

    fn supports_format(&self, format: OutputFormat) -> bool {
        format != OutputFormat::Raw
    }

    fn json_payload(&self, data: &SessionData) -> Value {
        let mut payload = serde_json::to_value(data).unwrap();
        let fields = payload.as_object_mut().unwrap();
        for field in ["slug", "version", "summary_files"] {
            fields.remove(field);
        }
        if matches!(self.kind, Kind::MiniMax) {
            fields.insert(
                "stats".into(),
                serde_json::json!({"message_count": data.messages.len()}),
            );
        }
        payload
    }
}

pub fn app_data(name: &str) -> crate::Result<PathBuf> {
    let root = if cfg!(target_os = "macos") {
        crate::file_sessions::environment_root("HOME", "")?.join("Library/Application Support")
    } else if cfg!(target_os = "windows") {
        crate::file_sessions::environment_root("APPDATA", "AppData/Roaming")?
    } else {
        crate::file_sessions::environment_root("XDG_CONFIG_HOME", ".config")?
    };
    Ok(root.join(name))
}

pub fn timestamp(value: &Value) -> Option<Timestamp> {
    value
        .as_f64()
        .or_else(|| value.as_str()?.trim().parse().ok())
        .and_then(|value| crate::session::epoch_seconds(value / 1000.0))
}

pub fn require_tables(connection: &Connection, tables: &[&str]) -> crate::Result<()> {
    for table in tables {
        if !crate::sqlite::has_table(connection, table)? {
            return Err(format!("Unsupported database schema: missing {table}").into());
        }
    }
    Ok(())
}
