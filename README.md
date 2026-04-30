# Intelligent Search Agent

Intelligent Search Agent is a local AI assistant for searching image assets and
PDF knowledge. It provides a browser chat interface, streams assistant answers,
shows image results in a clickable table, and cites PDF sources when the answer
comes from documents.

The project is inspired by an ALDI AI Companion-style workflow, but it does not
include guideline analysis. This repository is focused on the assistant and
retrieval layer only.

No Azure resources are required. The app runs locally or in Docker and uses
direct OpenAI API calls for chat, image understanding, and embeddings.

## What It Does

- Runs a FastAPI assistant UI at `http://localhost:8000/`
- Classifies each user request before searching
- Searches image assets with pgvector semantic retrieval
- Searches PDF chunks for document-grounded answers
- Streams the assistant response into the chat UI
- Shows image results as a table with clickable preview buttons
- Shows document sources as source chips with page links
- Stores chat sessions in PostgreSQL
- Provides read-only admin and corpus health endpoints
- Includes ingestion scripts for a Belgium demo corpus

## How It Works

```text
Browser chat UI
  |
  |-- POST /v1/chat/companion/stream
  |
FastAPI app
  |
  |-- Request router
  |     |-- image_search
  |     |-- document_answer
  |     |-- mixed_search
  |     |-- general_chat
  |
  |-- Retrieval services
  |     |-- assets
  |     |-- document chunks
  |
PostgreSQL + pgvector
  |
  |-- metadata
  |-- embeddings
  |-- source file pointers
  |-- chat sessions
```

The database does not store large image or PDF files. It stores metadata,
embeddings, captions, extracted PDF text, and pointers to files. Local demo
files live under `storage/assets`, which is intentionally ignored by git.

## Request Types

The assistant chooses one route for every user message.

| Route | When It Is Used | UI Behavior |
| --- | --- | --- |
| `image_search` | User asks for images, paintings, photos, maps, posters, or other visual assets | Streams a short answer and renders an image table |
| `document_answer` | User asks a historical or factual question | Searches PDF chunks and writes a sourced answer |
| `mixed_search` | User asks for both an answer and visual material | Shows document sources plus image results |
| `general_chat` | User asks something that does not need the corpus | Answers directly without retrieval |

Follow-up messages use recent chat history. For example, after asking for images
of the Belgian Revolution, the user can say `only paintings` and the assistant
will keep the original topic.

## Quick Start With Docker

Create a local `.env` file:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set:

```text
OPENAI_API_KEY=your_key_here
```

Start the app and database:

```powershell
.\scripts\start_local.ps1 -Build
```

Open:

- Assistant UI: `http://localhost:8000/`
- Health check: `http://localhost:8000/health`
- API docs: `http://localhost:8000/docs`

## PostgreSQL / pgAdmin

The Docker database is exposed on host port `5433`.

```text
Host: 127.0.0.1
Port: 5433
Database: intelligent_search_agent
User: postgres
Password: postgres
```

The database image includes pgvector through `pgvector/pgvector:pg17`.

## Manual Local Run

Use this when you want the API running directly on your machine while the
database still runs in Docker.

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
# edit .env and set OPENAI_API_KEY
docker compose up -d db
uvicorn intelligent_search_agent.app.main:app --reload --port 8000
```

When the API runs outside Docker, set this in `.env`:

```text
DB_HOST=localhost
DB_PORT=5433
```

## Ingest The Belgium Demo Corpus

The repository includes scripts for downloading and ingesting Belgian-history
images and PDFs. Downloaded files and generated manifests stay local under
`storage/` and are not committed.

Run ingestion:

```powershell
docker compose up -d db
python scripts\ingest_belgium_corpus.py --apply-schema
```

Useful safer commands:

```powershell
# inspect files and PDF chunking without OpenAI calls or DB writes
python scripts\ingest_belgium_corpus.py --dry-run

