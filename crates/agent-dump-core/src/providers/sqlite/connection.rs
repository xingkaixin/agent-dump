use rusqlite::{Connection, OpenFlags, types::ValueRef};
use serde_json::{Map, Value};
use std::path::Path;

pub fn change_sources(path: &Path) -> Vec<std::path::PathBuf> {
    let mut wal = path.as_os_str().to_owned();
    wal.push("-wal");
    vec![path.to_owned(), wal.into()]
}

pub fn connect(path: &Path) -> crate::Result<Connection> {
    let path = path.canonicalize()?;
    let connection = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    connection.busy_timeout(std::time::Duration::from_secs(5))?;
    connection.execute_batch("PRAGMA query_only = ON; BEGIN")?;
    Ok(connection)
}

pub fn has_table(connection: &Connection, name: &str) -> crate::Result<bool> {
    Ok(connection.query_row(
        "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?)",
        [name],
        |row| row.get(0),
    )?)
}

pub fn rows(
    connection: &Connection,
    sql: &str,
    parameters: &[&dyn rusqlite::ToSql],
) -> crate::Result<Vec<Value>> {
    let mut statement = connection.prepare(sql)?;
    let names: Vec<String> = statement
        .column_names()
        .iter()
        .map(|name| (*name).into())
        .collect();
    let mut rows = statement.query(parameters)?;
    let mut result = Vec::new();
    while let Some(row) = rows.next()? {
        let mut record = Map::new();
        for (index, name) in names.iter().enumerate() {
            let value = match row.get_ref(index)? {
                ValueRef::Null => Value::Null,
                ValueRef::Integer(value) => value.into(),
                ValueRef::Real(value) => {
                    crate::compat::json::float(value).into()
                }
                ValueRef::Text(value) => std::str::from_utf8(value)?.into(),
                ValueRef::Blob(bytes) => {
                    bytes.iter().copied().map(Value::from).collect()
                }
            };
            record.insert(name.clone(), value);
        }
        result.push(record.into());
    }
    Ok(result)
}

pub fn json_cell(value: &Value) -> crate::Result<Value> {
    match value {
        Value::String(text) => crate::compat::json::from_str(text),
        // A raw SQLite cell cannot contain an array; rows uses it only for BLOB bytes.
        Value::Array(bytes) => crate::compat::json::from_bytes(
            &bytes
                .iter()
                .map(|byte| {
                    u8::try_from(byte.as_u64().unwrap())
                        .expect("SQLite blob cells contain bytes")
                })
                .collect::<Vec<_>>(),
        ),
        _ => Err(crate::providers::error::ProviderError::Cause {
            kind: "TypeError",
            message: format!(
                "the JSON object must be str, bytes or bytearray, not {}",
                crate::compat::value::type_name(value)
            ),
        }
        .into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn readonly_transaction_keeps_one_snapshot_during_committed_changes() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("source.sqlite");
        let writer = Connection::open(&path).unwrap();
        writer.execute_batch("PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; CREATE TABLE messages (body TEXT); INSERT INTO messages VALUES ('before')").unwrap();
        let reader = connect(&path).unwrap();
        let read = |connection: &Connection| {
            rows(connection, "SELECT body FROM messages", &[]).unwrap()
        };
        assert_eq!(read(&reader)[0]["body"], "before");
        writer
            .execute("UPDATE messages SET body = 'after'", [])
            .unwrap();
        let persistent = change_sources(&path);
        let before: Vec<_> = persistent
            .iter()
            .map(std::fs::read)
            .collect::<Result<_, _>>()
            .unwrap();
        assert_eq!(read(&reader)[0]["body"], "before");
        assert!(reader.execute("DELETE FROM messages", []).is_err());
        drop(reader);
        assert_eq!(read(&connect(&path).unwrap())[0]["body"], "after");
        assert_eq!(
            persistent
                .iter()
                .map(std::fs::read)
                .collect::<Result<Vec<_>, _>>()
                .unwrap(),
            before
        );
    }
}
