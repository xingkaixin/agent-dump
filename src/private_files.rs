use std::fs;
use std::io::Write;
use std::path::Path;

pub fn sync(file: &fs::File) -> std::io::Result<()> {
    // Match Python's os.fsync; Apple's std::fs::File::sync_all uses F_FULLFSYNC.
    #[cfg(target_vendor = "apple")]
    return nix::unistd::fsync(file).map_err(Into::into);
    #[cfg(not(target_vendor = "apple"))]
    file.sync_all()
}

pub fn ensure_directory(path: &Path) -> crate::Result<()> {
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
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            if let Some(parent) = path.parent() {
                ensure_directory(parent)?;
            }
            builder.create(path)
        }
        result => result,
    };
    match result {
        Err(_) if path.is_dir() => Ok(()),
        result => result.map_err(|error| crate::source_io::Error::native(path, error).into()),
    }
}

pub fn write_text(path: &Path, text: &str) -> crate::Result<()> {
    let directory = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    ensure_directory(directory)?;
    let filename = path
        .file_name()
        .ok_or("Invalid output filename")?
        .to_string_lossy();
    let mut temporary = tempfile::Builder::new()
        .prefix(&format!(".{filename}."))
        .suffix(".tmp")
        .rand_bytes(8)
        .tempfile_in(directory)?;
    #[cfg(windows)]
    let text = &text.replace('\n', "\r\n");
    temporary.write_all(text.as_bytes())?;
    sync(temporary.as_file())?;
    temporary
        .persist(path)
        .map_err(|error| crate::source_io::Error::rename(error.file.path(), path, error.error))?;
    Ok(())
}
