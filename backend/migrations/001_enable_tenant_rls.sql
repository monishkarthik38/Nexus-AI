-- Apply with a migration role after the application tables exist.
-- Runtime connections must use a non-superuser role without BYPASSRLS.
BEGIN;

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON documents;
CREATE POLICY tenant_isolation ON documents
    USING (owner_id = NULLIF(current_setting('app.current_user_id', true), ''))
    WITH CHECK (owner_id = NULLIF(current_setting('app.current_user_id', true), ''));

ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON document_chunks;
CREATE POLICY tenant_isolation ON document_chunks
    USING (
        EXISTS (
            SELECT 1
            FROM documents AS d
            WHERE d.id = document_chunks.document_id
              AND d.owner_id = NULLIF(current_setting('app.current_user_id', true), '')
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM documents AS d
            WHERE d.id = document_chunks.document_id
              AND d.owner_id = NULLIF(current_setting('app.current_user_id', true), '')
        )
    );

ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON conversations;
CREATE POLICY tenant_isolation ON conversations
    USING (owner_id = NULLIF(current_setting('app.current_user_id', true), ''))
    WITH CHECK (owner_id = NULLIF(current_setting('app.current_user_id', true), ''));

ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON messages;
CREATE POLICY tenant_isolation ON messages
    USING (
        EXISTS (
            SELECT 1
            FROM conversations AS c
            WHERE c.id = messages.conversation_id
              AND c.owner_id = NULLIF(current_setting('app.current_user_id', true), '')
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM conversations AS c
            WHERE c.id = messages.conversation_id
              AND c.owner_id = NULLIF(current_setting('app.current_user_id', true), '')
        )
    );

ALTER TABLE research_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE research_reports FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON research_reports;
CREATE POLICY tenant_isolation ON research_reports
    USING (owner_id = NULLIF(current_setting('app.current_user_id', true), ''))
    WITH CHECK (owner_id = NULLIF(current_setting('app.current_user_id', true), ''));

ALTER TABLE evaluation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_runs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON evaluation_runs;
CREATE POLICY tenant_isolation ON evaluation_runs
    USING (owner_id = NULLIF(current_setting('app.current_user_id', true), ''))
    WITH CHECK (owner_id = NULLIF(current_setting('app.current_user_id', true), ''));

ALTER TABLE evidence_annotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_annotations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON evidence_annotations;
CREATE POLICY tenant_isolation ON evidence_annotations
    USING (
        owner_id = NULLIF(current_setting('app.current_user_id', true), '')
        AND EXISTS (
            SELECT 1
            FROM documents AS d
            JOIN document_chunks AS c
              ON c.document_id = d.id
            WHERE d.id = evidence_annotations.document_id
              AND c.id = evidence_annotations.source_id
              AND d.owner_id = NULLIF(current_setting('app.current_user_id', true), '')
        )
    )
    WITH CHECK (
        owner_id = NULLIF(current_setting('app.current_user_id', true), '')
        AND EXISTS (
            SELECT 1
            FROM documents AS d
            JOIN document_chunks AS c
              ON c.document_id = d.id
            WHERE d.id = evidence_annotations.document_id
              AND c.id = evidence_annotations.source_id
              AND d.owner_id = NULLIF(current_setting('app.current_user_id', true), '')
        )
    );

COMMIT;
