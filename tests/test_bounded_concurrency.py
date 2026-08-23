"""Bounded concurrency scheduling tests."""

from concurrent.futures import Future

import pytest

from agent_dump.bounded_concurrency import iter_completed_futures


def test_completed_futures_preserve_item_identity_and_bound_pending_work(monkeypatch) -> None:
    submitted: list[str] = []
    observed_pending: list[int] = []

    def submit(item: str) -> Future[str]:
        submitted.append(item)
        future: Future[str] = Future()
        future.set_result(item.upper())
        return future

    def recording_wait(
        futures: tuple[Future[str], ...], *, return_when: object
    ) -> tuple[set[Future[str]], set[Future[str]]]:
        del return_when
        observed_pending.append(len(futures))
        return {futures[0]}, set(futures[1:])

    monkeypatch.setattr("agent_dump.bounded_concurrency.wait", recording_wait)

    completed = list(iter_completed_futures(["a", "b", "c", "d"], max_pending=2, submit=submit))

    assert submitted == ["a", "b", "c", "d"]
    assert max(observed_pending) == 2
    assert sorted((index, item, future.result()) for index, item, future in completed) == [
        (0, "a", "A"),
        (1, "b", "B"),
        (2, "c", "C"),
        (3, "d", "D"),
    ]


def test_completed_futures_reject_non_positive_bound() -> None:
    with pytest.raises(ValueError, match="max_pending"):
        list(iter_completed_futures([], max_pending=0, submit=lambda item: Future()))
