# NEXUS production-readiness plan

## Product thesis: Evidence Watchtower

Build NEXUS as a continuous evidence-monitoring workspace, not a generic chat-with-files app. Users follow a claim or decision; as new PDFs, images, and videos arrive, NEXUS identifies evidence that appears to support, contradict, or weaken the tracked claim, then presents a dated, source-linked change timeline for human review.

The product should say **model-suggested** until a reviewer labels an item. A model score is not proof. Preserve immutable source references, model/prompt versions, and review history so users can audit why an alert appeared.

## Staged implementation

### 0. Fail-safe deployment configuration — started

- CORS is restricted to explicit configured origins.
- Baseline security response headers are added.
- Production startup refuses development secrets, SQLite, embedded/local Qdrant, wildcard CORS, PostgreSQL URLs without TLS, and Qdrant without HTTPS/API-key configuration.

These changes are guardrails only; they do not authenticate users or make the service production-ready.

### 1. Identity, workspace isolation, and authorization — implementation started

- Supabase JWT verification and owner-scoped access controls are implemented for the current API surfaces.
- Chat and evaluation validate selected document IDs against the authenticated owner before starting their workflows; tests cover foreign-document rejection.
- Internal vector search/index/delete and evaluation calls now require an explicit owner context instead of falling back to `default_user`.
- Cross-tenant tests cover document, conversation, report/PDF, annotation, evaluation-run, chat/evaluation document scopes, and Qdrant query filters.
- A PostgreSQL migration now defines forced RLS policies for documents, chunks, conversations, messages, reports, evaluation runs, and annotations. `backend/tests/postgres_rls.sql` exercises tenant reads, missing-context denial, and cross-tenant inserts.
- Request database sessions now set `app.current_user_id` from the verified principal at every PostgreSQL transaction begin, using transaction-local `set_config(..., true)` so commits/rollbacks and pooled connections do not retain the setting. SQLite is unchanged.
- The RLS migration is not applied to the local SQLite database and has not been validated against PostgreSQL.
- Before applying RLS to existing data, audit every legacy `default_user` row and explicitly map its owner. Do not bulk-assign legacy records to an account without verified ownership.
- Apply the SQL migration with a migration role, then run `backend/tests/postgres_rls.sql` against an isolated test database using the runtime role (which must not be a superuser or have `BYPASSRLS`). Neither step has been run here because no PostgreSQL service/client is configured in this workspace.
- Standalone scripts that create `AsyncSessionLocal` directly do not have a verified request identity; with RLS enabled they will fail closed/have no tenant visibility until explicitly designed with a safe administrative identity and scoped access.
- PostgreSQL deployments use Alembic (`alembic upgrade head`); production startup no longer creates tables and fails unless revision `003_durable_ingestion` is current, each tenant policy is enabled/forced, and the API connection role (including inherited/settable memberships) is not superuser/`BYPASSRLS`.
- Use `backend/migrations/postgres_roles.sql` to create non-bypass migration/runtime/worker roles, run migrations as `nexus_migrator`, then apply `backend/migrations/postgres_runtime_grants.sql` as the database administrator. Set role passwords out of band and keep separate migration/runtime/worker connection strings.
- Maintenance tools now require an explicit `--owner-id` and set that tenant context before querying.
- Continue testing each resource path against production services and mixed-owner data; application-level query filters do not replace database row-level security.
- Define user offboarding, token expiry/revocation, service-to-service auth, and audit events.

Current code: set `AUTH_MODE=supabase`, `SUPABASE_URL`, and either a signing-key JWKS endpoint (ES256/RS256) or `SUPABASE_JWT_SECRET` (HS256) in the backend environment; set `NEXT_PUBLIC_AUTH_MODE=supabase`, `NEXT_PUBLIC_SUPABASE_URL`, and `NEXT_PUBLIC_SUPABASE_ANON_KEY` in the frontend environment. The frontend obtains a Supabase access token and sends it as a Bearer token; the backend validates signature, issuer, audience, expiry, and subject. Client `owner_id` fields have been removed from API contracts. The development-only `X-Dev-User` identity works only when `AUTH_MODE=development`; never enable it in production. Database initialization now includes an additive compatibility migration for existing SQLite and PostgreSQL schemas, including evaluation-run ownership.

