-- Run against an isolated PostgreSQL test database as nexus_runtime after
-- applying Alembic migrations through 003_durable_ingestion and runtime grants.
BEGIN;

SELECT set_config('app.current_user_id', 'rls-test-tenant-a', true);

INSERT INTO documents (id, owner_id, filename, storage_path, status, created_at)
VALUES (
    '00000000-0000-4000-8000-000000000001',
    'rls-test-tenant-a',
    'tenant-a.pdf',
    '/test/tenant-a.pdf',
    'ready',
    now()
);
INSERT INTO ingestion_jobs (id, document_id, owner_id, status, attempts, available_at, created_at, updated_at)
VALUES (
    '00000000-0000-4000-8000-000000000007',
    '00000000-0000-4000-8000-000000000001',
    'rls-test-tenant-a',
    'queued',
    0,
    now(),
    now(),
    now()
);
INSERT INTO document_chunks (
    id, document_id, page_number, chunk_index, content_hash, chunk_text, created_at
)
VALUES (
    'rls-test-chunk-a',
    '00000000-0000-4000-8000-000000000001',
    1,
    0,
    'rls-test-hash-a',
    'tenant A content',
    now()
);
INSERT INTO conversations (id, owner_id, title, created_at)
VALUES (
    '00000000-0000-4000-8000-000000000002',
    'rls-test-tenant-a',
    'tenant A conversation',
    now()
);
INSERT INTO messages (id, conversation_id, role, content, created_at)
VALUES (
    '00000000-0000-4000-8000-000000000003',
    '00000000-0000-4000-8000-000000000002',
    'user',
    'tenant A message',
    now()
);
INSERT INTO research_reports (
    id, owner_id, report_type, title, topic, document_ids, document_names, sections, created_at
)
VALUES (
    '00000000-0000-4000-8000-000000000004',
    'rls-test-tenant-a',
    'executive_dossier',
    'tenant A report',
    'test',
    '["00000000-0000-4000-8000-000000000001"]'::json,
    '["tenant-a.pdf"]'::json,
    '[]'::json,
    now()
);
INSERT INTO evaluation_runs (id, owner_id, dataset_version, metrics, status, created_at)
VALUES (
    '00000000-0000-4000-8000-000000000005',
    'rls-test-tenant-a',
    'rls-test',
    '{}'::json,
    'completed',
    now()
);
INSERT INTO evidence_annotations (
    id, owner_id, document_id, source_id, claim, passage, label, created_at
)
VALUES (
    '00000000-0000-4000-8000-000000000006',
    'rls-test-tenant-a',
    '00000000-0000-4000-8000-000000000001',
    'rls-test-chunk-a',
    'tenant A claim',
    'tenant A passage',
    'supports',
    now()
);

DO $$
BEGIN
    IF (SELECT count(*) FROM documents) <> 1
       OR (SELECT count(*) FROM document_chunks) <> 1
       OR (SELECT count(*) FROM conversations) <> 1
       OR (SELECT count(*) FROM messages) <> 1
       OR (SELECT count(*) FROM research_reports) <> 1
       OR (SELECT count(*) FROM evaluation_runs) <> 1
       OR (SELECT count(*) FROM evidence_annotations) <> 1
       OR (SELECT count(*) FROM ingestion_jobs) <> 1 THEN
        RAISE EXCEPTION 'RLS failure: tenant A cannot read its own rows';
    END IF;
END;
$$;

SELECT set_config('app.current_user_id', 'rls-test-tenant-b', true);

DO $$
DECLARE
    affected_rows integer;
BEGIN
    IF EXISTS (SELECT 1 FROM documents) THEN
        RAISE EXCEPTION 'RLS leak: documents visible across tenants';
    END IF;
    IF EXISTS (SELECT 1 FROM document_chunks) THEN
        RAISE EXCEPTION 'RLS leak: chunks visible across tenants';
    END IF;
    IF EXISTS (SELECT 1 FROM conversations) THEN
        RAISE EXCEPTION 'RLS leak: conversations visible across tenants';
    END IF;
    IF EXISTS (SELECT 1 FROM messages) THEN
        RAISE EXCEPTION 'RLS leak: messages visible across tenants';
    END IF;
    IF EXISTS (SELECT 1 FROM research_reports) THEN
        RAISE EXCEPTION 'RLS leak: reports visible across tenants';
    END IF;
    IF EXISTS (SELECT 1 FROM evaluation_runs) THEN
        RAISE EXCEPTION 'RLS leak: evaluation runs visible across tenants';
    END IF;
    IF EXISTS (SELECT 1 FROM evidence_annotations) THEN
        RAISE EXCEPTION 'RLS leak: annotations visible across tenants';
    END IF;
    IF EXISTS (SELECT 1 FROM ingestion_jobs) THEN
        RAISE EXCEPTION 'RLS leak: ingestion jobs visible across tenants';
    END IF;
    UPDATE documents
       SET filename = 'tampered.pdf'
     WHERE id = '00000000-0000-4000-8000-000000000001';
    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    IF affected_rows <> 0 THEN
        RAISE EXCEPTION 'RLS failure: cross-tenant document update succeeded';
    END IF;
    DELETE FROM conversations
     WHERE id = '00000000-0000-4000-8000-000000000002';
    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    IF affected_rows <> 0 THEN
        RAISE EXCEPTION 'RLS failure: cross-tenant conversation delete succeeded';
    END IF;
    BEGIN
        INSERT INTO documents (
            id, owner_id, filename, storage_path, status, created_at
        )
        VALUES (
            '00000000-0000-4000-8000-000000000011',
            'rls-test-tenant-a',
            'forbidden.pdf',
            '/test/forbidden.pdf',
            'ready',
            now()
        );
        RAISE EXCEPTION 'RLS failure: cross-tenant document insert succeeded';
    EXCEPTION
        WHEN insufficient_privilege THEN NULL;
    END;
    BEGIN
        INSERT INTO research_reports (
            id, owner_id, report_type, title, topic,
            document_ids, document_names, sections, created_at
        )
        VALUES (
            '00000000-0000-4000-8000-000000000012',
            'rls-test-tenant-a',
            'executive_dossier',
            'forbidden report',
            'test',
            '[]'::json,
            '[]'::json,
            '[]'::json,
            now()
        );
        RAISE EXCEPTION 'RLS failure: cross-tenant report insert succeeded';
    EXCEPTION
        WHEN insufficient_privilege THEN NULL;
    END;
END;
$$;

SELECT set_config('app.current_user_id', '', true);
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM documents)
       OR EXISTS (SELECT 1 FROM document_chunks)
       OR EXISTS (SELECT 1 FROM conversations)
       OR EXISTS (SELECT 1 FROM messages)
       OR EXISTS (SELECT 1 FROM research_reports)
       OR EXISTS (SELECT 1 FROM evaluation_runs)
       OR EXISTS (SELECT 1 FROM evidence_annotations)
       OR EXISTS (SELECT 1 FROM ingestion_jobs) THEN
        RAISE EXCEPTION 'RLS leak: rows visible without tenant context';
    END IF;
END;
$$;

ROLLBACK;
