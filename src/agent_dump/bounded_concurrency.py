"""Bounded submission for concurrent work."""

from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, wait
from typing import TypeVar

_Item = TypeVar("_Item")
_Result = TypeVar("_Result")


def iter_completed_futures(
    items: Iterable[_Item],
    *,
    max_pending: int,
    submit: Callable[[_Item], Future[_Result]],
) -> Iterator[tuple[int, _Item, Future[_Result]]]:
    """Yield completed futures while keeping at most ``max_pending`` tasks submitted."""
    if max_pending < 1:
        raise ValueError("max_pending must be at least 1")

    pending_items = iter(enumerate(items))
    future_to_item: dict[Future[_Result], tuple[int, _Item]] = {}

    for index, item in pending_items:
        future_to_item[submit(item)] = (index, item)
        if len(future_to_item) == max_pending:
            break

    while future_to_item:
        completed, _ = wait(tuple(future_to_item), return_when=FIRST_COMPLETED)
        for future in completed:
            index, item = future_to_item.pop(future)
            yield index, item, future
            try:
                next_index, next_item = next(pending_items)
            except StopIteration:
                pass
            else:
                future_to_item[submit(next_item)] = (next_index, next_item)
