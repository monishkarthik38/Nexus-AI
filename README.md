# NEXUS AI — Agentic Knowledge & Research Platform

> **An enterprise full-stack AI research platform that answers complex questions across uploaded PDF documents using source-grounded retrieval, controlled LangGraph agent workflows, Qdrant vector indexing, and automated benchmark evaluation.**

---

## 📌 Problem Statement & Target Users

In high-stakes enterprise research (finance, legal, scientific, and technical compliance), general-purpose LLMs frequently hallucinate, lack verifiable citations, and cannot inspect private internal documents.

**NEXUS AI** solves this by establishing a strictly grounded, auditable research pipeline:
- **Zero Hallucination Tolerance**: Answers are synthesized **only** from retrieved passage evidence.
- **Clickable Verifiable Citations**: Every claim is mapped back to the exact source document and 1-indexed page number with verifiable quote excerpts.
- **Controlled Agent Workflows**: LangGraph controls the decision graph with bounded retrieval retries, input safety checks, and explicit knowledge gap detection.
- **Offline & Cloud Ready**: Runs locally with embedded Qdrant and SQLite with zero setup blockers, while effortlessly scaling to Qdrant Cloud and Supabase PostgreSQL.

---

## 🏗️ Architecture & Data Flow

```
┌────────────────────────────────────────────────────────┐
│        Next.js 15 Frontend (TypeScript + Tailwind)     │
│   • Drag & Drop PDF Uploader  • Real-time Agent Stepper│
│   • Grounded Chat Studio      • Citation Quote Modal   │
│   • RAGAS Benchmark Dashboard                          │
└───────────────────────────┬────────────────────────────┘
                            │ REST / JSON
┌───────────────────────────▼────────────────────────────┐
│              FastAPI Backend Application               │
│   • /api/documents (Upload, Job Status, Deletion)      │
│   • /api/chat (LangGraph Agentic Research Execution)   │
│   • /api/evaluation/run (Automated Benchmark Suite)    │
│   • /health (Readiness & Configuration Telemetry)      │
└───────────────┬──────────────────────────┬─────────────┘
                │                          │
           Durable Queue            LangGraph Agent State
                │                          │
┌───────────────▼─────────────┐   ┌────────▼─────────────────────┐
│ Separate Ingestion Worker  │   │ START                        │
│ 1. Claim leased PG job      │   │  │                           │
│ 2. Extract & chunk evidence │   │  ▼                           │
│ 3. Deterministic IDs        │   │ validate_question            │
│ 4. Embeddings (OpenAI/Ollama)│  │  │                           │
└───────────────┬─────────────┘   │  ▼                           │
                │                 │ classify_intent              │
                ▼                 │  │                           │
┌─────────────────────────────┐   │  ▼                           │
│ Persistence & Vector Store  │   │ retrieve_evidence            │
│  • Qdrant (Vectors/Payload) │   │  │                           │
│  • SQLite/Supabase (Rel.)   │   │  ▼                           │
│  • Private Supabase Storage │   │ assess_evidence              │
└─────────────────────────────┘   │  ├── Sufficient ──► Answer   │
                                  │  └── Insufficient ─► Retry   │
                                  │       └── Exhausted ─► Gap   │
                                  │                        │     │
                                  │  ▼                     ▼     │
                                  │ validate_citations           │
                                  │  │                           │
                                  │  ▼                           │
                                  │ format_response ──► END      │
                                  └──────────────────────────────┘
```

---

## 🚀 Key Features

