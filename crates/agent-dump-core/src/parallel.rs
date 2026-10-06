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

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[test]
    fn results_keep_input_order_within_a_bounded_window() {
        let items: Vec<usize> = (0..1000).collect();
        let started = AtomicUsize::new(0);
        let ahead = std::thread::available_parallelism()
            .map_or(4, std::num::NonZero::get)
            * 4;
        let mut seen = Vec::new();
        super::ordered(
            &items,
            |&item| {
                started.fetch_max(item, Ordering::Relaxed);
                item * 2
            },
            |value| {
                if value == 0 {
                    std::thread::sleep(std::time::Duration::from_millis(50));
                    assert!(started.load(Ordering::Relaxed) < ahead);
                }
                seen.push(value);
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(seen, items.iter().map(|item| item * 2).collect::<Vec<_>>());
    }

    #[test]
    fn failures_stop_consumption_and_waiting_workers() {
        let items: Vec<usize> = (0..1000).collect();
        let mut consumed = 0;
        let result = super::ordered(
            &items,
            |&item| item,
            |item| {
                consumed += 1;
                if item == 3 {
                    Err("stop".into())
                } else {
                    Ok(())
                }
            },
        );
        assert_eq!(result.unwrap_err().to_string(), "stop");
        assert_eq!(consumed, 4);
        let panicked = std::panic::catch_unwind(|| {
            super::ordered(&items, |&item| assert_ne!(item, 5), |()| Ok(()))
        });
        assert!(panicked.is_err());
    }
}
