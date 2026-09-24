use crate::provider::{Discovery, SessionFailure};
use crate::session::Session;
use jiff::{SignedDuration, Timestamp};
use std::path::{Path, PathBuf};
use walkdir::WalkDir;

pub struct SourceRoots {
    pub base: PathBuf,
    pub owned: PathBuf,
    primary: PathBuf,
    fallback: &'static str,
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
    pub fn resolve(
        root: PathBuf,
        suffix: &str,
        fallback: &'static str,
        label: &'static str,
    ) -> Self {
        let primary = root.join(suffix);
        let (base, owned) = if primary.exists() {
            (primary.clone(), root)
        } else {
            let base = PathBuf::from(fallback);
            (base.clone(), base)
        };
        Self {
            base,
            owned,
            primary,
            fallback,
            label,
        }
    }

    pub fn search_roots(&self) -> Vec<(&'static str, PathBuf)> {
        vec![
            (self.label, self.primary.clone()),
            ("local development fallback", self.fallback.into()),
        ]
    }

    pub fn files(
        &self,
        depth: Option<usize>,
        accept: impl Fn(&Path) -> bool,
    ) -> crate::Result<Vec<PathBuf>> {
        if !self.base.exists() {
            return Ok(Vec::new());
        }
        let mut walker = WalkDir::new(&self.base);
        if let Some(depth) = depth {
            walker = walker.max_depth(depth);
        }
        let mut paths = Vec::new();
        for entry in walker {
            let entry = entry?;
            if !entry.file_type().is_dir() && accept(entry.path()) {
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
                error: error.to_string(),
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
    base: &Path,
    paths: &[PathBuf],
    id: &str,
    preferred: impl Fn(&Path) -> bool,
    mut parse: impl FnMut(&Path) -> crate::Result<Option<Session>>,
) -> crate::Result<Session> {
    if base.exists() {
        let root = base.canonicalize()?;
        for direct in [true, false] {
            for path in paths {
                if preferred(path) != direct {
                    continue;
                }
                let result = (|| {
                    if !path.canonicalize()?.starts_with(&root) {
                        return Ok(None);
                    }
                    parse(path)
                })();
                match result {
                    Ok(Some(session)) if session.id == id => return Ok(session),
                    Err(error) => warn(path, &error),
                    _ => {}
                }
            }
        }
    }
    Err(format!("Session not found: {id}").into())
}

fn warn(path: &Path, error: &dyn std::fmt::Display) {
    eprintln!(
        "Warning: could not read session {}: {}",
        crate::render::safe_line(&path.display().to_string()),
        crate::render::safe_line(&error.to_string())
    );
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
