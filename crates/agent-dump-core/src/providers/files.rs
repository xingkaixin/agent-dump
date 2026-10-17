use crate::providers::contract::{Discovery, Lookup, SessionFailure};
use crate::session::Session;
use crate::session::timestamp::Timestamp;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use walkdir::WalkDir;

pub struct SourceRoots {
    pub base: Option<PathBuf>,
    resolve: Box<dyn Fn() -> crate::Result<Located> + Send + Sync>,
    owned: PathBuf,
    fallback: PathBuf,
}

pub struct Located {
    pub owner: PathBuf,
    pub sessions: PathBuf,
    pub label: &'static str,
}

#[derive(Default)]
pub struct SourceFiles {
    pub paths: Vec<PathBuf>,
    pub failures: Vec<SessionFailure>,
}

pub fn environment_root(
    variable: &str,
    default: &str,
) -> crate::Result<PathBuf> {
    if variable != "HOME"
        && let Some(path) = environment_path(variable)?
    {
        return Ok(path);
    }
    Ok(home()?.join(default))
}

pub fn environment_value(variable: &str) -> Option<OsString> {
    let value = std::env::var_os(variable)?;
    let value = match value.to_str() {
        Some(text) => OsString::from(text.trim()),
        None => value,
    };
    (!value.is_empty()).then_some(value)
}

pub fn environment_path(variable: &str) -> crate::Result<Option<PathBuf>> {
    let Some(value) = environment_value(variable) else {
        return Ok(None);
    };
    Ok(Some(match value.to_str() {
        Some(text) => expand_home(text)?,
        None => PathBuf::from(value),
    }))
}

pub fn expand_home(text: &str) -> crate::Result<PathBuf> {
    if text == "~" {
        return home();
    }
    Ok(
        match text.strip_prefix("~/").or_else(|| text.strip_prefix("~\\")) {
            Some(rest) => home()?.join(rest),
            None => PathBuf::from(text),
        },
    )
}

pub fn home() -> crate::Result<PathBuf> {
    let home = if cfg!(windows) {
        std::env::var_os("USERPROFILE").or_else(|| {
            let mut drive = std::env::var_os("HOMEDRIVE")?;
            drive.push(std::env::var_os("HOMEPATH")?);
            Some(drive)
        })
    } else {
        std::env::var_os("HOME")
    }
    .ok_or("Could not determine home directory")?;
    Ok(PathBuf::from(home))
}

impl SourceRoots {
    #[cfg(test)]
    pub fn fixed(
        root: PathBuf,
        suffix: &'static str,
        fallback: impl Into<PathBuf>,
        label: &'static str,
    ) -> Self {
        Self::new(move || Ok(root.clone()), suffix, fallback, label)
    }

    pub fn new(
        root: impl Fn() -> crate::Result<PathBuf> + Send + Sync + 'static,
        suffix: &'static str,
        fallback: impl Into<PathBuf>,
        label: &'static str,
    ) -> Self {
        Self::located(
            move || {
                let owner = root()?;
                Ok(Located {
                    sessions: owner.join(suffix),
                    owner,
                    label,
                })
            },
            fallback,
        )
    }

    pub fn located(
        resolve: impl Fn() -> crate::Result<Located> + Send + Sync + 'static,
        fallback: impl Into<PathBuf>,
    ) -> Self {
        let fallback = fallback.into();
        Self {
            base: None,
            resolve: Box::new(resolve),
            owned: fallback.clone(),
            fallback,
        }
    }

    pub fn configured_root(&self) -> crate::Result<PathBuf> {
        Ok((self.resolve)()?.owner)
    }

    pub fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>> {
        let located = (self.resolve)()?;
        Ok(vec![
            (located.label, located.sessions),
            ("local development fallback", self.fallback.clone()),
        ])
    }

    pub fn owned(&self) -> &Path {
        &self.owned
    }

    pub fn select(&mut self) -> crate::Result<Option<&Path>> {
        if self.base.is_none() {
            let Located {
                owner: root,
                sessions: primary,
                ..
            } = (self.resolve)()?;
            self.base = [&primary, &self.fallback]
                .into_iter()
                .find(|path| path.exists())
                .cloned();
            if self.base.as_ref() == Some(&primary) {
                self.owned = root;
            }
        }
        Ok(self.base.is_some().then_some(self.owned.as_path()))
    }

    pub fn files(
        &mut self,
        depth: Option<usize>,
        accept: impl Fn(&Path, &Path) -> bool,
    ) -> crate::Result<SourceFiles> {
        self.select()?;
        let Some(base) = &self.base else {
            return Ok(SourceFiles::default());
        };
        if !base.exists() {
            return Ok(SourceFiles::default());
        }
        let mut walker = WalkDir::new(base);
        if let Some(depth) = depth {
            walker = walker.max_depth(depth);
        }
        let mut files = SourceFiles::default();
        for entry in walker {
            match entry {
                Ok(entry) => {
                    if !entry.file_type().is_dir() && accept(entry.path(), base)
                    {
                        files.paths.push(entry.into_path());
                    }
                }
                Err(error) if error.depth() > 0 => {
                    files.failures.push(SessionFailure {
                        source: crate::storage::source_io::path_text(
                            error.path().unwrap_or(base),
                        ),
                        error: error.into(),
                    });
                }
                Err(error) => return Err(error.into()),
            }
        }
        Ok(files)
    }
}

