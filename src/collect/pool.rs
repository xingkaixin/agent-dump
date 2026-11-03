use std::collections::VecDeque;
use std::panic::{AssertUnwindSafe, catch_unwind, resume_unwind};
use std::sync::mpsc;

/// Runs queued jobs with at most `limit` in flight. `handle` sees each result
/// on the calling thread and may add or drop queued jobs; an error stops new
/// jobs and returns once the running ones finish.
pub fn run<J: Send, R: Send>(
    limit: usize,
    mut queue: VecDeque<J>,
    work: impl Fn(J) -> R + Sync,
    mut handle: impl FnMut(R, &mut VecDeque<J>) -> crate::Result<()>,
) -> crate::Result<()> {
    std::thread::scope(|scope| {
        let (sender, receiver) = mpsc::channel();
        let mut running = 0;
        loop {
            while running < limit.max(1)
                && let Some(job) = queue.pop_front()
            {
                let (sender, work) = (sender.clone(), &work);
                scope.spawn(move || {
                    let result = catch_unwind(AssertUnwindSafe(|| work(job)));
                    let _ = sender.send(result);
                });
                running += 1;
            }
            if running == 0 {
                return Ok(());
            }
            running -= 1;
            match receiver.recv().expect("the pool keeps a sender") {
                Ok(result) => handle(result, &mut queue)?,
                Err(panic) => resume_unwind(panic),
            }
        }
    })
}
