-- Run once by a PostgreSQL superuser, after migration 0011, to give the crypto signal worker its
-- own least-privilege role. Replace the password placeholder with a random value and keep it only
-- in the worker's environment file. Safe to run again: it re-applies the same grants.
--
--   psql -v ON_ERROR_STOP=1 -v pw="'<random>'" -f grant_signals_role.sql
--
-- The role can read the worker's settings, add scans, scored coins and acknowledgements, and update
-- a scan it started. It cannot see an order, a credential, a limit or any other Trader table.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'signals_rw') THEN
    CREATE ROLE signals_rw LOGIN;
  END IF;
END $$;
ALTER ROLE signals_rw PASSWORD :pw;
GRANT CONNECT ON DATABASE aidss TO signals_rw;
GRANT USAGE ON SCHEMA trading TO signals_rw;
GRANT SELECT ON trading.signal_config TO signals_rw;
GRANT SELECT, INSERT, UPDATE ON trading.signal_scan TO signals_rw;
GRANT SELECT, INSERT ON trading.signal_candidate TO signals_rw;
GRANT SELECT, INSERT ON trading.signal_ack TO signals_rw;
