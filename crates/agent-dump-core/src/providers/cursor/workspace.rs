use crate::compat::value::text;
use serde_json::Value;
use std::collections::HashMap;
use std::path::{Component, Path, PathBuf};

pub fn directories(user: &Path) -> HashMap<String, String> {
    let mut result = HashMap::new();
    let Ok(entries) = std::fs::read_dir(user.join("workspaceStorage")) else {
        return result;
    };
    let mut entries: Vec<_> = entries.flatten().collect();
    entries.sort_by_key(std::fs::DirEntry::file_name);
    for entry in entries {
        if !entry.file_type().is_ok_and(|kind| kind.is_dir()) {
            continue;
        }
        let path = entry.path();
        let Some(directory) = std::fs::read(path.join("workspace.json"))
            .ok()
            .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
            .and_then(|value| folder(&value))
        else {
            continue;
        };
        for id in composer_ids(&path.join("state.vscdb")) {
            result.insert(id, directory.clone());
        }
    }
    result
}

fn folder(workspace: &Value) -> Option<String> {
    let uri = [&workspace["folder"], &workspace["workspace"]]
        .into_iter()
        .map(text)
        .find(|value| !value.is_empty())?;
    decode(uri.strip_prefix("file://").unwrap_or(uri))
        .map(|path| normalize(&path))
}

fn composer_ids(database: &Path) -> Vec<String> {
    let Ok(connection) =
        crate::providers::sqlite::connection::connect(database)
    else {
        return Vec::new();
    };
    let Ok(raw) = connection.query_row(
        "SELECT value FROM ItemTable WHERE key = 'composer.composerData'",
        [],
        |row| row.get::<_, String>(0),
    ) else {
        return Vec::new();
    };
    let Ok(data) = serde_json::from_str::<Value>(&raw) else {
        return Vec::new();
    };
    data["allComposers"]
        .as_array()
        .or_else(|| data.as_array())
        .into_iter()
        .flatten()
        .filter_map(|composer| {
            [&composer["composerId"], &composer["id"]]
                .into_iter()
                .map(text)
                .find(|id| !id.is_empty())
                .map(str::to_owned)
        })
        .collect()
}

fn decode(value: &str) -> Option<String> {
    let mut bytes = Vec::with_capacity(value.len());
    let mut iter = value.bytes();
    while let Some(byte) = iter.next() {
        if byte == b'%' {
            let high = char::from(iter.next()?).to_digit(16)?;
            let low = char::from(iter.next()?).to_digit(16)?;
            bytes.push(u8::try_from(high * 16 + low).ok()?);
        } else {
            bytes.push(byte);
        }
    }
    String::from_utf8(bytes).ok()
}

fn normalize(value: &str) -> String {
    let mut path = PathBuf::new();
    for part in Path::new(value).components() {
        match part {
            Component::CurDir => {}
            Component::ParentDir
                if path.file_name().is_some_and(|name| name != "..") =>
            {
                path.pop();
            }
            _ => path.push(part.as_os_str()),
        }
    }
    let mut result = path.to_string_lossy().into_owned();
    if result.is_empty() {
        result.push('.');
    }
    if value.ends_with(std::path::MAIN_SEPARATOR)
        && !result.ends_with(std::path::MAIN_SEPARATOR)
    {
        result.push(std::path::MAIN_SEPARATOR);
    }
    result
}
