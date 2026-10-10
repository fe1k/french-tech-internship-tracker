# French Tech Internship Tracker 🇫🇷

> Real-time ingestion engine and interactive platform tracking tech internships (_Stage_ & _Alternance_) across Big Tech, French Tech scaleups, and top VC-backed startups in France.

## Overview

French Tech Internship Tracker implements a dynamic platform, featuring automated multi-source ATS ingestion, deterministic deduplication, semantic CV matching, and automated GitHub synchronization.

## Architecture

- `apps/web`: Next.js (TypeScript, React 19, Tailwind CSS)
- `services/pipeline`: Python data ingestion engine (ATS connectors, embeddings, alert dispatchers)
- `supabase/migrations`: Versioned SQL migrations and relational schema
- `.github/workflows`: Scheduled automation and CI/CD pipelines

## License

MIT
