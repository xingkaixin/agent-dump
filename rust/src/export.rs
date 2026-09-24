use sha2::{Digest, Sha256};
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

fn filename(id: &str) -> crate::Result<String> {
    let normalized = id.replace('\\', "/");
    let name = normalized
        .rsplit('/')
        .find(|component| !component.is_empty() && *component != ".")
        .unwrap_or("");
    let reason = if matches!(name, "" | "." | "..") {
        Some("no usable filename component")
    } else if crate::render::safe_body(name) != name || name.contains(['\t', '\n']) {
        Some("filename contains a control character")
    } else {
        None
    };
    if let Some(reason) = reason {
        return Err(crate::provider_error::ProviderError::Diagnostic {
            summary: ["session id cannot be used as an export filename"; 2],
            details: vec![
                format!("session id: {}", crate::value::repr(&id.into())),
                format!("reason: {reason}"),
            ],
            roots: Vec::new(),
            capability: Some(["session id does not produce a safe filename"; 2]),
            next_steps: vec![[
                "Pick another session, or fix the session id in the provider data.",
                "选择其他会话，或修复 provider 数据中的 session id。",
            ]],
        }
        .into());
    }
    let edge = |c: char| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-';
    let stem = name.split('.').next().unwrap_or("");
    let reserved = matches!(stem, "aux" | "con" | "nul" | "prn")
        || (1..=9).any(|i| stem == format!("com{i}") || stem == format!("lpt{i}"));
    if id == name
        && id.len() <= 120
        && id.starts_with(edge)
        && id.ends_with(edge)
        && id.chars().all(|c| edge(c) || c == '.')
        && !reserved
    {
        Ok(id.to_owned())
    } else {
        Ok(format!("~{:x}", Sha256::digest(id.as_bytes())))
    }
}

fn absolute_existing_ancestor(path: &Path) -> crate::Result<PathBuf> {
    if path.exists() {
        return Ok(path.canonicalize()?);
    }
    let parent = path.parent().ok_or("Cannot resolve output path")?;
    Ok(absolute_existing_ancestor(parent)?.join(path.file_name().ok_or("Invalid output path")?))
}

fn ensure_directory(path: &Path) -> crate::Result<()> {
    if path.as_os_str().is_empty() {
        return Ok(());
    }
    let builder = fs::DirBuilder::new();
    #[cfg(unix)]
    let builder = {
        use std::os::unix::fs::DirBuilderExt;
        let mut builder = builder;
        builder.mode(0o700);
        builder
    };
    let result = match builder.create(path) {
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            if let Some(parent) = path.parent() {
                ensure_directory(parent)?;
            }
            builder.create(path)
        }
        result => result,
    };
    match result {
        Err(_) if path.is_dir() => Ok(()),
        result => crate::source_io::at(path, result),
    }
}

fn write(
    output: &Path,
    session_id: &str,
    suffix: &str,
    source_root: &Path,
    contents: impl FnOnce(&mut fs::File) -> crate::Result<()>,
) -> crate::Result<PathBuf> {
    let directory = std::path::absolute(output)?;
    let resolved = absolute_existing_ancestor(&directory)?;
    if resolved.starts_with(source_root.canonicalize()?) {
        return Err("Export output must be outside the Provider source directory".into());
    }
    let output_path = output.join(format!("{}{suffix}", filename(session_id)?));
    let destination = std::path::absolute(&output_path)?;
    if destination.is_symlink() {
        return Err("Export destination must not be a symlink".into());
    }
    ensure_directory(output)?;
    let mut temporary = tempfile::Builder::new()
        .prefix(&format!(
            ".{}.",
            output_path.file_name().unwrap().to_string_lossy()
        ))
        .suffix(".tmp")
        .rand_bytes(8)
        .tempfile_in(&directory)?;
    contents(temporary.as_file_mut())?;
    temporary.flush()?;
    temporary.as_file().sync_all()?;
    temporary.persist(&destination).map_err(|error| {
        crate::source_io::Error::rename(error.file.path(), &output_path, error.error)
    })?;
    Ok(output_path)
}

pub fn json(
    session_id: &str,
    data: &impl serde::Serialize,
    output: &Path,
    source_root: &Path,
    suffix: &str,
) -> crate::Result<PathBuf> {
    write(output, session_id, suffix, source_root, |file| {
        let mut writer = io::BufWriter::new(file);
        data.serialize(&mut serde_json::Serializer::with_formatter(
            &mut writer,
            crate::python_json::Formatter::default(),
        ))?;
        writer.flush()?;
        Ok(())
    })
}

pub fn markdown(
    session_id: &str,
    text: &str,
    output: &Path,
    source_root: &Path,
) -> crate::Result<PathBuf> {
    write(output, session_id, ".md", source_root, |file| {
        file.write_all(text.as_bytes())?;
        Ok(())
    })
}

pub fn raw(
    session_id: &str,
    source: &Path,
    output: &Path,
    source_root: &Path,
) -> crate::Result<PathBuf> {
    write(output, session_id, ".raw.jsonl", source_root, |file| {
        io::copy(&mut fs::File::open(source)?, file)?;
        Ok(())
    })
}
