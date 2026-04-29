# Intelligent Search Agent

Local, Docker-friendly AI assistant for searching images and PDF knowledge with
PostgreSQL + pgvector. This project is inspired by the ALDI AI Companion flow,
but the guideline-analysis pipeline has been removed. The focus is the assistant:
chat, intent routing, asset search, document retrieval, and source previews.

There are no Azure resources in this version. The app runs locally, can be built
as a Docker image, and uses direct OpenAI API calls for chat, vision metadata,
and embeddings.

## What Works Now

- Browser chat UI at `http://localhost:8000/`
- Streaming assistant responses through `/v1/chat/companion/stream`
- Structured request routing with Pydantic AI:
  - image search
  - document answer
  - mixed image + document search
  - general chat
- Image result table with clickable preview buttons
- PDF/document source chips with excerpts and source links
- Follow-up awareness using recent chat messages
- Optional LLM reranking after deterministic vector retrieval
- Chat session persistence in PostgreSQL
- Read-only admin/corpus health endpoints
- Docker Compose setup with FastAPI and pgvector PostgreSQL
- Belgium demo corpus ingestion for local images and Belgian-history PDFs

## Architecture

```text
Browser UI
  |
  |-- POST /v1/chat/companion/stream
  |-- GET  /v1/assets/{id}/file
  |-- GET  /v1/documents/{id}/file
  |
FastAPI
  |
  |-- Pydantic AI routing
  |-- OpenAI chat, vision, and embeddings
  |-- Retrieval services
  |
PostgreSQL + pgvector
  |
  |-- assets
  |-- documents
  |-- document_chunks
  |-- chat_sessions
  |-- chat_messages
```

Real images and PDFs are not stored in PostgreSQL. The database stores metadata,
validated VLM descriptions, extracted text, embeddings, and file pointers. Local
prototype files live under `storage/assets`, which is intentionally ignored by
git except for placeholder `.gitkeep` files.

## Quick Start

```powershell
Copy-Item .env.example .env
# edit .env and set OPENAI_API_KEY
.\scripts\start_local.ps1 -Build
```

Open:

- `http://localhost:8000/` for the assistant UI
- `http://localhost:8000/health` for runtime health
- `http://localhost:8000/docs` for OpenAPI docs

The Docker database is exposed for pgAdmin on:

```text
Host: 127.0.0.1
Port: 5433
Database: intelligent_search_agent
User: postgres
Password: postgres
```

## Manual Local Run

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
# edit .env and set OPENAI_API_KEY
docker compose up -d db
uvicorn intelligent_search_agent.app.main:app --reload --port 8000
```

When running the API outside Docker against the Docker database, set `DB_PORT`
in `.env` to `5433`.

## Docker

```powershell
Copy-Item .env.example .env
# edit .env and set OPENAI_API_KEY
docker compose --env-file .env up --build
```

Build only:

```powershell
docker build -t intelligent-search-agent-api:local .
```

## Main API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Runtime health |
| `POST` | `/v1/chat/stream` | Basic streaming assistant |
| `POST` | `/v1/chat/companion/stream` | Assistant stream with routing, retrieval, citations, and image-table mode |
| `POST` | `/v1/chat` | Non-streaming assistant wrapper |
| `GET` | `/v1/search` | Unified search across indexed sources |
| `GET` | `/v1/assets/search` | Direct asset search |
| `GET` | `/v1/assets/{id}` | Asset metadata |
| `GET` | `/v1/assets/{id}/link` | Stored asset pointers |
| `GET` | `/v1/assets/{id}/file` | Serve or redirect to the asset |
| `GET` | `/v1/documents/search` | Direct document chunk search |
| `GET` | `/v1/documents/{id}` | Document metadata |
| `GET` | `/v1/documents/{id}/chunks` | Document chunks |
| `GET` | `/v1/documents/{id}/file` | Serve or redirect to the source PDF |
| `GET` | `/v1/admin/corpus/status` | Corpus counts, missing embeddings/files, duplicate groups |
| `GET` | `/v1/admin/chat/sessions` | Recent persisted chat sessions |

## Companion Behavior

The assistant classifies every user request before retrieval.

| Intent | Behavior |
| --- | --- |
| `image_search` | Search `assets`, stream a short answer, and render an image table with Show buttons |
| `document_answer` | Search PDF chunks and stream a prose answer with source chips |
| `mixed_search` | Search both assets and PDF chunks, then show prose, sources, and image results |
| `general_chat` | Answer directly without corpus retrieval |

The browser sends recent chat turns with each request, so follow-ups like
`only paintings` or `show the PDFs too` can reuse prior context.

## Ingest Belgium Corpus

After downloading images and PDFs into the expected local storage folders:

```powershell
docker compose up -d db
python scripts\ingest_belgium_corpus.py --apply-schema
```

Useful safer runs:

```powershell
# validate files and PDF chunking without OpenAI calls or DB writes
python scripts\ingest_belgium_corpus.py --dry-run

# ingest a small sample first
python scripts\ingest_belgium_corpus.py --apply-schema --image-limit 5 --pdf-limit 2

# only process PDFs
python scripts\ingest_belgium_corpus.py --skip-images

# force-refresh existing rows and regenerate VLM entries
python scripts\ingest_belgium_corpus.py --force --refresh-vlm
```

The script:

- analyzes images with `VISION_MODEL`
- validates VLM output with Pydantic models
- extracts and chunks PDF text
- OCRs textless PDF pages in `--pdf-ocr auto` mode
- embeds asset and document text
- upserts rows into PostgreSQL

Generated VLM caches, downloaded images, downloaded PDFs, and corpus manifests
stay local under `storage/` and are ignored by git.

## Checks

```powershell
python -m pytest
python scripts\evaluate_companion_routes.py
python scripts\corpus_health.py --docker-db
```

Expected populated demo corpus:

```text
assets: 150
documents: 40
document chunks: 1007
missing embeddings: 0
missing local files: 0
duplicate content hash groups: 0
```

## Security And Local Data

- `.env` is ignored and must contain the real `OPENAI_API_KEY`.
- `.env.example` contains placeholders only.
- `storage/assets/**` and `storage/manifests/**` are ignored because they hold
  downloaded source files and generated corpus metadata.
- Set `ADMIN_API_KEY` before exposing the API beyond local development.
- `ALLOWED_SOURCE_URL_HOSTS` limits external redirects for asset/document files.

## Project Docs

- `docs/architecture.md`
- `docs/data-sources.md`
- `docs/belgium-corpus-sources.md`
- `docs/evaluation-prompts.md`
- `docs/evals/companion_routes.jsonl`

## Deliberately Excluded

The old ALDI guideline-compliance workflow is not part of this repo:

- no guideline upload or analysis routes
- no logo/layout/color compliance checks
- no Azure services
- no guideline report generation

Those can be added later as separate features, but this repo is currently the
assistant and search core.
