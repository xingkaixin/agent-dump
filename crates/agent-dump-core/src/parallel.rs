use std::collections::BTreeMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Condvar, Mutex, mpsc};

struct Window {
    consumed: Mutex<Option<usize>>,
    advanced: Condvar,
}

impl Window {
    fn advance(&self, count: usize) {
        if let Some(consumed) = self.consumed.lock().unwrap().as_mut() {
            *consumed = count;
        }
        self.advanced.notify_all();
    }

    fn stop(&self) {
        *self.consumed.lock().unwrap() = None;
        self.advanced.notify_all();
    }
}

struct Stop<'a>(&'a Window);

impl Drop for Stop<'_> {
    fn drop(&mut self) {
        self.0.stop();
    }
}

/// Runs `work` on a bounded worker pool and hands results to `consume` in
/// input order. Workers stay within a fixed window ahead of `consume`, and a
/// failed `consume` stops the remaining work.
pub fn ordered<'a, T: Sync, R: Send>(
    items: &'a [T],
    work: impl Fn(&'a T) -> R + Sync,
    mut consume: impl FnMut(R) -> crate::Result<()>,
) -> crate::Result<()> {
    let workers = std::thread::available_parallelism()
        .map_or(4, std::num::NonZero::get)
        .min(items.len());
    let ahead = workers * 4;
    let next = AtomicUsize::new(0);
    let window = Window {
        consumed: Mutex::new(Some(0)),
        advanced: Condvar::new(),
    };
    std::thread::scope(|scope| {
        let (sender, receiver) = mpsc::channel();
        for _ in 0..workers {
            let sender = sender.clone();
            let (next, work, window) = (&next, &work, &window);
            scope.spawn(move || {
                loop {
                    let index = next.fetch_add(1, Ordering::Relaxed);
                    let Some(item) = items.get(index) else {
                        break;
                    };
                    let consumed = window
                        .advanced
                        .wait_while(window.consumed.lock().unwrap(), |done| {
                            done.is_some_and(|done| index >= done + ahead)
                        })
                        .unwrap();
                    if consumed.is_none() {
                        break;
                    }
                    drop(consumed);
                    let stop = Stop(window);
                    let result = work(item);
                    std::mem::forget(stop);
                    if sender.send((index, result)).is_err() {
                        break;
                    }
                }
            });
        }
        drop(sender);
        let _stop = Stop(&window);
        let mut ready = BTreeMap::new();
        let mut expected = 0;
        for (index, result) in receiver {
            ready.insert(index, result);
            while let Some(result) = ready.remove(&expected) {
                expected += 1;
                consume(result)?;
                window.advance(expected);
            }
        }
        Ok(())
    })
}
