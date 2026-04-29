CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS projects (
  id SERIAL PRIMARY KEY,
  external_id TEXT UNIQUE,
  name TEXT NOT NULL,
  year INT,
  client TEXT,
  source_uri TEXT,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assets (
  id SERIAL PRIMARY KEY,
  project_id INT REFERENCES projects(id) ON DELETE SET NULL,
  external_id TEXT UNIQUE,
  file_name TEXT,
  file_path TEXT,
  file_type TEXT,
  file_size BIGINT,
  storage_backend TEXT DEFAULT 'local',
  storage_uri TEXT,
  source_url TEXT,
  thumbnail_uri TEXT,
  content_hash TEXT,
  asset_kind TEXT,
  language TEXT,
  period TEXT,
  campaign_context TEXT,
  description TEXT,
  asset_content TEXT,
  document_content TEXT,
  image_width INT,
  image_height INT,
  metadata JSONB DEFAULT '{}'::jsonb,
  embedding_text TEXT,
  embedding vector(1536),
  search_vector tsvector,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
  id SERIAL PRIMARY KEY,
  external_id TEXT UNIQUE,
  title TEXT NOT NULL,
  source_uri TEXT,
  doc_type TEXT,
  language TEXT,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_chunks (
  id SERIAL PRIMARY KEY,
  document_id INT REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  heading TEXT,
  content TEXT NOT NULL,
  page_number INT,
  metadata JSONB DEFAULT '{}'::jsonb,
  embedding_text TEXT,
  embedding vector(1536),
  search_vector tsvector,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS status_meetings (
  id SERIAL PRIMARY KEY,
  title TEXT,
  week_number INT,
  year INT,
  meeting_date DATE,
  participants TEXT,
  source_uri TEXT,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS topics (
  id SERIAL PRIMARY KEY,
  meeting_id INT REFERENCES status_meetings(id) ON DELETE CASCADE,
  category TEXT,
  topic TEXT,
  content TEXT,
  responsible TEXT,
  status TEXT,
  deadline TEXT,
  is_absence BOOLEAN DEFAULT FALSE,
  metadata JSONB DEFAULT '{}'::jsonb,
  embedding_text TEXT,
  embedding vector(1536),
  search_vector tsvector,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_sessions (
  id UUID PRIMARY KEY,
  title TEXT,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id BIGSERIAL PRIMARY KEY,
  session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION assets_search_vector_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('simple', COALESCE(NEW.description, '')), 'A') ||
    setweight(to_tsvector('simple', COALESCE(NEW.asset_content, '')), 'B') ||
    setweight(to_tsvector('simple', COALESCE(NEW.document_content, '')), 'B') ||
    setweight(to_tsvector('simple', COALESCE(NEW.embedding_text, '')), 'B') ||
    setweight(to_tsvector('simple', COALESCE(NEW.file_name, '')), 'C') ||
    setweight(to_tsvector('simple', COALESCE(NEW.asset_kind, '')), 'C') ||
    setweight(to_tsvector('simple', COALESCE(NEW.language, '')), 'C') ||
    setweight(to_tsvector('simple', COALESCE(NEW.period, '')), 'C');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION document_chunks_search_vector_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('simple', COALESCE(NEW.heading, '')), 'A') ||
    setweight(to_tsvector('simple', COALESCE(NEW.content, '')), 'B') ||
    setweight(to_tsvector('simple', COALESCE(NEW.embedding_text, '')), 'B');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION topics_search_vector_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('simple', COALESCE(NEW.topic, '')), 'A') ||
    setweight(to_tsvector('simple', COALESCE(NEW.content, '')), 'B') ||
    setweight(to_tsvector('simple', COALESCE(NEW.category, '')), 'C') ||
    setweight(to_tsvector('simple', COALESCE(NEW.responsible, '')), 'C');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_assets_search_vector ON assets;
CREATE TRIGGER trg_assets_search_vector
  BEFORE INSERT OR UPDATE ON assets
  FOR EACH ROW EXECUTE FUNCTION assets_search_vector_update();

DROP TRIGGER IF EXISTS trg_document_chunks_search_vector ON document_chunks;
CREATE TRIGGER trg_document_chunks_search_vector
  BEFORE INSERT OR UPDATE ON document_chunks
  FOR EACH ROW EXECUTE FUNCTION document_chunks_search_vector_update();

DROP TRIGGER IF EXISTS trg_topics_search_vector ON topics;
CREATE TRIGGER trg_topics_search_vector
  BEFORE INSERT OR UPDATE ON topics
  FOR EACH ROW EXECUTE FUNCTION topics_search_vector_update();

CREATE INDEX IF NOT EXISTS idx_assets_embedding_hnsw
  ON assets USING hnsw (embedding vector_cosine_ops)
  WITH (m = 24, ef_construction = 200);

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw
  ON document_chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 24, ef_construction = 200);

CREATE INDEX IF NOT EXISTS idx_topics_embedding_hnsw
  ON topics USING hnsw (embedding vector_cosine_ops)
  WITH (m = 24, ef_construction = 200);

CREATE INDEX IF NOT EXISTS idx_assets_search_gin ON assets USING gin (search_vector);
CREATE INDEX IF NOT EXISTS idx_document_chunks_search_gin ON document_chunks USING gin (search_vector);
CREATE INDEX IF NOT EXISTS idx_topics_search_gin ON topics USING gin (search_vector);

CREATE INDEX IF NOT EXISTS idx_assets_asset_kind ON assets (asset_kind);
CREATE INDEX IF NOT EXISTS idx_assets_language ON assets (language);
CREATE INDEX IF NOT EXISTS idx_assets_file_type ON assets (file_type);
CREATE INDEX IF NOT EXISTS idx_assets_period ON assets (period);
CREATE INDEX IF NOT EXISTS idx_assets_campaign_context ON assets (campaign_context);
CREATE INDEX IF NOT EXISTS idx_assets_storage_backend ON assets (storage_backend);
CREATE INDEX IF NOT EXISTS idx_projects_year ON projects (year);
CREATE INDEX IF NOT EXISTS idx_documents_doc_type ON documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_documents_language ON documents (language);
CREATE INDEX IF NOT EXISTS idx_topics_category ON topics (category);
CREATE INDEX IF NOT EXISTS idx_topics_responsible ON topics (responsible);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
  ON chat_messages (session_id, created_at);
