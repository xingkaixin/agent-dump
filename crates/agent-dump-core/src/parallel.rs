use std::collections::BTreeMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc;

/// Runs `work` on a bounded worker pool and hands results to `consume` in
/// input order. A failed `consume` stops the remaining work.
pub fn ordered<T: Sync, R: Send>(
    items: &[T],
    work: impl Fn(&T) -> R + Sync,
    mut consume: impl FnMut(R) -> crate::Result<()>,
) -> crate::Result<()> {
    let workers = std::thread::available_parallelism()
        .map_or(4, std::num::NonZero::get)
        .min(items.len());
    let next = AtomicUsize::new(0);
    std::thread::scope(|scope| {
        let (sender, receiver) = mpsc::channel();
        for _ in 0..workers {
            let sender = sender.clone();
            let (next, work) = (&next, &work);
            scope.spawn(move || {
                loop {
                    let index = next.fetch_add(1, Ordering::Relaxed);
                    let Some(item) = items.get(index) else {
                        break;
                    };
                    if sender.send((index, work(item))).is_err() {
                        break;
                    }
                }
            });
        }
        drop(sender);
        let mut ready = BTreeMap::new();
        let mut expected = 0;
        for (index, result) in receiver {
            ready.insert(index, result);
            while let Some(result) = ready.remove(&expected) {
                expected += 1;
                consume(result)?;
            }
        }
        Ok(())
    })
}

#[cfg(test)]
mod tests {
    #[test]
    fn results_keep_input_order_and_failures_stop_consumption() {
        let items: Vec<usize> = (0..200).collect();
        let mut seen = Vec::new();
        super::ordered(
            &items,
            |&item| {
                if item % 7 == 0 {
                    std::thread::sleep(std::time::Duration::from_millis(1));
                }
                item * 2
            },
            |value| {
                seen.push(value);
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(seen, items.iter().map(|item| item * 2).collect::<Vec<_>>());

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
    }
}
