"""Output format contract tests."""

from unittest import mock

from locale_helpers import Keys, expect
import pytest

from agent_dump.agents.cursor import CursorAgent
from agent_dump.diagnostics import DiagnosticError
from agent_dump.output_formats import parse_format_spec, validate_uri_agent_formats


class TestValidateUriAgentFormats:
    def test_provider_without_restrictions_accepts_all_formats(self):
        agent = mock.MagicMock()
        agent.unsupported_uri_formats = frozenset()

        validate_uri_agent_formats(agent, ["json", "markdown", "raw", "print"])

    def test_provider_restrictions_raise_capability_error(self):
        agent = CursorAgent()

        with pytest.raises(DiagnosticError) as excinfo:
            validate_uri_agent_formats(agent, ["json", "raw"])

        assert excinfo.value.capability_gap is not None
        assert (
            expect(Keys.DIAG_URI_CAPABILITY_DETAIL, agent="Cursor", supported="json, print", requested="raw")
            == excinfo.value.capability_gap
        )


class TestFormatSpec:
    def test_parse_format_spec_supports_alias_and_dedup(self):
        result = parse_format_spec("json, md ,raw,json")
        assert result == ["json", "markdown", "raw"]

    def test_parse_format_spec_rejects_unknown_format(self):
        with pytest.raises(ValueError):
            parse_format_spec("json,foo")

    def test_parse_format_spec_rejects_empty_part(self):
        with pytest.raises(ValueError):
            parse_format_spec("json,,raw")
