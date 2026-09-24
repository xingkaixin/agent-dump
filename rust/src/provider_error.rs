use std::fmt;
use std::path::Path;

pub type LocalizedText = [&'static str; 2];

#[derive(Debug)]
pub enum ProviderError {
    Cause {
        kind: &'static str,
        message: String,
    },
    Message(LocalizedText),
    Diagnostic {
        summary: LocalizedText,
        details: Vec<String>,
        roots: Vec<String>,
        capability: Option<LocalizedText>,
        next_steps: Vec<LocalizedText>,
    },
}

impl ProviderError {
    pub fn invalid(message: impl Into<String>) -> Self {
        Self::Cause {
            kind: "ValueError",
            message: message.into(),
        }
    }

    pub fn capability(
        summary: LocalizedText,
        capability: LocalizedText,
        details: Vec<String>,
    ) -> Self {
        Self::Diagnostic {
            summary,
            details,
            roots: Vec::new(),
            capability: Some(capability),
            next_steps: Vec::new(),
        }
    }

    pub fn missing(
        summary: LocalizedText,
        path: &Path,
        details: Vec<String>,
        roots: Vec<String>,
        next_steps: Vec<LocalizedText>,
    ) -> Self {
        Self::Diagnostic {
            summary,
            details: std::iter::once(format!(
                "missing path: {}",
                crate::source_io::path_text(path)
            ))
            .chain(details)
            .collect(),
            roots,
            capability: None,
            next_steps,
        }
    }

    pub fn summary(&self, zh: bool) -> &str {
        match self {
            Self::Cause { message, .. } => message,
            Self::Message(summary) | Self::Diagnostic { summary, .. } => summary[usize::from(zh)],
        }
    }
}

impl fmt::Display for ProviderError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.summary(false))
    }
}

impl std::error::Error for ProviderError {}

pub fn message(error: &(dyn std::error::Error + 'static), zh: bool) -> String {
    let error = original(error);
    if let Some(error) = error.downcast_ref::<ProviderError>() {
        return error.summary(zh).to_owned();
    }
    match error.downcast_ref::<rusqlite::Error>() {
        Some(rusqlite::Error::SqlInputError { msg, .. }) => msg.clone(),
        Some(rusqlite::Error::SqliteFailure(failure, _))
            if failure.code == rusqlite::ErrorCode::CannotOpen =>
        {
            "unable to open database file".into()
        }
        Some(rusqlite::Error::SqliteFailure(_, Some(message))) => message.clone(),
        _ => error.to_string(),
    }
}

pub fn kind(error: &(dyn std::error::Error + 'static)) -> Option<&'static str> {
    let error = original(error);
    match error.downcast_ref::<ProviderError>() {
        Some(ProviderError::Cause { kind, .. }) => Some(*kind),
        Some(ProviderError::Message(_)) => Some("ValueError"),
        Some(ProviderError::Diagnostic {
            capability: Some(_),
            ..
        }) => Some("DiagnosticCapabilityError"),
        Some(ProviderError::Diagnostic {
            capability: None, ..
        }) => Some("DiagnosticFileNotFoundError"),
        None if error.is::<crate::source_io::Error>() => Some(
            error
                .downcast_ref::<crate::source_io::Error>()
                .unwrap()
                .kind,
        ),
        None if error.is::<crate::python_json::Error>() => Some(
            error
                .downcast_ref::<crate::python_json::Error>()
                .unwrap()
                .kind,
        ),
        None => match error.downcast_ref::<rusqlite::Error>() {
            Some(rusqlite::Error::SqliteFailure(failure, _))
                if matches!(
                    failure.code,
                    rusqlite::ErrorCode::NotADatabase | rusqlite::ErrorCode::DatabaseCorrupt
                ) =>
            {
                Some("DatabaseError")
            }
            Some(rusqlite::Error::SqliteFailure(..) | rusqlite::Error::SqlInputError { .. }) => {
                Some("OperationalError")
            }
            _ => None,
        },
    }
}

pub fn operation_message(error: &(dyn std::error::Error + 'static), zh: bool) -> String {
    let kind = kind(error);
    let summary = message(error, zh);
    match kind {
        Some(kind) => format!("{kind}: {summary}"),
        None => summary,
    }
}

pub fn original<'a>(
    mut error: &'a (dyn std::error::Error + 'static),
) -> &'a (dyn std::error::Error + 'static) {
    while error.is::<crate::session_data::SharedReadError>() {
        error = error.source().unwrap();
    }
    error
}