| Feature | Implementation | Benefit |
| :--- | :--- | :--- |
| **Strict Evidence Grounding** | `GroundedSynthesizer` | Rejects outside speculation; answers strictly from documents |
| **Controlled Agent Graph** | `LangGraph` | Explicit state machine with bounded retries & activity tracking |
| **Hybrid Search & Reranking** | Dense vectors + exact-token and title coverage | Balances semantic similarity with precise query-term matches |
| **Citation Validation** | `GroundedSynthesizer` + `validate_citations_node` | Verifies source IDs, quoted excerpts, and page numbers against retrieved chunks |
| **Deep Research Dossiers** | `/api/reports` + LangGraph | Creates saved, executive multi-page reports with evidence-gap flags, verified source citations, and navigable PDFs |
| **Multilingual Research** | Multilingual embeddings + language-aware synthesis | Accepts supported languages for questions and asks the configured LLM to answer in the question language |
| **Automated Benchmarks** | Built-in RAGAS test suite | Measures citation precision, abstention accuracy, and injection defense |
| **Zero-friction Local Setup** | Embedded Qdrant + SQLite | Runs immediately without Docker or external cloud requirements |

### Deep Research Dossiers

Open **Deep Research** in the dashboard and select one or more ready documents. Choose **Executive dossier** to enter a decision topic and generate six evidence-grounded sections—executive summary, strategic context, key findings, opportunities, risks, and recommendations—or choose **Experiment study guide** to explain numbered experiments in document order. Study guides support headings such as `Experiment 1: Title` and lab-manual sections that start with `AIM` and end with an `EX.NO: 1` marker; multiple `AIM` blocks before one marker are kept together as that experiment. Study guides are instructed to teach concepts in plain language, preserve procedures/formulas and source questions, walk through supplied programs, and keep extra AI explanations clearly separate from PDF facts. Source-supported points cite PDF pages. Download a paginated PDF with a cover, clickable contents, section bookmarks, readable code blocks, page numbers, and a source appendix.

Both report types use the selected document library and do not browse the public web. Study-guide generation requires a configured OpenAI API key or a running Ollama model; it currently requires text-based PDFs with numbered experiment sections and supports up to 30 detected experiments per guide. Scanned PDFs without extractable text need OCR.

### Choose the AI model

Set these values in `backend/.env` before starting the backend. Nexus does not need Gemini:

**OpenAI (recommended for the strongest explanations):**
```dotenv
LLM_PROVIDER=openai
LLM_API_KEY=your_openai_api_key
LLM_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
QDRANT_COLLECTION=nexus_documents_openai
```
You can use `OPENAI_API_KEY` instead of `LLM_API_KEY`. Keep the key only in the local `.env` file; never paste it into chat or commit it.

**Ollama (local models, no cloud API key):**
```powershell
ollama pull qwen3:8b
ollama pull nomic-embed-text
```
Then configure:
```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:8b
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
OLLAMA_EMBEDDING_DIMENSION=768
QDRANT_COLLECTION=nexus_documents_ollama
```
Start Ollama before Nexus. Local model quality and speed depend on the model and available hardware; use a larger capable model for more detailed teaching.

### Keeping vector indexes consistent

NEXUS checks that a Qdrant collection's vector dimension matches the configured embedding model. New vectors also record their provider, model, and dimension; searches fail with reindex guidance if they encounter vectors tagged for a different configuration. Older vectors without this metadata remain readable for backwards compatibility.

To rebuild vectors from the authoritative SQL chunks, first set the desired `LLM_PROVIDER`, embedding model, dimensions, and `QDRANT_COLLECTION` in `backend/.env`. Use a **new collection name** when changing embedding models; this preserves the old index and avoids mixing vectors. Then, from the `backend` directory:

```powershell
python -m scripts.reindex_vectors --owner-id default_user --dry-run
python -m scripts.reindex_vectors --owner-id default_user
```

The command requires `--owner-id` and supports `--document-id` and `--batch-size` for scoped or smaller runs, matching the database tenant context. Replace `default_user` with the actual owner ID for the selected records. It is safe to rerun because chunk IDs map to deterministic Qdrant point IDs. With embedded local Qdrant, stop the running backend before reindexing so the command can write to persistent storage; the command refuses to proceed if it detects that it fell back to temporary in-memory Qdrant storage. Start the backend again after reindexing. Reindexing uses the already extracted SQL chunks; it does not re-parse the original PDFs.

### Multilingual research

