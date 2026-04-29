from intelligent_search_agent.ingestion.corpus_ingest import (
    ImageVlmEntry,
    chunk_page_text,
    stable_external_id,
)


def test_chunk_page_text_respects_overlap() -> None:
    text = " ".join(f"word{i}" for i in range(200))

    chunks = chunk_page_text(text, chunk_chars=120, overlap_chars=20)

    assert len(chunks) > 1
    assert all(len(chunk) <= 120 for chunk in chunks)
    assert chunks[0] != chunks[1]


def test_image_vlm_entry_normalizes_unexpected_kind() -> None:
    entry = ImageVlmEntry(
        description="A historical Belgian street scene with a public gathering.",
        asset_kind="oil painting",
        subjects="Belgian Revolution",
    )

    assert entry.asset_kind == "other"
    assert entry.subjects == ["Belgian Revolution"]


def test_stable_external_id_uses_source_fields() -> None:
    item = {"source_url": "https://example.test/source", "local_path": "local/file.jpg"}

    assert stable_external_id("commons", item) == stable_external_id("commons", dict(item))
    assert stable_external_id("commons", item).startswith("commons:")
