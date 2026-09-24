use crate::provider::{DiagnosticSink, RecoverableDiagnostic};
use serde_json::Value;
use std::fs::File;
use std::io::{self, BufRead, BufReader, Read, Seek, SeekFrom};
use std::path::Path;

pub const FULL_SCAN_LIMIT: u64 = 256 * 1024;
const WINDOW: u64 = 64 * 1024;

pub struct Metadata {
    pub header: Option<Value>,
    pub records: Vec<Value>,
    pub tail: Option<Value>,
    pub complete: bool,
}

fn object(bytes: &[u8]) -> Option<Value> {
    crate::python_json::from_slice(bytes)
        .ok()
        .filter(Value::is_object)
}

fn nonempty(bytes: &[u8]) -> bool {
    bytes.iter().any(|byte| !byte.is_ascii_whitespace())
}

pub fn metadata(path: &Path, head_lines: usize) -> io::Result<Metadata> {
    let mut file = File::open(path)?;
    let size = file.metadata()?.len();
    let mut bytes = Vec::new();
    if size <= FULL_SCAN_LIMIT {
        file.read_to_end(&mut bytes)?;
        let lines: Vec<_> = bytes
            .split(|byte| *byte == b'\n')
            .filter(|line| nonempty(line))
            .collect();
        return Ok(Metadata {
            header: lines.first().and_then(|line| object(line)),
            records: lines.iter().filter_map(|line| object(line)).collect(),
            tail: None,
            complete: true,
        });
    }
    file.by_ref().take(WINDOW).read_to_end(&mut bytes)?;
    let end = bytes.iter().rposition(|byte| *byte == b'\n');
    let lines: Vec<_> = end
        .map(|end| {
            bytes[..=end]
                .split(|byte| *byte == b'\n')
                .take(head_lines)
                .filter(|line| nonempty(line))
                .collect()
        })
        .unwrap_or_default();
    let header = if end.is_none() {
        Some(serde_json::json!({}))
    } else {
        lines.first().and_then(|line| object(line))
    };
    let records = lines.iter().filter_map(|line| object(line)).collect();
    file.seek(SeekFrom::Start(size - WINDOW))?;
    let mut tail = Vec::new();
    file.take(WINDOW).read_to_end(&mut tail)?;
    let tail_record = tail
        .iter()
        .position(|byte| *byte == b'\n')
        .and_then(|start| {
            let end = tail.iter().rposition(|byte| *byte == b'\n')?;
            tail[start + 1..=end]
                .split(|byte| *byte == b'\n')
                .rev()
                .find(|line| nonempty(line))
                .and_then(object)
        });
    Ok(Metadata {
        header,
        records,
        tail: tail_record,
        complete: false,
    })
}

pub fn scan(
    path: &Path,
    diagnostics: &mut DiagnosticSink<'_>,
    mut append: impl FnMut(Value, &mut DiagnosticSink<'_>) -> crate::Result<()>,
) -> crate::Result<()> {
    scan_numbered(path, diagnostics, |_, record, diagnostics| {
        append(record, diagnostics)
    })
}

pub fn scan_numbered(
    path: &Path,
    diagnostics: &mut DiagnosticSink<'_>,
    mut append: impl FnMut(usize, Value, &mut DiagnosticSink<'_>) -> crate::Result<()>,
) -> crate::Result<()> {
    let mut reader = BufReader::new(File::open(path)?);
    let mut line = Vec::new();
    let mut number = 0;
    let mut skipped = Vec::new();
    let mut count = 0;
    loop {
        line.clear();
        if reader.read_until(b'\n', &mut line)? == 0 {
            break;
        }
        number += 1;
        if !nonempty(&line) {
            continue;
        }
        if let Some(value) = object(&line) {
            append(number, value, diagnostics)?;
        } else if matches!(line.last(), Some(b'\n' | b'\r')) {
            count += 1;
            if skipped.len() < 5 {
                skipped.push(number);
            }
        }
    }
    if count > 0 {
        diagnostics(RecoverableDiagnostic::JsonlRecordsSkipped {
            path: path.to_owned(),
            count,
            lines: skipped,
        })?;
    }
    Ok(())
}
