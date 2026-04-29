from intelligent_search_agent.ingestion.embedding_text import compose_asset_embedding_text


def test_compose_asset_embedding_text_keeps_searchable_fields():
    text = compose_asset_embedding_text(
        {
            "description": "French summer banner",
            "asset_kind": "banner",
            "language": "fr",
            "period": "summer",
            "project_name": "Wine Campaign",
            "year": 2024,
            "file_name": "wine_fr.png",
            "metadata": {
                "vlm_entry": {
                    "subjects": ["market square"],
                    "locations": ["Brussels"],
                    "people": ["merchant"],
                    "visual_style": "engraving",
                    "search_keywords": ["street scene"],
                },
                "tags": ["Belgian history"],
            },
        }
    )

    assert "French summer banner" in text
    assert "banner" in text
    assert "Wine Campaign" in text
    assert "wine_fr.png" in text
    assert "Brussels" in text
    assert "street scene" in text
    assert "Belgian history" in text
