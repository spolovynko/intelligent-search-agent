from intelligent_search_agent.core.config import get_settings


def test_default_settings_load():
    settings = get_settings()

    assert settings.db_name == "intelligent_search_agent"
    assert settings.rag_top_k > 0
