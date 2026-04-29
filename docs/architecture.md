# Architecture

This project is the assistant/search core extracted from the older ALDI RAG
project. The guideline-analysis branch is intentionally excluded.

## Runtime Responsibilities

The API should do four things well:

1. Accept natural-language questions.
2. Let the assistant choose retrieval tools.
3. Search indexed assets, documents, and meeting topics.
4. Return grounded answers with links to real source material.

The runtime should not scan large file systems or perform batch enrichment.
Those belong in offline ingestion jobs or background workers.

## Runtime Components

```text
FastAPI
  |
  |-- /v1/chat/companion/stream
  |-- /v1/chat/stream
  |-- /v1/search
  |-- /v1/assets/*
  |-- /v1/documents/*
  |-- /v1/meetings/*
  |
Companion stream
  |
  |-- Pydantic AI structured route
  |     |-- image_search
  |     |-- document_answer
  |     |-- mixed_search
  |     |-- general_chat
  |
  |-- retrieval planner
  |     |-- image table mode
  |     |-- document citations
  |     |-- mixed image + PDF evidence
  |
Legacy PydanticAI assistant
  |
  |-- search_assets
  |-- search_documents
  |-- search_meetings
  |
Retrieval services
  |
  |-- assets: hybrid vector + keyword + metadata filters
  |-- documents: hybrid vector + keyword over chunks
  |-- meetings: semantic search plus date/category/person filters
  |
PostgreSQL + pgvector
```

## Storage Boundary

PostgreSQL stores searchable facts and pointers. It does not store big binary
assets. Real files live in local storage, mounted network storage, an internal
file service, or S3-compatible object storage such as MinIO.

The key columns are:

- `assets.storage_backend`
- `assets.storage_uri`
- `assets.file_path`
- `assets.source_url`
- `assets.thumbnail_uri`

This lets the same retrieval code work with local prototypes and production
server, NAS, or object-storage setups.

## Future Image Search

For image-heavy assistant search, ingest these signals:

- filename and folder context
- campaign/project metadata
- language, period, asset kind, campaign context
- generated caption
- OCR text
- dominant visible subjects/products
- thumbnail URI
- optional image embedding in a later table/column

The first implementation can search images through text embeddings generated
from captions/OCR/metadata. A later multimodal retrieval layer can be added
without changing the public chat API.

## Future Document RAG

Documents should be chunked into `document_chunks` with:

- stable document id
- chunk index
- heading
- page number
- content
- embedding text
- vector embedding
- keyword `search_vector`

The assistant already has a `search_documents` tool; later ingestion only needs
to populate the tables.

## Assistant Response Modes

The browser companion uses a structured route before retrieval:

- `image_search`: retrieve assets and show image findings with a preview modal.
- `document_answer`: retrieve PDF chunks and keep the UI chat-only, with source chips.
- `mixed_search`: retrieve both, show source chips and image findings together.
- `general_chat`: answer without retrieval.

This keeps the old ALDI-like pattern where visual searches produce a browsable
findings table, while normal questions remain a streamed chat answer.
