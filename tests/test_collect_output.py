"""Collect Markdown output tests."""

from datetime import date

import pytest

from agent_dump.collect_output import write_collect_markdown


class TestCollectOutput:
    def test_write_collect_markdown_uses_date_range_filename(self, tmp_path):
        path = write_collect_markdown(
            "# report",
            since_date=date(2026, 3, 1),
            until_date=date(2026, 3, 5),
            output_dir=tmp_path,
        )
        assert path == tmp_path / "agent-dump-collect-20260301-20260305.md"
        assert path.read_text(encoding="utf-8") == "# report"

    def test_write_collect_markdown_uses_explicit_output_path(self, tmp_path):
        output_path = tmp_path / "reports" / "report.md"
        path = write_collect_markdown(
            "# report",
            since_date=date(2026, 3, 1),
            until_date=date(2026, 3, 5),
            output_path=output_path,
        )
        assert path == output_path
        assert path.read_text(encoding="utf-8") == "# report"

    def test_write_collect_markdown_creates_parent_dirs_for_output_path(self, tmp_path):
        output_path = tmp_path / "nested" / "collect" / "report.md"
        path = write_collect_markdown(
            "# report",
            since_date=date(2026, 3, 1),
            until_date=date(2026, 3, 5),
            output_path=output_path,
        )
        assert path == output_path
        assert output_path.parent.is_dir()

    def test_write_collect_markdown_rejects_both_output_dir_and_output_path(self, tmp_path):
        with pytest.raises(ValueError, match="mutually exclusive"):
            write_collect_markdown(
                "# report",
                since_date=date(2026, 3, 1),
                until_date=date(2026, 3, 5),
                output_dir=tmp_path,
                output_path=tmp_path / "report.md",
            )
