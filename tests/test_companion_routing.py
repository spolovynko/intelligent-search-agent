from intelligent_search_agent.agent.assistant.companion import (
    AssistantIntent,
    AssistantRoute,
    RerankItem,
    RerankResult,
    apply_rerank_order,
    apply_user_intent_overrides,
    asset_kind_filter,
    contextual_question,
    choose_sources,
    heuristic_route,
    rerank_asset_rows,
    serialize_document,
)


def test_choose_sources_routes_explicit_image_requests_to_assets() -> None:
    assert choose_sources("Show me images of the Belgian Revolution") == (True, False)
    assert choose_sources("Find maps or visuals related to Antwerp history") == (True, False)


def test_choose_sources_routes_history_questions_to_chat_documents() -> None:
    assert choose_sources("What happened during the Belgian Revolution?") == (False, True)
    assert choose_sources("Can you show what happened during the Belgian Revolution?") == (
        False,
        True,
    )


def test_choose_sources_can_request_assets_and_documents() -> None:
    assert choose_sources("Find images and sources about Belgian patriotism in 1830") == (
        True,
        True,
    )


def test_heuristic_route_exposes_display_modes() -> None:
    image_route = heuristic_route("Show me images of the Belgian Revolution")
    document_route = heuristic_route("What happened during the Belgian Revolution?")
    mixed_route = heuristic_route("Explain the Belgian Revolution and show related images")

    assert image_route.intent == AssistantIntent.IMAGE_SEARCH
    assert image_route.display_mode == "asset_table"
    assert document_route.intent == AssistantIntent.DOCUMENT_ANSWER
    assert document_route.display_mode == "chat"
    assert mixed_route.intent == AssistantIntent.MIXED_SEARCH
    assert mixed_route.display_mode == "mixed"


def test_serialize_document_includes_clickable_page_citation() -> None:
    item = serialize_document(
        {
            "id": 42,
            "document_id": 7,
            "document_title": "Belgian Revolution Notes",
            "content": "A relevant excerpt",
            "page_number": 3,
            "doc_type": "pdf",
            "language": "en",
            "similarity": 0.81,
            "source_uri": "https://example.test/source.pdf",
            "metadata": {},
        },
        1,
    )

    assert item["ref"] == "D1"
    assert item["citation"] == "Belgian Revolution Notes (p. 3)"
    assert item["open_url"] == "/v1/documents/7/file#page=3"


def test_asset_kind_filter_ignores_generic_other() -> None:
    route = AssistantRoute(intent=AssistantIntent.IMAGE_SEARCH, asset_kind="other")

    assert asset_kind_filter("Show me images of the Belgian Revolution", route) is None


def test_asset_kind_filter_keeps_explicit_kind() -> None:
    route = AssistantRoute(intent=AssistantIntent.IMAGE_SEARCH, asset_kind="map")

    assert asset_kind_filter("Find maps of Antwerp", route) == "map"


def test_user_intent_override_forces_mixed_when_images_and_answer_are_requested() -> None:
    route = AssistantRoute(
        intent=AssistantIntent.DOCUMENT_ANSWER, search_query="Belgian Revolution"
    )

    normalized = apply_user_intent_overrides(
        route,
        "Explain the Belgian Revolution and show related images",
    )

    assert normalized.intent == AssistantIntent.MIXED_SEARCH
    assert normalized.needs_assets is True
    assert normalized.needs_documents is True
    assert normalized.display_mode == "mixed"


def test_contextual_question_resolves_short_followup() -> None:
    history = [
        {"role": "user", "content": "Show me images of the Belgian Revolution"},
        {"role": "assistant", "content": "I found several image matches."},
    ]

    assert contextual_question("Only paintings", history) == (
        "Show me images of the Belgian Revolution. Follow-up constraint: Only paintings"
    )


def test_asset_reranker_promotes_exact_subject_matches() -> None:
    route = AssistantRoute(intent=AssistantIntent.IMAGE_SEARCH)
    rows = [
        {
            "id": 1,
            "similarity": 0.70,
            "file_name": "ghent_model.jpg",
            "description": "A city model of Ghent.",
            "asset_kind": "object",
            "metadata": {"tags": ["Ghent"]},
        },
        {
            "id": 2,
            "similarity": 0.62,
            "file_name": "wappers_revolution.jpg",
            "description": "A painting of the Belgian Revolution.",
            "asset_kind": "painting",
            "metadata": {"tags": ["Belgian Revolution", "1830"]},
        },
    ]

    ranked = rerank_asset_rows(rows, "Show me images of the Belgian Revolution", route, 2)

    assert ranked[0]["id"] == 2
    assert ranked[0]["rerank_score"] > ranked[0]["retrieval_score"]


def test_apply_rerank_order_keeps_unmentioned_items() -> None:
    items = [{"ref": "A1"}, {"ref": "A2"}, {"ref": "A3"}]
    rerank = RerankResult(items=[RerankItem(ref="A2", score=0.9, reason="best")])

    ordered = apply_rerank_order(items, rerank)

    assert [item["ref"] for item in ordered] == ["A2", "A1", "A3"]
    assert ordered[0]["llm_rerank_reason"] == "best"
