use crate::provider::{Discovery, Lookup, SessionFailure};
use crate::session::Session;
use crate::timestamp::Timestamp;
use jiff::SignedDuration;
use std::path::{Path, PathBuf};
use walkdir::WalkDir;

pub struct SourceRoots {
    pub base: Option<PathBuf>,
    root: Box<dyn Fn() -> crate::Result<PathBuf>>,
    suffix: &'static str,
    owned: PathBuf,
    fallback: PathBuf,
    label: &'static str,
}

pub fn environment_root(variable: &str, default: &str) -> crate::Result<PathBuf> {
    if let Some(value) = std::env::var_os(variable).filter(|value| !value.is_empty()) {
        return Ok(PathBuf::from(value));
    }
    let home = std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .ok_or("HOME or USERPROFILE is required")?;
    Ok(PathBuf::from(home).join(default))
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
        root: impl Fn() -> crate::Result<PathBuf> + 'static,
        suffix: &'static str,
        fallback: impl Into<PathBuf>,
        label: &'static str,
    ) -> Self {
        let fallback = fallback.into();
        Self {
            base: None,
            root: Box::new(root),
            suffix,
            owned: fallback.clone(),
            fallback,
            label,
        }
    }

    pub fn configured_root(&self) -> crate::Result<PathBuf> {
        (self.root)()
    }

    pub fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>> {
        Ok(vec![
            (self.label, self.configured_root()?.join(self.suffix)),
            ("local development fallback", self.fallback.clone()),
        ])
    }

    pub fn owned(&self) -> &Path {
        &self.owned
    }

    pub fn files(
        &mut self,
        depth: Option<usize>,
        accept: impl Fn(&Path, &Path) -> bool,
    ) -> crate::Result<Vec<PathBuf>> {
        if self.base.is_none() {
            let root = self.configured_root()?;
            let primary = root.join(self.suffix);
            self.base = [&primary, &self.fallback]
                .into_iter()
                .find(|path| path.exists())
                .cloned();
            if self.base.as_ref() == Some(&primary) {
                self.owned = root;
            }
        }
        let Some(base) = &self.base else {
            return Ok(Vec::new());
        };
        if !base.exists() {
            return Ok(Vec::new());
        }
        let mut walker = WalkDir::new(base);
        if let Some(depth) = depth {
            walker = walker.max_depth(depth);
        }
        let mut paths = Vec::new();
        for entry in walker {
            let entry = entry?;
            if !entry.file_type().is_dir() && accept(entry.path(), base) {
                paths.push(entry.into_path());
            }
        }
        Ok(paths)
    }
}

pub fn discover(
    paths: &[PathBuf],
    days: i64,
    prune_mtime: bool,
    mut parse: impl FnMut(&Path, Timestamp) -> crate::Result<Option<Session>>,
) -> crate::Result<Discovery> {
    let seconds = days.checked_mul(86400).ok_or("days is out of range")?;
    let cutoff = Timestamp::now().checked_sub(SignedDuration::from_secs(seconds))?;
    let mut discovery = Discovery {
        available: !paths.is_empty(),
        ..Discovery::default()
    };
    for path in paths {
        let result = (|| {
            if prune_mtime && Timestamp::try_from(path.metadata()?.modified()?)? < cutoff {
                return Ok(None);
            }
            parse(path, cutoff)
        })();
        match result {
            Ok(Some(session)) if session.created_at >= cutoff => discovery.sessions.push(session),
            Err(error) => discovery.failures.push(SessionFailure {
                source: path.display().to_string(),
                error,
            }),
            _ => {}
        }
    }
    discovery
        .sessions
        .sort_by(|a, b| b.created_at.cmp(&a.created_at));
    Ok(discovery)
}

pub fn find(
    base: Option<&Path>,
    paths: &[PathBuf],
    id: &str,
    preferred: impl Fn(&Path) -> bool,
    mut parse: impl FnMut(&Path) -> crate::Result<Option<Session>>,
) -> crate::Result<Lookup> {
    let mut lookup = Lookup::default();
    if let Some(base) = base.filter(|base| base.exists()) {
        let root = base.canonicalize()?;
        for direct in [true, false] {
            for path in paths {
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
                        if lookup
                            .session
                            .as_ref()
                            .is_none_or(|found| session.created_at > found.created_at)
                        {
                            lookup.session = Some(session);
                        }
                        if direct {
                            return Ok(lookup);
                        }
                    }
                    Err(error) => lookup.failures.push(SessionFailure {
                        source: path.display().to_string(),
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
        let parse = |path: &Path, _: Timestamp| {
            Ok(Some(Session::new(
                "kept".into(),
                "Kept".into(),
                path.to_owned(),
                Timestamp::now(),
                Timestamp::now(),
            )))
        };
        let discovery = discover(&[missing.clone(), readable], 7, true, parse).unwrap();
        assert!(discovery.available);
        assert_eq!(discovery.sessions.len(), 1);
        assert_eq!(discovery.sessions[0].id, "kept");
        assert_eq!(discovery.failures.len(), 1);
        assert_eq!(discovery.failures[0].source, missing.display().to_string());

        let failed = discover(&[missing], 7, true, parse).unwrap();
        assert!(failed.available);
        assert!(failed.sessions.is_empty());
        assert_eq!(failed.failures.len(), 1);

        let absent = discover(&[], 7, true, parse).unwrap();
        assert!(!absent.available);
        assert!(absent.failures.is_empty());
    }
}