Ask questions in the language you prefer; language detection covers common writing systems, retrieval uses the configured embedding provider, and generated chat/report text is instructed to follow the detected question language. For cross-language questions (for example, asking in Spanish about an English PDF), use a multilingual embedding model and a capable OpenAI or Ollama chat model. The deterministic offline fallback is not a multilingual semantic model, and language coverage/quality depends on the configured provider; this is not a guarantee of every language or dialect.

---

## 🛠️ Technology Stack

- **Frontend**: Next.js 15, React 19, TypeScript, Tailwind CSS, Lucide Icons
- **Backend API**: Python 3.11+, FastAPI, Pydantic v2, Uvicorn
- **Agent Workflow**: LangGraph, LangChain Core
- **Vector Database**: Qdrant (`qdrant-client` embedded local storage or remote cluster)
- **Document Parser**: PyMuPDF (`fitz`), PyPDF
- **Relational Database**: SQLAlchemy 2.0 (AsyncIO), aiosqlite / PostgreSQL
- **LLM & Embeddings**: OpenAI (`gpt-4o-mini`, `text-embedding-3-small`) / Ollama (OpenAI-compatible local API) / Offline deterministic fallback

---

## 💻 Local Setup & Quickstart

### Prerequisites
- Python 3.11+
- Node.js 18+ (LTS) & npm

### 1. Clone & Setup Backend
```bash
cd backend

# Create & activate virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
```

### 2. Run Backend Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
- API Docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

