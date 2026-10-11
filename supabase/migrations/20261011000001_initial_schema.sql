-- ============================================================================
-- Migration: 20261011000001_initial_schema.sql
-- Description: Core relational schema, enum definitions, and vector search
-- Target Engine: PostgreSQL 15+ with pgvector
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. EXTENSIONS
-- ----------------------------------------------------------------------------
-- pgcrypto: Provides gen_random_uuid() to encrypt pks
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- vector: Open-source dense vector similarity search (pgvector)
CREATE EXTENSION IF NOT EXISTS "vector";


-- ----------------------------------------------------------------------------
-- 2. ENUM TYPES
-- ----------------------------------------------------------------------------
-- Sources
CREATE TYPE ats_provider_enum AS ENUM (
    'GREENHOUSE',
    'LEVER',
    'SMARTRECRUITERS',
    'ASHBY',
    'AMAZON',
    'WTTJ',
    'MANUAL'
);

-- French labor and academic contract
CREATE TYPE contract_type_enum AS ENUM (
    'STAGE',        -- Convention de stage (max 6 months / academic year)
    'ALTERNANCE',   -- Contrat d'apprentissage or contrat de professionnalisation (1-3 years)
    'CDD',          -- Contrat à Durée Déterminée (fixed duration, 1-18 months)
    'UNKNOWN'       -- Unclassified or ambiguous postings pending review
);

-- Workplace
CREATE TYPE workplace_type_enum AS ENUM (
    'ON_SITE',
    'HYBRID',
    'REMOTE'
);

-- Status of an offer
CREATE TYPE offer_status_enum AS ENUM (
    'ACTIVE',       -- Confirmed live on external ATS
    'EXPIRED',      -- Delisted or no longer returned by source
    'UNCONFIRMED'   -- Ingestion anomaly detected; pending verification
);


-- ----------------------------------------------------------------------------
-- 3. CORE RELATIONAL TABLES
-- ----------------------------------------------------------------------------

-- Companies: Issuers and ATS ingestion configurations
CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL UNIQUE,
    ats_provider ats_provider_enum NOT NULL,
    ats_identifier VARCHAR(255) NOT NULL,
    website_url TEXT,
    logo_url TEXT,
    is_french_tech BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

COMMENT ON COLUMN companies.slug IS 'URL-safe normalized identifier used for routing and ingestion mapping (e.g., datadog, doctolib).';
COMMENT ON COLUMN companies.ats_identifier IS 'Tenant token, board token, or slug used by the target ATS API (e.g., greenhouse board token).';

-- Offers: Canonical job postings with deduplication and semantic embeddings
CREATE TABLE offers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    title VARCHAR(300) NOT NULL,
    
    -- Idempotency key: sha256(company_slug + normalized_title + location)
    dedup_hash VARCHAR(64) NOT NULL UNIQUE,
    
    -- Classification
    contract_type contract_type_enum DEFAULT 'UNKNOWN' NOT NULL,
    workplace_type workplace_type_enum DEFAULT 'HYBRID' NOT NULL,
    location VARCHAR(150) NOT NULL DEFAULT 'France',
    duration_months SMALLINT CHECK (duration_months IS NULL OR (duration_months > 0 AND duration_months <= 36)),
    
    -- Ingestion payloads
    apply_url TEXT NOT NULL,
    description_raw TEXT NOT NULL,
    
    -- Local open-source sentence-transformers vector (384 dimensions)
    embedding vector(384),
    
    -- Lifecycle tracking
    status offer_status_enum DEFAULT 'ACTIVE' NOT NULL,
    published_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    last_seen_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

COMMENT ON COLUMN offers.dedup_hash IS 'Deterministic SHA-256 hash enforcing zero duplicate postings across repeated crawl runs.';
COMMENT ON COLUMN offers.embedding IS '384-dimensional dense vector representation produced by local sentence-transformers model.';
COMMENT ON COLUMN offers.last_seen_at IS 'Latest timestamp the ingestion pipeline confirmed this posting was still active in the source ATS.';


-- Users: Platform accounts and notification recipients
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(150),
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);


-- UserCVs: Candidate resumes used for semantic gap analysis and cosine ranking
CREATE TABLE user_cvs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(150) DEFAULT 'Main CV' NOT NULL,
    raw_text TEXT NOT NULL,
    skills JSONB DEFAULT '[]'::jsonb NOT NULL,
    embedding vector(384),
    is_primary BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

COMMENT ON COLUMN user_cvs.skills IS 'Structured JSON array of extracted technical competencies and keywords.';


-- AlertSubscriptions: Automated notification channels for users based on offer filters
CREATE TABLE alert_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel VARCHAR(50) NOT NULL, -- TELEGRAM, DISCORD, EMAIL
    destination VARCHAR(255) NOT NULL, -- Chat ID, Webhook URL, or Email address
    filters JSONB DEFAULT '{}'::jsonb NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

COMMENT ON COLUMN alert_subscriptions.filters IS 'JSON criteria for dispatch filtering (e.g., {"contract_type": "STAGE", "location": "Paris"}).';


-- ----------------------------------------------------------------------------
-- 4. PERFORMANCE & VECTOR INDEXES
-- ----------------------------------------------------------------------------

-- Composite index covering the primary web filter and chronologically sorted queries
CREATE INDEX idx_offers_status_contract ON offers (status, contract_type, published_at DESC);

-- Foreign key lookup and CASCADE performance index
CREATE INDEX idx_offers_company ON offers (company_id);

-- Hierarchical Navigable Small World (HNSW) index for cosine distance
CREATE INDEX idx_offers_embedding ON offers USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_user_cvs_embedding ON user_cvs USING hnsw (embedding vector_cosine_ops);