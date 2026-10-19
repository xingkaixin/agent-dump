use agent_dump_core::config::LoggingConfig;
use agent_dump_core::output::i18n::terminal;
use agent_dump_core::query::transcript::search_value;
use agent_dump_core::session::timestamp::Timestamp;
use agent_dump_core::storage::source_io::path_text;
use agent_dump_core::storage::{private_files, source_io};
use serde_json::{Value, json};
use std::io::Write;
use std::sync::Mutex;

pub struct Logger {
    config: LoggingConfig,
    run_id: String,
    failed: Mutex<bool>,
    zh: bool,
}
impl Logger {
    pub fn new(config: LoggingConfig, zh: bool) -> Self {
        Self {
            config,
            run_id: uuid::Uuid::new_v4().to_string(),
            failed: Mutex::new(false),
            zh,
        }
    }
    #[allow(
        clippy::significant_drop_tightening,
        reason = "Serialize writes and emit only one failure warning across concurrent workers"
    )]
    pub fn log(&self, event: &str, payload: Value) {
        if !self.config.enabled {
            return;
        }
        let mut failed = self.failed.lock().unwrap();
        if *failed {
            return;
        }
        let mut record = json!({"timestamp": Timestamp::now().iso_local(), "event":event, "run_id":self.run_id});
        if let Value::Object(payload) = payload {
            record.as_object_mut().unwrap().extend(payload);
        }
        let path = &self.config.path;
        let write = || -> crate::Result<()> {
            if let Some(parent) = path.parent() {
                private_files::ensure_directory(parent)?;
            }
            let mut options = std::fs::OpenOptions::new();
            options.create(true).append(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let mut file = options
                .open(path)
                .map_err(|e| source_io::Error::new(path, &e))?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = file
                    .set_permissions(std::fs::Permissions::from_mode(0o600));
            }
            writeln!(file, "{}", search_value(&record))?;
            Ok(())
        };
        if let Err(error) = write() {
            *failed = true;
            eprintln!(
                "{}",
                terminal(
                    "COLLECT_LOG_WRITE_FAILED",
                    self.zh,
                    &[("path", path_text(path)), ("error", error.to_string())]
                )
            );
        }
    }
}
