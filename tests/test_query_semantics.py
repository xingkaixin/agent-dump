from unittest import mock

import agent_dump.query_semantics as query_semantics
from agent_dump.query_semantics import TextQuery, TextQueryMode, serialize_search_value


class TestTextQuery:
    def test_keyword_is_one_literal_phrase(self) -> None:
        query = TextQuery.parse("  Auth   Timeout  ", TextQueryMode.KEYWORD)

        assert query.literals == ("Auth Timeout",)
        assert query.matches(("auth timeout",))
        assert not query.matches(("auth failed before timeout",))

    def test_search_requires_every_distinct_literal_term(self) -> None:
        query = TextQuery.parse(" auth   timeout auth ", TextQueryMode.SEARCH_TERMS)

        assert query.literals == ("auth", "timeout")
        assert query.matches(("AUTH failed", "request timeout"))
        assert not query.matches(("auth only",))

    def test_operator_like_terms_are_plain_text(self) -> None:
        query = TextQuery.parse('AND NEAR * "quoted"', TextQueryMode.SEARCH_TERMS)

        assert query.matches(('literal AND, NEAR, *, and "quoted" values',))
        assert not query.matches(("ordinary words",))

    def test_cjk_literal_requires_adjacency(self) -> None:
        query = TextQuery.parse("认证", TextQueryMode.SEARCH_TERMS)

        assert query.matches(("修复认证模块",))
        assert not query.matches(("认知经过证明",))

    def test_snippet_comes_from_a_matching_field(self) -> None:
        query = TextQuery.parse("auth timeout", TextQueryMode.SEARCH_TERMS)

        assert query.build_snippet(("Auth incident", "request timeout")) == "**Auth** incident"

    def test_match_reports_full_field_evidence_for_ranking(self) -> None:
        query = TextQuery.parse("auth timeout", TextQueryMode.SEARCH_TERMS)

        split_match = query.find_match(("Auth incident", "request timeout"))
        title_match = query.find_match(("Auth timeout", "request timeout"))

        assert split_match is not None
        assert split_match.fully_matching_field_indexes == frozenset()
        assert split_match.snippet == "**Auth** incident"
        assert title_match is not None
        assert title_match.fully_matching_field_indexes == frozenset({0})

    def test_match_normalizes_and_scans_each_field_once(self) -> None:
        query = TextQuery.parse("auth timeout", TextQueryMode.SEARCH_TERMS)

        with (
            mock.patch.object(
                query_semantics,
                "normalize_search_text",
                wraps=query_semantics.normalize_search_text,
            ) as normalize,
            mock.patch.object(query_semantics, "_find_literal", wraps=query_semantics._find_literal) as find_literal,
        ):
            match = query.find_match(("Auth title", "request timeout"))

        assert match is not None
        assert normalize.call_count == 2
        assert find_literal.call_count == 4


def test_search_value_serialization_preserves_logical_unicode() -> None:
    assert serialize_search_value({"keyword": "认证"}) == '{"keyword": "认证"}'
