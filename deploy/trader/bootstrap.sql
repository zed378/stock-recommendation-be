-- Run ONCE by a PostgreSQL superuser before the first migration.
--
-- Creates the Trader's roles. Passwords are NOT in this file: set them with
-- `ALTER ROLE ... PASSWORD` from a secret, never from a committed script.
--
--   trader_owner    runs migrations, owns the objects in schema "trading"
--   trader_rw       the running Trader (see the grants in migration 0001)
--   trader_monitor  read-only on the heartbeat, for the host liveness script (ADR-039)

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trader_owner') THEN
    CREATE ROLE trader_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trader_rw') THEN
    CREATE ROLE trader_rw LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trader_monitor') THEN
    CREATE ROLE trader_monitor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END
$$;

-- trader_owner needs to create the schema and objects in the target database.
-- Replace <database> with the database name (the analysis stack uses "aidss").
GRANT CREATE ON DATABASE <database> TO trader_owner;

-- The Trader's roles must not write outside schema "trading". Nothing is granted on
-- "public"; revoke the default so that stays true.
REVOKE ALL ON SCHEMA public FROM trader_rw, trader_monitor;

-- IMPORTANT (see TASKS/BACKLOG.md): in the current deployment the analysis API
-- connects as the database's bootstrap superuser, which bypasses every grant. The
-- isolation of ADR-021 is only real once the analysis API uses a limited role.
