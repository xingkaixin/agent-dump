"""Private output writing for collect mode."""

from datetime import date
from pathlib import Path

from agent_dump.private_files import write_private_text


def write_collect_markdown(
    markdown: str,
    *,
    since_date: date,
    until_date: date,
    output_dir: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """Write collect markdown to the requested path with private permissions."""
    if output_path is not None and output_dir is not None:
        raise ValueError("output_path and output_dir are mutually exclusive")

    if output_path is not None:
        path = output_path
    else:
        base = output_dir if output_dir is not None else Path.cwd()
        path = base / f"agent-dump-collect-{since_date.strftime('%Y%m%d')}-{until_date.strftime('%Y%m%d')}.md"

    return write_private_text(path, markdown)
