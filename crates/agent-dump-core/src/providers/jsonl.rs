use crate::providers::contract::{DiagnosticSink, RecoverableDiagnostic};
use serde::de::{Deserializer, IgnoredAny, MapAccess, Visitor};
use serde_json::value::RawValue;
use serde_json::{Map, Value};
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom};
use std::path::Path;

pub const FULL_SCAN_LIMIT: u64 = 256 * 1024;
const WINDOW: u64 = 64 * 1024;

pub struct Metadata {
    pub header: Option<Value>,
    pub records: Vec<Value>,
    pub tail: Option<Value>,
    pub complete: bool,
}

/// Fields a provider reads from a record. `Fields` positions are only
/// indexed, so a non-object there is kept as null.
pub enum Shape {
    Leaf,
    Fields(&'static [(&'static str, Shape)]),
}

struct Pruned(&'static [(&'static str, Shape)]);

impl<'de> Visitor<'de> for Pruned {
    type Value = Map<String, Value>;

    fn expecting(
        &self,
        formatter: &mut std::fmt::Formatter<'_>,
    ) -> std::fmt::Result {
        formatter.write_str("a JSON object")
    }

    fn visit_map<A: MapAccess<'de>>(
        self,
        mut map: A,
    ) -> Result<Self::Value, A::Error> {
        let mut object = Map::new();
        while let Some(key) = map.next_key::<String>()? {
            if let Some((_, shape)) =
                self.0.iter().find(|(name, _)| *name == key)
            {
                let raw = map.next_value::<&RawValue>()?;
                let value = project(raw.get(), shape)
                    .map_err(serde::de::Error::custom)?;
                object.insert(key, value);
            } else {
                map.next_value::<IgnoredAny>()?;
            }
        }
        Ok(object)
    }
}

fn project(text: &str, shape: &'static Shape) -> serde_json::Result<Value> {
    match shape {
        Shape::Leaf => serde_json::from_str(text),
        Shape::Fields(fields) if text.starts_with('{') => {
            let mut deserializer = serde_json::Deserializer::from_str(text);
            let object = deserializer.deserialize_map(Pruned(fields))?;
            deserializer.end()?;
            Ok(Value::Object(object))
        }
        Shape::Fields(_) => Ok(Value::Null),
    }
}

fn object(bytes: &[u8]) -> Option<Value> {
    crate::compat::json::from_slice(bytes)
        .ok()
        .filter(Value::is_object)
}

fn pruned(bytes: &[u8], shape: &'static Shape) -> Option<Value> {
    let text = std::str::from_utf8(bytes).ok()?;
    let text = text.trim_start_matches([' ', '\t', '\n', '\r']);
    if !text.starts_with('{') {
        return None;
    }
    // Inputs serde_json rejects, such as NaN, take the compatible path.
    let Ok(mut value) = project(text, shape) else {
        return object(bytes);
    };
    crate::compat::json::normalize(&mut value);
    Some(value)
}

fn nonempty(bytes: &[u8]) -> bool {
    bytes.iter().any(|byte| !byte.is_ascii_whitespace())
}

/// Records after the first `head_lines` keep only the fields in `shape`.
pub fn metadata(
    path: &Path,
    head_lines: usize,
    shape: Option<&'static Shape>,
) -> crate::Result<Metadata> {
    let mut file = crate::storage::source_io::open(path)?;
    let size = file.metadata()?.len();
    let mut bytes = Vec::new();
    if size <= FULL_SCAN_LIMIT {
        crate::storage::source_io::at(path, file.read_to_end(&mut bytes))?;
        let lines: Vec<_> = bytes
            .split(|byte| *byte == b'\n')
            .filter(|line| nonempty(line))
            .collect();
        let mut records = Vec::new();
        for line in &lines {
            records.extend(match shape {
                Some(shape) if records.len() >= head_lines => {
                    pruned(line, shape)
                }
                _ => object(line),
            });
        }
        return Ok(Metadata {
            header: lines.first().and_then(|line| object(line)),
            records,
            tail: None,
            complete: true,
        });
    }
    crate::storage::source_io::at(
        path,
        file.by_ref().take(WINDOW).read_to_end(&mut bytes),
    )?;
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
    let tail_record =
        tail.iter()
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
    mut append: impl FnMut(
        usize,
        Value,
        &mut DiagnosticSink<'_>,
    ) -> crate::Result<()>,
) -> crate::Result<()> {
    let mut reader = BufReader::new(crate::storage::source_io::open(path)?);
    let mut line = Vec::new();
    let mut number = 0;
    let mut skipped = Vec::new();
    let mut count = 0;
    loop {
        line.clear();
        if crate::storage::source_io::at(
            path,
            reader.read_until(b'\n', &mut line),
        )? == 0
        {
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

#[cfg(test)]
mod tests {
    use super::*;

    static SHAPE: Shape = Shape::Fields(&[
        ("timestamp", Shape::Leaf),
        (
            "payload",
            Shape::Fields(&[
                ("type", Shape::Leaf),
                ("arguments", Shape::Fields(&[("model", Shape::Leaf)])),
            ]),
        ),
    ]);

    #[test]
    fn pruned_records_read_like_full_records() {
        let lines: [&[u8]; 12] = [
            br#"{"timestamp":"t","payload":{"type":"message","content":"x"}}"#,
            br#"{"timestamp":"t","payload":[{"type":"message"}]}"#,
            br#"{"payload":{"type":["message"]}}"#,
            br#"{"payload":{"type":{"kind":"message"}}}"#,
            br#"{"timestamp":"t","payload":{"type":"message","n":NaN}}"#,
            br#"{"timestamp":"a","timestamp":"b","payload":{"type":1}}"#,
            br#"  {"timestamp":"c","payload":{"arguments":"{}"}}"#,
            br#"{"payload":{"arguments":{"model":"m"}},"timestamp":1e999}"#,
            br#"[{"timestamp":"t"}]"#,
            br#"{"timestamp":"t"} trailing"#,
            b"{\"timestamp\":\"\xff\"}",
            br#"{"timestamp":"t","payload":"text"}"#,
        ];
        for line in lines {
            let full = object(line);
            let pruned = pruned(line, &SHAPE);
            assert_eq!(full.is_some(), pruned.is_some(), "{line:?}");
            let (Some(full), Some(pruned)) = (full, pruned) else {
                continue;
            };
            for path in [
                &["timestamp"][..],
                &["payload", "type"],
                &["payload", "arguments", "model"],
            ] {
                let read = |value: &Value| {
                    path.iter()
                        .fold(value.clone(), |value, key| value[key].clone())
                };
                assert_eq!(read(&full), read(&pruned), "{line:?} {path:?}");
            }
        }
    }
}
