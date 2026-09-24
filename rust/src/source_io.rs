use std::fmt;
use std::fs::File;
use std::io;
use std::path::{Path, PathBuf};

#[derive(Debug)]
pub struct Error {
    pub kind: &'static str,
    code: i32,
    reason: String,
    path: PathBuf,
    destination: Option<PathBuf>,
}

impl Error {
    pub fn rename(path: &Path, destination: &Path, error: io::Error) -> Self {
        let mut error = Self::new(path, error);
        error.destination = Some(destination.into());
        error
    }

    pub fn new(path: &Path, error: io::Error) -> Self {
        let (kind, code, reason) = match error.kind() {
            io::ErrorKind::NotFound => ("FileNotFoundError", 2, "No such file or directory"),
            io::ErrorKind::PermissionDenied => ("PermissionError", 13, "Permission denied"),
            io::ErrorKind::AlreadyExists => ("FileExistsError", 17, "File exists"),
            io::ErrorKind::NotADirectory => ("NotADirectoryError", 20, "Not a directory"),
            io::ErrorKind::IsADirectory => ("IsADirectoryError", 21, "Is a directory"),
            _ => ("OSError", error.raw_os_error().unwrap_or(5), ""),
        };
        Self {
            kind,
            code,
            reason: if reason.is_empty() {
                error.to_string().split(" (os error").next().unwrap().into()
            } else {
                reason.into()
            },
            path: path.into(),
            destination: None,
        }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "[Errno {}] {}: {}",
            self.code,
            self.reason,
            crate::value::repr(&self.path.to_string_lossy().as_ref().into())
        )?;
        if let Some(destination) = &self.destination {
            write!(
                formatter,
                " -> {}",
                crate::value::repr(&destination.to_string_lossy().as_ref().into())
            )?;
        }
        Ok(())
    }
}
impl std::error::Error for Error {}

pub fn at<T>(path: &Path, result: io::Result<T>) -> crate::Result<T> {
    result.map_err(|error| Error::new(path, error).into())
}

pub fn open(path: &Path) -> crate::Result<File> {
    if path.is_dir() {
        return Err(Error::new(
            path,
            io::Error::from(if cfg!(windows) {
                io::ErrorKind::PermissionDenied
            } else {
                io::ErrorKind::IsADirectory
            }),
        )
        .into());
    }
    at(path, File::open(path))
}

pub fn read(path: &Path) -> crate::Result<Vec<u8>> {
    use io::Read;
    let mut bytes = Vec::new();
    at(path, open(path)?.read_to_end(&mut bytes))?;
    Ok(bytes)
}
