use crate::compat::value::{integer, text};
use serde_json::Value;
use std::fmt::Write as _;
use std::sync::LazyLock;

const SAFE_INTEGER: i64 = 9_007_199_254_740_991;

pub struct Log {
    pub header: Value,
    pub events: Vec<Value>,
}

/// Returns the format version and whether the file is zstd compressed.
pub fn generation(name: &str) -> Option<(u64, bool)> {
    static NAME: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"^session(?:\.v(\d+))?\.jsonl(\.zstd)?$").unwrap()
    });
    let captures = NAME.captures(name)?;
    let version = match captures.get(1) {
        Some(version) => version.as_str().parse().ok()?,
        None => 0,
    };
    Some((version, captures.get(2).is_some()))
}

fn unit(code: u16, out: &mut String) {
    match u8::try_from(code) {
        Ok(byte) if byte.is_ascii_alphanumeric() || b"._-".contains(&byte) => {
            out.push(char::from(byte));
        }
        _ => write!(out, "~{code:04X}").unwrap(),
    }
}

/// The directory name DSH gives a session id.
pub fn encode(id: &str) -> Option<String> {
    if id.is_empty() {
        return None;
    }
    if id == "." || id == ".." {
        return Some("~002E".repeat(id.len()));
    }
    let mut out = String::new();
    id.encode_utf16().for_each(|code| unit(code, &mut out));
    Some(out)
}

/// The directory name DSH gives a working directory.
pub fn project(cwd: &str) -> Option<String> {
    if cwd.is_empty() {
        return None;
    }
    let mut slug = String::new();
    let mut separator = false;
    for code in cwd.encode_utf16() {
        if [u16::from(b'/'), u16::from(b'\\'), u16::from(b':')].contains(&code)
        {
            if !separator {
                slug.push('-');
            }
            separator = true;
        } else {
            unit(code, &mut slug);
            separator = false;
        }
    }
    let slug = slug.trim_start_matches('-');
    Some(if slug.is_empty() {
        "--root--".into()
    } else {
        format!("--{}--", &slug[..slug.len().min(251)])
    })
}

pub fn is_integer(value: &Value) -> bool {
    value
        .as_f64()
        .is_some_and(|n| n.fract() == 0.0 && n.abs() <= 9_007_199_254_740_991.0)
}

fn is_count(value: &Value) -> bool {
    is_integer(value) && value.as_f64().is_some_and(|n| n >= 0.0)
}

fn valid_header(header: &Value) -> bool {
    is_count(&header["version"])
        && header["type"] == "session"
        && header["id"].as_str().is_some_and(|id| !id.is_empty())
        && is_count(&header["createdAt"])
        && is_count(&header["delegationDepth"])
        && ["cwd", "parentSession", "agentPreset"]
            .iter()
            .all(|key| header.get(key).is_none_or(Value::is_string))
        && header["cwd"] != ""
        && header.get("seedLength").is_none_or(is_count)
        && header
            .get("origin")
            .is_none_or(|origin| origin == "subagent")
}

pub fn is_packed(row: &Value) -> bool {
    ["text-chunks", "reasoning-chunks", "tool-call-chunks"]
        .contains(&text(&row["type"]))
}

/// The first sequence number of a record and how many events it stands for;
/// a packed row holds a run of streamed `assistant/chunk` events.
fn span(row: &Value) -> Option<(i64, i64)> {
    if !is_packed(row) {
        let valid = !text(&row["type"]).is_empty()
            && is_count(&row["seq"])
            && is_integer(&row["time"]);
        return valid.then(|| (integer(&row["seq"]), 1));
    }
    if !is_count(&row["seq0"]) || !is_integer(&row["time0"]) {
        return None;
    }
    let data = &row["data"];
    let tool = row["type"] == "tool-call-chunks";
    let values = data[if tool { "args" } else { "texts" }].as_array()?;
    let gaps = data["dt"].as_array()?;
    let valid = ["turn", "step", "index"]
        .iter()
        .all(|key| data[key].is_number())
        && !values.is_empty()
        && values.iter().all(Value::is_string)
        && gaps.len() + 1 == values.len()
        && gaps.iter().all(is_integer)
        && (!tool
            || (data["id"].is_string()
                && data.get("name").is_none_or(Value::is_string)));
    if !valid {
        return None;
    }
    let mut time = integer(&row["time0"]);
    for gap in gaps {
        time = time.checked_add(integer(gap))?;
        if time.abs() > SAFE_INTEGER {
            return None;
        }
    }
    let seq = integer(&row["seq0"]);
    let count = i64::try_from(values.len()).ok()?;
    (seq + count - 1 <= SAFE_INTEGER).then_some((seq, count))
}

/// Reads a session log, or `None` when it is not a valid DSH log. A record
/// still being written at the end is ignored.
pub fn read(path: &std::path::Path) -> crate::Result<Option<Log>> {
    let compressed = path
        .file_name()
        .and_then(|name| generation(&name.to_string_lossy()))
        .is_some_and(|(_, compressed)| compressed);
    let bytes = crate::storage::source_io::read(path)?;
    if !compressed {
        let text = String::from_utf8_lossy(&bytes);
        let end = text.rfind('\n');
        return Ok(end.and_then(|end| decode(text[..end].split('\n'))));
    }
    let Ok((frames, _)) = crate::storage::zstd::frames(&bytes) else {
        return Ok(None);
    };
    let frames: Vec<_> = frames
        .iter()
        .map(|frame| String::from_utf8_lossy(frame))
        .collect();
    let mut records = Vec::new();
    for (index, frame) in frames.iter().enumerate() {
        let Some(frame) = frame.strip_suffix('\n') else {
            return Ok(None);
        };
        // DSH writes the header alone in the first frame.
        if index == 0 && frame.contains('\n') {
            return Ok(None);
        }
        records.extend(frame.split('\n'));
    }
    Ok(decode(records.into_iter()))
}

fn decode<'a>(mut lines: impl Iterator<Item = &'a str>) -> Option<Log> {
    let header: Value = serde_json::from_str(lines.next()?).ok()?;
    if !valid_header(&header) {
        return None;
    }
    let mut events = Vec::new();
    let mut next = 0;
    for line in lines {
        let event: Value = serde_json::from_str(line).ok()?;
        let (seq, count) = span(&event)?;
        if seq != next {
            return None;
        }
        next += count;
        events.push(event);
    }
    (integer(&header["seedLength"]) <= next).then_some(Log { header, events })
}