This is an initial integration, not a completed security certification. Configure a real Supabase project, validate its signing-key mode and token rotation, add real-browser sign-in/refresh/sign-out tests, and complete a full endpoint/tenant-isolation review before launch. The local development identity is not authentication.

**Gate:** unauthenticated requests are rejected; changing a URL/body cannot expose another workspace's resources.

### 2. Reliable ingestion and private media storage

- A server-side Supabase Storage adapter now supports object upload, read, and deletion, with owner/document-scoped object keys. Production startup verifies that the configured bucket is private. Keep its service-role key exclusively in the backend environment.
- Production configuration now requires `STORAGE_BACKEND=supabase` and `SUPABASE_SERVICE_ROLE_KEY`. Local development continues to default to the local filesystem.
- The adapter uses server-side private object access; client-side signed upload/download URLs are not implemented.
- Upload now writes a durable tenant-owned ingestion job transactionally with the document metadata. `python -m app.ingestion.worker` runs the separate PostgreSQL worker; it claims with `FOR UPDATE SKIP LOCKED`, leases/heartbeats jobs, retries transient failures up to five times with backoff, and uses stable vector IDs for retry idempotency. `GET /api/documents/{id}/ingestion` reports the owner-scoped job ID, state, attempts, and safe error.
- The worker uses a distinct non-bypass `nexus_worker` role. It can claim queue rows across owners, while forced RLS still limits document/chunk access to the tenant context from the claimed job. Configure `INGESTION_WORKER_DATABASE_URL` with that role; it must use verified TLS in production.
- The API returns documents as processing immediately; the dashboard refreshes statuses until terminal. Deletion locks/cancels the queued work before removing the document and its vectors.
- SQLite development uses a single in-process background worker, so it shares the local embedded Qdrant instance. The SQLite claim is an atomic `UPDATE ... RETURNING`; jobs survive API restarts and expired leases can be reclaimed. `INGESTION_INLINE_DEVELOPMENT=true` optionally restores synchronous upload behavior for legacy local setups. Production validation requires that flag false and starts only the separately configured PostgreSQL worker.
- Do not run multiple API instances against the development SQLite database; this mode is for a single local prototype process and is not a production queue.
- Add malware/content scanning, resource quotas, checksums, timeouts, and orphan-file reconciliation.
- Version extractors, vision models, prompts, and evidence records. Add explicit retention/deletion and backup/restore policies.

**Gate:** worker restarts and retries do not duplicate Qdrant points or corrupt document states; deletion removes all associated records and assets.

### 3. Evidence Watchtower MVP

- Let a user save a reviewed claim as a watch item, including scope, evidence references, and last-reviewed time.
- On new ingestion, retrieve relevant evidence for watched claims; group alerts by source and modality.
- Show changes over time: new supporting evidence, contradiction, missing/removed source, or unresolved ambiguity.
- Require human review; support dismiss, confirm, and request-more-evidence actions with an audit trail.

**Gate:** replayable tests demonstrate each alert with document-disjoint test data and exact source locators.

### 4. Evaluation and model development

- Keep human annotations as the ground truth; separate training, validation, and locked document-disjoint test sets.
- Report per-class precision/recall/F1, calibration, abstention, latency, and failure slices per modality.
- Keep the current TF-IDF verifier experimental. Only show its output as a suggestion after it beats agreed minimum thresholds on real held-out documents.
- Version every model/data artifact and keep private source material out of public artifacts unless licensed.

### 5. Operations and release controls

- Add CI for backend tests, static checks, frontend build/type checks, dependency/security scans, and database migration tests.
- Add structured logs, traces, redaction, request IDs, rate limits, abuse detection, alerting, and SLOs.
- Use staged deployments, health/readiness probes, secrets management, backups, rollback plans, and incident procedures.
- Complete privacy, data-processing, copyright, retention, and accessibility reviews before public launch.

## Current status

The project has production-configuration guardrails, Supabase JWT authentication, explicit owner context in retrieval, per-transaction PostgreSQL tenant context wiring, cross-tenant API tests, a server-side Supabase Storage adapter, and durable ingestion for both single-process SQLite development and PostgreSQL worker deployments. **The PostgreSQL policies and queue migration have not been applied or run against PostgreSQL, and this is not a production security certification.** Live worker/provider tests, privacy/retention controls, independent security review, and operational hardening remain outstanding. Do not expose this build to the public internet or store sensitive documents. Storage and ingestion still require production-provider validation and operational hardening.
