-- Run ONCE by a PostgreSQL superuser before the first migration.
--
-- Creates the Trader's roles and the limited analysis role (ADR-021).
-- Passwords are NOT in this file: set them with `ALTER ROLE ... PASSWORD`
-- from a secret, never from a committed script.
--
--   trader_owner    runs migrations, owns the objects in schema "trading"
--   trader_rw       the running Trader (see the grants in migration 0001..0007)
--   trader_monitor  read-only on the heartbeat, for the host liveness script (ADR-039)
--   aidss_app       the analysis API and worker; owns objects in schema "public"
--                   and has NO access to schema "trading" (ADR-021)

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trader_owner') THEN
    CREATE ROLE trader_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trader_rw') THEN
    CREATE ROLE trader_rw LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trader_monitor') THEN
    CREATE ROLE trader_monitor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aidss_app') THEN
    CREATE ROLE aidss_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;

-- trader_owner needs to create the schema and objects in the target database.
-- Replace <database> with the database name (the analysis stack uses "aidss").
GRANT CREATE ON DATABASE <database> TO trader_owner;
GRANT CONNECT, TEMPORARY ON DATABASE <database> TO aidss_app, trader_rw, trader_monitor;

-- The Trader's roles must not write outside schema "trading". Nothing is granted on
-- "public"; revoke the default so that stays true.
REVOKE ALL ON SCHEMA public FROM trader_rw, trader_monitor;

-- The analysis platform role works in schema "public" only; see
-- deploy/trader/isolate_analysis_role.sql for migrating an existing database
-- where "public" objects are currently owned by the bootstrap superuser.
GRANT USAGE, CREATE ON SCHEMA public TO aidss_app;
