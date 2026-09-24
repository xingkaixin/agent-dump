use std::path::Path;

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

pub fn basename(text: &str) -> Option<String> {
    Path::new(text.trim().trim_end_matches(['/', '\\']))
        .file_name()
        .and_then(|name| name.to_str())
        .and_then(normalize_title)
}
