use crate::providers::contract::{DiagnosticSink, RecoverableDiagnostic};
use crate::providers::jsonl;
use serde_json::Value;
use std::collections::HashSet;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};

#[allow(
    clippy::case_sensitive_file_extension_comparisons,
    reason = "Codex writes lowercase rollout names"
)]
pub fn is_rollout(path: &Path) -> bool {
    path.file_name()
        .and_then(|name| name.to_str())
        .is_some_and(|name| {
            name.starts_with("rollout-")
                && (name.ends_with(".jsonl") || name.ends_with(".jsonl.zst"))
        })
}

pub fn compressed(path: &Path) -> bool {
    path.extension().is_some_and(|extension| extension == "zst")
}

pub fn stem(path: &Path) -> String {
    let name = path.file_name().unwrap_or_default().to_string_lossy();
    let name = name.strip_suffix(".zst").unwrap_or(&name);
    name.strip_suffix(".jsonl").unwrap_or(name).to_owned()
}

/// Codex keeps the plain rollout while it may still append to it.
pub fn prefer_plain(paths: &mut Vec<PathBuf>) {
    let plain: HashSet<_> = paths
        .iter()
        .filter(|path| !compressed(path))
        .cloned()
        .collect();
    paths.retain(|path| {
        !compressed(path) || !plain.contains(&path.with_extension(""))
    });
}

pub fn open(path: &Path) -> crate::Result<Box<dyn Read>> {
    let file = crate::storage::source_io::open(path)?;
    if !compressed(path) {
        return Ok(Box::new(file));
    }
    let decoder = ruzstd::decoding::StreamingDecoder::new(file)
        .map_err(|error| format!("{}: {error}", path.display()))?;
    Ok(Box::new(decoder))
}

pub fn scan(
    path: &Path,
    diagnostics: &mut DiagnosticSink<'_>,
    mut append: impl FnMut(Value, &mut DiagnosticSink<'_>) -> crate::Result<()>,
) -> crate::Result<()> {
    if !compressed(path) {
        return jsonl::scan(path, diagnostics, append);
    }
    let mut skipped = Vec::new();
    let mut count = 0;
    lines(path, |number, line, terminated| {
        if let Some(value) = object(line) {
            append(value, diagnostics)?;
        } else if terminated {
            count += 1;
            if skipped.len() < 5 {
                skipped.push(number);
            }
        }
        Ok(true)
    })?;
    if count > 0 {
        diagnostics(RecoverableDiagnostic::JsonlRecordsSkipped {
            path: path.to_owned(),
            count,
            lines: skipped,
        })?;
    }
    Ok(())
}

/// Visits non-blank lines with their 1-based numbers until `visit` stops.
pub fn lines(
    path: &Path,
    mut visit: impl FnMut(usize, &[u8], bool) -> crate::Result<bool>,
) -> crate::Result<()> {
    let mut reader = BufReader::new(open(path)?);
    let mut line = Vec::new();
    let mut number = 0;
    loop {
        line.clear();
        if crate::storage::source_io::at(
            path,
            reader.read_until(b'\n', &mut line),
        )? == 0
        {
            return Ok(());
        }
        number += 1;
        let terminated = matches!(line.last(), Some(b'\n' | b'\r'));
        if !line.iter().all(u8::is_ascii_whitespace)
            && !visit(number, &line, terminated)?
        {
            return Ok(());
        }
    }
}

pub fn object(line: &[u8]) -> Option<Value> {
    crate::compat::json::from_slice(line)
        .ok()
        .filter(Value::is_object)
}
