use crate::provider::{DiagnosticSink, Provider};
use crate::session::{Session, SessionData};
use std::collections::VecDeque;
use std::fmt;
use std::ops::{Deref, DerefMut};
use std::path::PathBuf;
use std::sync::{Arc, Condvar, Mutex, OnceLock};
use std::time::SystemTime;

#[derive(Clone, Debug, PartialEq, Eq)]
struct PathSignal {
    path: PathBuf,
    modified: Option<SystemTime>,
    changed: Option<i128>,
    size: Option<u64>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SessionSignal {
    updated: i64,
    title: String,
    sources: Vec<PathSignal>,
}

impl SessionSignal {
    pub fn new(provider: &(impl Provider + ?Sized), session: &Session) -> Self {
        let mut sources = Vec::new();
        for path in provider.change_sources(session) {
            if sources
                .iter()
                .any(|signal: &PathSignal| signal.path == path)
            {
                continue;
            }
            let metadata = path.metadata().ok();
            sources.push(PathSignal {
                path,
                modified: metadata
                    .as_ref()
                    .and_then(|metadata| metadata.modified().ok()),
                changed: metadata.as_ref().and_then(changed_time),
                size: metadata.map(|metadata| metadata.len()),
            });
        }
        Self {
            updated: session.updated_at.as_microsecond(),
            title: session.title.clone(),
            sources,
        }
    }
}

#[cfg(unix)]
fn changed_time(metadata: &std::fs::Metadata) -> Option<i128> {
    use std::os::unix::fs::MetadataExt;
    Some(i128::from(metadata.ctime()) * 1_000_000_000 + i128::from(metadata.ctime_nsec()))
}

#[cfg(not(unix))]
fn changed_time(metadata: &std::fs::Metadata) -> Option<i128> {
    let created = metadata.created().ok()?;
    Some(match created.duration_since(SystemTime::UNIX_EPOCH) {
        Ok(duration) => duration.as_nanos() as i128,
        Err(error) => -(error.duration().as_nanos() as i128),
    })
}

#[derive(Clone, Debug)]
pub struct SharedReadError(Arc<dyn std::error::Error + Send + Sync>);

impl fmt::Display for SharedReadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl std::error::Error for SharedReadError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(self.0.as_ref())
    }
}

type Outcome = std::result::Result<Arc<SessionData>, SharedReadError>;

struct Load {
    identity: (String, String),
    signal: SessionSignal,
    outcome: OnceLock<Outcome>,
}

struct Entry {
    load: Arc<Load>,
    leases: usize,
    retain: bool,
}

pub struct SessionDataCache {
    entries: Mutex<VecDeque<Entry>>,
    ready: Condvar,
    completed_limit: usize,
}

impl Default for SessionDataCache {
    fn default() -> Self {
        Self::new(32)
    }
}

impl SessionDataCache {
    pub fn new(completed_limit: usize) -> Self {
        Self {
            entries: Mutex::new(VecDeque::new()),
            ready: Condvar::new(),
            completed_limit,
        }
    }

    pub fn get(
        &self,
        name: &str,
        provider: &(impl Provider + ?Sized),
        session: &Session,
        zh: bool,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Arc<SessionData>> {
        let lease = self.lease(name, provider, session, zh, diagnostics)?;
        if let Some(entry) = self
            .entries
            .lock()
            .unwrap()
            .iter_mut()
            .find(|entry| Arc::ptr_eq(&entry.load, &lease.load))
        {
            entry.retain = true;
        }
        Ok(lease.data.clone())
    }

    pub fn lease(
        &self,
        name: &str,
        provider: &(impl Provider + ?Sized),
        session: &Session,
        zh: bool,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<SessionLease<'_>> {
        let identity = (name.to_owned(), session.id.clone());
        let (load, should_load) = loop {
            let signal = SessionSignal::new(provider, session);
            let mut entries = self.entries.lock().unwrap();
            let position = entries
                .iter()
                .position(|entry| entry.load.identity == identity);
            if let Some(position) = position {
                let load = entries[position].load.clone();
                if load.signal != signal && load.outcome.get().is_none() {
                    drop(
                        self.ready
                            .wait_while(entries, |_| load.outcome.get().is_none())
                            .unwrap(),
                    );
                    continue;
                }
                let mut entry = entries.remove(position).unwrap();
                if load.signal == signal {
                    entry.leases += 1;
                    entries.push_back(entry);
                    break (load, false);
                }
            }
            let load = Arc::new(Load {
                identity: identity.clone(),
                signal,
                outcome: OnceLock::new(),
            });
            entries.push_back(Entry {
                load: load.clone(),
                leases: 1,
                retain: false,
            });
            break (load, true);
        };
        if should_load {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                provider.read(session, zh, diagnostics)
            }));
            let (outcome, panic) = match result {
                Ok(result) => (
                    result
                        .map(Arc::new)
                        .map_err(|error| SharedReadError(error.into())),
                    None,
                ),
                Err(panic) => (
                    Err(SharedReadError(
                        crate::Error::from("session reader panicked").into(),
                    )),
                    Some(panic),
                ),
            };
            let mut entries = self.entries.lock().unwrap();
            let failed = outcome.is_err();
            assert!(load.outcome.set(outcome).is_ok());
            if let Some(position) = entries
                .iter()
                .position(|entry| Arc::ptr_eq(&entry.load, &load))
            {
                let entry = entries.remove(position).unwrap();
                if !failed {
                    entries.push_back(entry);
                }
            }
            self.evict(&mut entries);
            self.ready.notify_all();
            drop(entries);
            if let Some(panic) = panic {
                std::panic::resume_unwind(panic);
            }
        } else {
            let entries = self.entries.lock().unwrap();
            drop(
                self.ready
                    .wait_while(entries, |_| load.outcome.get().is_none())
                    .unwrap(),
            );
        }
        match load.outcome.get().unwrap() {
            Ok(data) => Ok(SessionLease {
                cache: self,
                data: data.clone(),
                load,
            }),
            Err(error) => Err(Box::new(error.clone())),
        }
    }

    fn evict(&self, entries: &mut VecDeque<Entry>) {
        let mut completed = entries
            .iter()
            .filter(|entry| entry.load.outcome.get().is_some() && entry.leases == 0)
            .count();
        while completed > self.completed_limit {
            let position = entries
                .iter()
                .position(|entry| entry.load.outcome.get().is_some() && entry.leases == 0)
                .unwrap();
            entries.remove(position);
            completed -= 1;
        }
    }
}

pub struct SessionLease<'a> {
    cache: &'a SessionDataCache,
    load: Arc<Load>,
    data: Arc<SessionData>,
}

impl Deref for SessionLease<'_> {
    type Target = SessionData;

    fn deref(&self) -> &SessionData {
        &self.data
    }
}

impl DerefMut for SessionLease<'_> {
    fn deref_mut(&mut self) -> &mut SessionData {
        Arc::make_mut(&mut self.data)
    }
}

impl Drop for SessionLease<'_> {
    fn drop(&mut self) {
        let mut entries = self.cache.entries.lock().unwrap();
        if let Some(position) = entries
            .iter()
            .position(|entry| Arc::ptr_eq(&entry.load, &self.load))
        {
            let entry = &mut entries[position];
            entry.leases -= 1;
            if entry.leases == 0 && !entry.retain {
                entries.remove(position);
            }
            self.cache.evict(&mut entries);
        }
    }
}

#[cfg(test)]
mod tests;
