-- Rollback script for deploy/trader/isolate_analysis_role.sql.
--
-- Returns ownership of `public` schema objects back to the bootstrap superuser
-- (`aidss`) so the analysis stack can fall back to its original superuser
-- connection URL if needed. Does NOT touch schema `trading`.

BEGIN;

DO $$
DECLARE
  rec RECORD;
BEGIN
  FOR rec IN
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'public'
  LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO aidss', rec.tablename);
  END LOOP;

  FOR rec IN
    SELECT sequencename
    FROM pg_sequences
    WHERE schemaname = 'public'
  LOOP
    EXECUTE format('ALTER SEQUENCE public.%I OWNER TO aidss', rec.sequencename);
  END LOOP;

  FOR rec IN
    SELECT viewname
    FROM pg_views
    WHERE schemaname = 'public'
  LOOP
    EXECUTE format('ALTER VIEW public.%I OWNER TO aidss', rec.viewname);
  END LOOP;

  FOR rec IN
    SELECT t.typname
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public'
      AND t.typtype = 'e'
  LOOP
    EXECUTE format('ALTER TYPE public.%I OWNER TO aidss', rec.typname);
  END LOOP;
END
$$;

COMMIT;
