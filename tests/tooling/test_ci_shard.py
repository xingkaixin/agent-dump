"""Sharding must preserve coverage when tests are added or removed."""

from ci_shard import partition
import pytest


def test_partition_includes_new_files_once_and_ignores_removed_files() -> None:
    files = ["new.py", "a.py", "b.py", "c.py", "d.py"]
    timings = {"a.py": 100.0, "b.py": 70.0, "c.py": 20.0, "d.py": 10.0, "removed.py": 900.0}
    shards = partition(files, timings, 4, 60.0)

    assert sorted(name for shard in shards for name in shard) == sorted(files)
    assert all(shards)
    assert shards == partition(list(reversed(files)), timings, 4, 60.0)


def test_partition_balances_time_including_shard_zero_checks() -> None:
    timings = {"a.py": 60.0, "b.py": 50.0, "c.py": 40.0, "d.py": 30.0, "e.py": 20.0}
    shards = partition(list(timings), timings, 3, 40.0)
    loads = [sum(timings[name] for name in shard) + (40 if index == 0 else 0) for index, shard in enumerate(shards)]

    assert max(loads) == 80


def test_partition_without_history_still_covers_every_file() -> None:
    shards = partition(["a.py", "b.py", "c.py"], {}, 2, 0.0)

    assert sorted(name for shard in shards for name in shard) == ["a.py", "b.py", "c.py"]


@pytest.mark.parametrize("count", [0, -1, 3])
def test_partition_rejects_empty_shards(count: int) -> None:
    with pytest.raises(ValueError, match="Shard count"):
        partition(["a.py", "b.py"], {}, count, 0.0)
