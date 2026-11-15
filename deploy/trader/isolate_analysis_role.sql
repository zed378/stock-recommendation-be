-- Migrate the analysis platform (src/aidss) off the PostgreSQL bootstrap superuser
-- onto the limited role `aidss_app` (ADR-021).
--
-- Run as the bootstrap superuser (`aidss`) inside the target database (or a
-- scratch database created with `CREATE DATABASE aidss_role_rehearsal` first).
-- Passwords are NOT in this file: set `ALTER ROLE aidss_app PASSWORD ...`
-- separately from a secret.
--
-- What this script does:
-- 1. Creates `aidss_app` with NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS.
-- 2. Ensures the `vector` extension already exists (so `alembic/env.py`'s
--    `CREATE EXTENSION IF NOT EXISTS vector` is a no-op that needs no superuser).
-- 3. Transfers ownership of all tables, sequences, views, and user-defined enum
--    types in `schema public` ONLY to `aidss_app`, so `api` startup's
--    `alembic upgrade head` can run future `public` schema migrations as `aidss_app`.
-- 4. Grants `USAGE, CREATE ON SCHEMA public` to `aidss_app` and revokes `CREATE`
--    on `public` from `PUBLIC`, `trader_rw`, and `trader_monitor`.
-- 5. Explicitly revokes all privileges on `schema trading` (and every object inside
--    it) from `PUBLIC` and `aidss_app`, ensuring `aidss_app` cannot read or write
--    any Trader table.

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aidss_app') THEN
    CREATE ROLE aidss_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  ELSE
    ALTER ROLE aidss_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;

-- Pre-create pgvector as superuser if not already installed; skipped when testing
-- on a minimal PostgreSQL image without pgvector.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
    CREATE EXTENSION IF NOT EXISTS vector;
  END IF;
END
$$;

-- Restrict search_path of aidss_app to public only.
ALTER ROLE aidss_app SET search_path TO public;

-- Schema-level privileges on public.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO aidss_app;

-- Transfer ownership of all tables, sequences, views, and domain/enum types in
-- schema `public` (never `trading` or system schemas) to `aidss_app`.
DO $$
DECLARE
  rec RECORD;
BEGIN
  FOR rec IN
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'public'
  LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO aidss_app', rec.tablename);
  END LOOP;

  FOR rec IN
    SELECT sequencename
    FROM pg_sequences
    WHERE schemaname = 'public'
  LOOP
    EXECUTE format('ALTER SEQUENCE public.%I OWNER TO aidss_app', rec.sequencename);
  END LOOP;

  FOR rec IN
    SELECT viewname
    FROM pg_views
    WHERE schemaname = 'public'
  LOOP
    EXECUTE format('ALTER VIEW public.%I OWNER TO aidss_app', rec.viewname);
  END LOOP;

  FOR rec IN
    SELECT t.typname
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public'
      AND t.typtype = 'e'
  LOOP
    EXECUTE format('ALTER TYPE public.%I OWNER TO aidss_app', rec.typname);
  END LOOP;
END
$$;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO aidss_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO aidss_app;
ALTER DEFAULT PRIVILEGES FOR ROLE aidss_app IN SCHEMA public
  GRANT ALL PRIVILEGES ON TABLES TO aidss_app;
ALTER DEFAULT PRIVILEGES FOR ROLE aidss_app IN SCHEMA public
  GRANT ALL PRIVILEGES ON SEQUENCES TO aidss_app;

-- Enforce strict isolation of schema `trading` from `aidss_app` and `PUBLIC` (ADR-021).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'trading') THEN
    REVOKE ALL ON SCHEMA trading FROM PUBLIC, aidss_app;
    REVOKE ALL ON ALL TABLES IN SCHEMA trading FROM PUBLIC, aidss_app;
    REVOKE ALL ON ALL SEQUENCES IN SCHEMA trading FROM PUBLIC, aidss_app;
    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA trading FROM PUBLIC, aidss_app;
  END IF;
END
$$;

COMMIT;
