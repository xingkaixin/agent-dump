#[derive(Clone, Copy, PartialEq)]
pub enum OutputFormat {
    Json,
    Markdown,
    Raw,
    Print,
}

impl OutputFormat {
    pub fn name(self) -> &'static str {
        match self {
            Self::Json => "json",
            Self::Markdown => "markdown",
            Self::Raw => "raw",
            Self::Print => "print",
        }
    }
}

pub fn parse(spec: &str) -> crate::Result<Vec<OutputFormat>> {
    let mut formats = Vec::new();
    for value in spec.split(',') {
        let format = match value.trim().to_lowercase().as_str() {
            "json" => OutputFormat::Json,
            "markdown" | "md" => OutputFormat::Markdown,
            "raw" => OutputFormat::Raw,
            "print" => OutputFormat::Print,
            _ => return Err(format!("Invalid output format: {value:?}").into()),
        };
        if !formats.contains(&format) {
            formats.push(format);
        }
    }
    Ok(formats)
}
