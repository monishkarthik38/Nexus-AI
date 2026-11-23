-- Run after `alembic upgrade head` as a PostgreSQL administrator.
GRANT SELECT, INSERT, UPDATE, DELETE ON
    documents,
    document_chunks,
    conversations,
    messages,
    research_reports,
    evaluation_runs,
    evidence_annotations,
    ingestion_jobs
TO nexus_runtime;
GRANT SELECT ON alembic_version TO nexus_runtime;
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM nexus_runtime;

GRANT SELECT, UPDATE ON documents TO nexus_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON document_chunks TO nexus_worker;
GRANT SELECT, UPDATE ON ingestion_jobs TO nexus_worker;
GRANT SELECT ON alembic_version TO nexus_worker;
