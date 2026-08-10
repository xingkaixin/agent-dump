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


def test_search_value_serialization_preserves_logical_unicode() -> None:
    assert serialize_search_value({"keyword": "认证"}) == '{"keyword": "认证"}'