# ingest a small sample first
python scripts\ingest_belgium_corpus.py --apply-schema --image-limit 5 --pdf-limit 2

# process only PDFs
python scripts\ingest_belgium_corpus.py --skip-images

# refresh existing rows and regenerate VLM image descriptions
python scripts\ingest_belgium_corpus.py --force --refresh-vlm
```

The ingestion pipeline:

- describes each image with a vision model
- validates image metadata with Pydantic models
- extracts PDF text with PyMuPDF
- optionally OCRs textless PDF pages
- chunks PDF text by page
- embeds image and document search text
- upserts records into PostgreSQL

Expected populated demo corpus:

```text
assets: 150
documents: 40
document chunks: 1007
missing embeddings: 0
missing local files: 0
duplicate content hash groups: 0
```

## Main API Routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Runtime health |
| `POST` | `/v1/chat/companion/stream` | Main streaming assistant endpoint |
| `POST` | `/v1/chat/stream` | Basic streaming chat endpoint |
| `POST` | `/v1/chat` | Non-streaming chat wrapper |
| `GET` | `/v1/search` | Unified search |
| `GET` | `/v1/assets/search` | Search assets directly |
| `GET` | `/v1/assets/{id}` | Asset metadata |
| `GET` | `/v1/assets/{id}/file` | Serve or redirect to an asset file |
| `GET` | `/v1/documents/search` | Search document chunks directly |
| `GET` | `/v1/documents/{id}` | Document metadata |
| `GET` | `/v1/documents/{id}/chunks` | Document chunks |
| `GET` | `/v1/documents/{id}/file` | Serve or redirect to a PDF |
| `GET` | `/v1/admin/corpus/status` | Corpus counts and health checks |
| `GET` | `/v1/admin/chat/sessions` | Recent persisted chat sessions |

## Project Structure

```text
intelligent_search_agent/
  agent/assistant/       assistant routing, findings, answering, streaming
  app/routes/            FastAPI route handlers
  app/static/            browser chat UI
  core/                  configuration, logging, security helpers
  db/                    database services, queries, embeddings
  ingestion/             corpus ingestion and PDF/image processing
  models/                API response/request models
  retrieval/             file storage helpers

scripts/                 local utilities and ingestion entrypoints
sql/schema.sql           database schema and pgvector indexes
docs/                    architecture, data sources, evaluation prompts
storage/                 local corpus files, ignored by git
tests/                   unit tests
```

## Development Checks

Run these before committing code changes:

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest
python scripts\corpus_health.py --docker-db
```

Evaluate companion routing against the local running API:

```powershell
python scripts\evaluate_companion_routes.py
```

## Security And Local Data

- `.env` is ignored and must hold real secrets locally.
- `.env.example` contains placeholders only.
- `storage/assets/**` and `storage/manifests/**` are ignored because they hold
  downloaded corpus files and generated metadata.
- Set `ADMIN_API_KEY` before exposing admin routes outside local development.
- `ALLOWED_SOURCE_URL_HOSTS` controls which external file URLs can be redirected
  to by asset and document endpoints.

## Useful Docs

- `docs/architecture.md`
- `docs/data-sources.md`
- `docs/belgium-corpus-sources.md`
- `docs/evaluation-prompts.md`
- `docs/evals/companion_routes.jsonl`

## What Is Deliberately Not Included

This repository does not include the old guideline-compliance workflow:

- no guideline upload flow
- no layout, logo, or color compliance checks
- no guideline report generation
- no Azure-specific resources

Those features can be added later as separate modules. The current project is
the assistant and search core.

## Troubleshooting

If pgAdmin cannot connect, make sure the project database is running:

```powershell
docker compose up -d db
```

If the assistant UI loads but cannot answer corpus questions, check:

```powershell
python scripts\corpus_health.py --docker-db
```

If ingestion fails immediately, confirm `.env` contains `OPENAI_API_KEY` and the
database container is healthy:

```powershell
docker compose ps
```
