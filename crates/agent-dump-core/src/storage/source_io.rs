use std::fmt;
use std::fs::File;
use std::io;
use std::path::{Path, PathBuf};
pub fn path_text(path: &Path) -> String {
    if cfg!(windows) {
        path.to_string_lossy().replace('/', "\\")
    } else {
        path.to_string_lossy().into_owned()
    }
}

#[derive(Debug)]
pub struct Error {
    pub kind: &'static str,
    code: i32,
    origin: &'static str,
    reason: String,
    path: PathBuf,
    destination: Option<PathBuf>,
}

impl Error {
    pub fn rename(path: &Path, destination: &Path, error: &io::Error) -> Self {
        let mut error = Self::native(path, error);
        error.destination = Some(destination.into());
        error
    }
    pub fn native(path: &Path, error: &io::Error) -> Self {
        // Python's mkdir/replace report WinError; file reads report CRT errno.
        let native = if cfg!(windows) {
            error.raw_os_error().map(|code| {
                let reason = error.to_string();
                (
                    code,
                    reason
                        .split(" (os error")
                        .next()
                        .unwrap()
                        .trim_end_matches('.')
                        .to_owned(),
                )
            })
        } else {
            None
        };
        let mut error = Self::new(path, error);
        if let Some((code, reason)) = native {
            error.code = code;
            error.reason = reason;
            error.origin = "WinError";
        }
        error
    }
    pub fn new(path: &Path, error: &io::Error) -> Self {
        let (kind, code, reason) = match error.kind() {
            io::ErrorKind::NotFound => {
                ("FileNotFoundError", 2, "No such file or directory")
            }
            io::ErrorKind::PermissionDenied => {
                ("PermissionError", 13, "Permission denied")
            }
            io::ErrorKind::AlreadyExists => {
                ("FileExistsError", 17, "File exists")
            }
            io::ErrorKind::NotADirectory => {
                ("NotADirectoryError", 20, "Not a directory")
            }
            io::ErrorKind::IsADirectory => {
                ("IsADirectoryError", 21, "Is a directory")
            }
            _ => ("OSError", error.raw_os_error().unwrap_or(5), ""),
        };
        Self {
            kind,
            code,
            origin: "Errno",
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
            "[{} {}] {}: {}",
            self.origin,
            self.code,
            self.reason,
            crate::compat::value::repr(&path_text(&self.path).into())
        )?;
        if let Some(destination) = &self.destination {
            write!(
                formatter,
                " -> {}",
                crate::compat::value::repr(&path_text(destination).into())
            )?;
        }
        Ok(())
    }
}
impl std::error::Error for Error {}

pub fn at<T>(path: &Path, result: io::Result<T>) -> crate::Result<T> {
    result.map_err(|error| Error::new(path, &error).into())
}

pub fn open(path: &Path) -> crate::Result<File> {
    if path.is_dir() {
        return Err(Error::new(
            path,
            &io::Error::from(if cfg!(windows) {
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