pub fn discover<S: Send>(
    files: SourceFiles,
    days: Option<i64>,
    prune_mtime: bool,
    scan: impl Fn(&Path) -> crate::Result<S> + Sync,
    mut parse: impl FnMut(
        &Path,
        S,
        Option<Timestamp>,
    ) -> crate::Result<Option<Session>>,
) -> crate::Result<Discovery> {
    let cutoff = days.map(Timestamp::days_ago).transpose()?;
    let SourceFiles { paths, failures } = files;
    let mut discovery = Discovery {
        available: !paths.is_empty(),
        failures,
        ..Discovery::default()
    };
    crate::parallel::ordered(
        &paths,
        |path| {
            let scanned = (|| {
                if prune_mtime
                    && let Some(cutoff) = cutoff
                    && Timestamp::try_from(path.metadata()?.modified()?)?
                        < cutoff
                {
                    return Ok(None);
                }
                scan(path).map(Some)
            })();
            (path, scanned)
        },
        |(path, scanned)| {
            match scanned.and_then(|scanned| {
                scanned.map_or(Ok(None), |scanned| parse(path, scanned, cutoff))
            }) {
                Ok(Some(session))
                    if cutoff
                        .is_none_or(|cutoff| session.created_at >= cutoff) =>
                {
                    discovery.sessions.push(session);
                }
                Err(error) => discovery.failures.push(SessionFailure {
                    source: crate::storage::source_io::path_text(path),
                    error,
                }),
                _ => {}
            }
            Ok(())
        },
    )?;
    discovery
        .sessions
        .sort_by(|a, b| b.created_at.cmp(&a.created_at));
    Ok(discovery)
}

pub fn find(
    base: Option<&Path>,
    files: SourceFiles,
    id: &str,
    preferred: impl Fn(&Path) -> bool,
    mut parse: impl FnMut(&Path) -> crate::Result<Option<Session>>,
) -> crate::Result<Lookup> {
    let SourceFiles { paths, failures } = files;
    let mut lookup = Lookup {
        session: None,
        failures,
    };
    if let Some(base) = base.filter(|base| base.exists()) {
        let root = base.canonicalize()?;
        for direct in [true, false] {
            for path in &paths {
                if direct && !preferred(path) {
                    continue;
                }
                let result = (|| {
                    if !path.canonicalize()?.starts_with(&root) {
                        return Ok(None);
                    }
                    parse(path)
                })();
                match result {
                    Ok(Some(session)) if session.id == id => {
                        if lookup.session.as_ref().is_none_or(|found| {
                            session.created_at > found.created_at
                        }) {
                            lookup.session = Some(session);
                        }
                        if direct {
                            return Ok(lookup);
                        }
                    }
                    Err(error) => lookup.failures.push(SessionFailure {
                        source: crate::storage::source_io::path_text(path),
                        error,
                    }),
                    _ => {}
                }
            }
        }
    }
    Ok(lookup)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn failed_candidates_remain_visible_without_a_diagnostic_sink() {
        let directory = tempfile::tempdir().unwrap();
        let readable = directory.path().join("readable.jsonl");
        std::fs::write(&readable, b"").unwrap();
        let missing = directory.path().join("removed.jsonl");
        let scan = |_: &Path| Ok(());
        let parse = |path: &Path, (): (), _: Option<Timestamp>| {
            Ok(Some(Session::new(
                "kept".into(),
                "Kept".into(),
                path.to_owned(),
                Timestamp::now(),
                Timestamp::now(),
            )))
        };
        let files = |paths| SourceFiles {
            paths,
            failures: Vec::new(),
        };
        let discovery = discover(
            files(vec![missing.clone(), readable]),
            Some(7),
            true,
            scan,
            parse,
        )
        .unwrap();
        assert!(discovery.available);
        assert_eq!(discovery.sessions.len(), 1);
        assert_eq!(discovery.sessions[0].id, "kept");
        assert_eq!(discovery.failures.len(), 1);
        assert_eq!(discovery.failures[0].source, missing.display().to_string());

        let failed =
            discover(files(vec![missing]), Some(7), true, scan, parse).unwrap();
        assert!(failed.available);
        assert!(failed.sessions.is_empty());
        assert_eq!(failed.failures.len(), 1);

        let absent =
            discover(SourceFiles::default(), Some(7), true, scan, parse)
                .unwrap();
        assert!(!absent.available);
        assert!(absent.failures.is_empty());
    }
}
