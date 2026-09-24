use std::fmt;
use std::path::Path;

pub type LocalizedText = [&'static str; 2];

#[derive(Debug)]
pub enum ProviderError {
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
            details: std::iter::once(format!("missing path: {}", path.display()))
                .chain(details)
                .collect(),
            roots,
            capability: None,
            next_steps,
        }
    }

    pub fn summary(&self, zh: bool) -> &'static str {
        match self {
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
    error
        .downcast_ref::<ProviderError>()
        .map_or_else(|| error.to_string(), |error| error.summary(zh).to_owned())
}

pub fn operation_message(error: &(dyn std::error::Error + 'static), zh: bool) -> String {
    let kind = match error.downcast_ref::<ProviderError>() {
        Some(ProviderError::Message(_)) => Some("ValueError"),
        Some(ProviderError::Diagnostic {
            capability: Some(_),
            ..
        }) => Some("DiagnosticCapabilityError"),
        Some(ProviderError::Diagnostic {
            capability: None, ..
        }) => Some("DiagnosticFileNotFoundError"),
        None => match error.downcast_ref::<rusqlite::Error>() {
            Some(rusqlite::Error::SqliteFailure(failure, _))
                if failure.code == rusqlite::ErrorCode::NotADatabase =>
            {
                Some("DatabaseError")
            }
            _ => None,
        },
    };
    let summary = message(error, zh);
    match kind {
        Some(kind) => format!("{kind}: {summary}"),
        None => summary,
    }
}