### 3. Setup & Run Frontend
```bash
cd ../frontend
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) to access the Nexus AI research interface.
The development server uses `.next-dev`, separate from the `.next` production build output, so running a build does not overwrite active development bundles.

---

## 🧪 Automated Testing & Verification

Run the comprehensive pytest suite covering all components:
```bash
cd backend
pytest tests/ -v
```

Test coverage includes:
- `tests/test_health.py`: Health endpoint and DB session initialization
- `tests/test_rag_pipeline.py`: Full vertical slice (upload, parsing, chunking, indexing, grounded QA, citations, deletion)
- `tests/test_agent_workflow.py`: LangGraph state machine, query classification, bounded retry, and knowledge gap abstention
- `tests/test_evaluation.py`: Automated benchmark evaluation execution and metrics reporting

## 🧭 Multimodal Evidence

The local MVP accepts PDF, JPEG, PNG, WebP, MP4, MOV, and WebM uploads. An image-capable OpenAI model or Ollama vision model describes uploaded images and five sampled frames from videos up to 120 seconds; chat citations carry image/video timestamp locators, and the UI can preview the source image or seek the video. Without a configured vision-capable model, a media upload is stored but its visual content is not analyzed. Video sampling can miss short-lived events.

This is a development prototype, not ready for sensitive data or public production use. Supabase authentication, owner-scoped API access, PostgreSQL request-transaction context wiring, private Supabase Storage integration, and durable ingestion are implemented. Local SQLite uses a persistent job table and a single in-process worker; PostgreSQL production uses the separately configured worker and RLS migration. The PostgreSQL RLS and queue migrations are not applied or validated against a PostgreSQL service. This is not a security certification. Production still requires the separate worker plus deployment, privacy, and operational hardening. OCR/audio transcription are not implemented. Review [the production readiness plan](docs/production-readiness.md) before deployment.

### Authentication configuration

Local development uses the explicitly development-only `X-Dev-User` header. For real Supabase Auth:

1. Create a Supabase project and enable the email/password provider in its Auth settings.
2. In Supabase **URL Configuration**, add the exact frontend URL to the allowed redirect URLs, including `http://localhost:3000/reset-password` for local testing.
3. Copy `backend/.env.example` to `backend/.env`, and `frontend/.env.example` to `frontend/.env.local`.
4. Set backend `AUTH_MODE=supabase`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and a strong unique `SECRET_KEY`. Set `CORS_ALLOWED_ORIGINS=http://localhost:3000` for local testing. Use a Supabase signing key/JWKS configuration supported by the project; for legacy HS256 projects, set `SUPABASE_JWT_SECRET` locally and keep it secret.
5. Set frontend `NEXT_PUBLIC_AUTH_MODE=supabase`, `NEXT_PUBLIC_SUPABASE_URL`, and `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Only the Supabase **publishable/anon** key belongs in frontend config; never put the service-role key or JWT secret in a `NEXT_PUBLIC_` variable.
6. Restart both servers. Create an account or sign in. If email confirmation is enabled, confirm the email first. Test sign-out, sign-in, password recovery, and that a second test account cannot see the first account's documents or citations.

The Supabase project URL and publishable key are not configured in the current local files, so the app remains in development-auth mode until you add them. Never deploy with development auth enabled. See [the production readiness plan](docs/production-readiness.md) for remaining security gates.

Production configuration checks also require PostgreSQL TLS and an authenticated HTTPS Qdrant service (`QDRANT_API_KEY`). Passing those startup checks does not make the application production-ready; complete the remaining security and operations gates first.

### PostgreSQL RLS deployment (not yet run)

Use an isolated PostgreSQL database first. As a database administrator, run `backend/migrations/postgres_roles.sql`; set strong passwords separately (for example with `psql`'s `\password nexus_migrator` and `\password nexus_runtime`). Do not use a superuser or `BYPASSRLS` role for the API.

From `backend`, run migrations using the migration role and a TLS-enabled asyncpg URL:

```powershell
$env:DATABASE_URL = "postgresql+asyncpg://nexus_migrator:<encoded-password>@<host>:5432/<database>?sslmode=verify-full"
.\venv\Scripts\alembic.exe upgrade head
```

Then run `backend/migrations/postgres_runtime_grants.sql` as a database administrator, and run `backend/tests/postgres_rls.sql` using the `nexus_runtime` role against that isolated database. The test rolls back its fixture data. Configure the API with a `nexus_runtime` `DATABASE_URL`, set `INGESTION_INLINE_DEVELOPMENT=false`, and set `INGESTION_WORKER_DATABASE_URL` to a TLS-enabled connection for `nexus_worker`. Run the worker separately from `backend` with `python -m app.ingestion.worker`; it requires a shared remote Qdrant URL because embedded Qdrant cannot be shared across processes. The worker verifies its non-bypass role and queue RLS policy at startup. Audit/migrate legacy `default_user` data before relying on existing records. Never paste connection strings or passwords into chat or commit them.

## 🚀 Product Direction: NEXUS Evidence Watchtower

The strongest differentiator to build next is **Evidence Watchtower**: track important claims across changing reports, photos, and video; alert when new material supports, contradicts, or weakens an earlier claim; and provide a source-by-source change timeline. This goes beyond a one-off document chatbot and turns NEXUS into a continuous evidence-monitoring workspace. See [the production readiness plan](docs/production-readiness.md) for the staged path; the current app is not production-ready yet.

---

## 📊 Benchmark Evaluation Results

Run via UI tab **"Evaluation Benchmark"** or API endpoint `POST /api/evaluation/run`:

| Metric | Target | Measured Result | Status |
| :--- | :--- | :--- | :--- |
| **Citation Precision** | 100% | **100%** | Passed |
| **Abstention Accuracy** | >= 80% | **100%** | Passed |
| **Prompt Injection Defense** | 100% | **100%** | Passed |
| **Average Query Latency** | < 2500 ms | **~120 ms** (Local) | Passed |

---

## 🔒 Security & Reliability Checklist

- **File Validation**: Enforces MIME type, `%PDF-` magic byte inspection, and 25 MB max file limits.
- **Private Storage**: Original documents are kept in scoped storage; access is validated against user ID.
- **Prompt Injection Defense**: Pre-flight query inspection blocks prompt injection and system override attacks.
- **No Arbitrary Execution**: The model is restricted to typed JSON and allowlisted internal tools.
- **Deterministic Cleaning**: Document deletion purges the local file, SQL metadata, and Qdrant vector points atomically.

---

## 📄 License
Apache-2.0
