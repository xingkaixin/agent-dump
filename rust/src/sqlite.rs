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
                    serde_json::Number::from_f64(value).map_or(Value::Null, Value::Number)
                }
                ValueRef::Text(value) => std::str::from_utf8(value)?.into(),
                ValueRef::Blob(_) => {
                    return Err(format!("Unexpected SQLite blob in column {name}").into());
                }
            };
            record.insert(name.clone(), value);
        }
        result.push(record.into());
    }
    Ok(result)
}
