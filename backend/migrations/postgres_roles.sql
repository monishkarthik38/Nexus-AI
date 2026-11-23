-- Run once as a PostgreSQL administrator in the target application database.
-- Set each role password out of band (for example with psql's \password).
DO $$
BEGIN
    CREATE ROLE nexus_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
    CREATE ROLE nexus_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
    CREATE ROLE nexus_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO nexus_migrator', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO nexus_runtime', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO nexus_worker', current_database());
END;
$$;
GRANT USAGE, CREATE ON SCHEMA public TO nexus_migrator;
GRANT USAGE ON SCHEMA public TO nexus_runtime;
GRANT USAGE ON SCHEMA public TO nexus_worker;
ALTER DEFAULT PRIVILEGES FOR ROLE nexus_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nexus_runtime;
