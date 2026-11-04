-- DANGER: deletes EVERYTHING in your public schema (all app tables and data). Only for wiping an old project
-- before running full_setup.sql. Users in Authentication are not deleted.
drop schema if exists public cascade;
create schema public;
grant usage on schema public to postgres, anon, authenticated, service_role;
grant all on schema public to postgres, service_role;
alter default privileges in schema public grant all on tables to postgres, service_role;
alter default privileges in schema public grant all on sequences to postgres, service_role;
alter default privileges in schema public grant all on functions to postgres, service_role;
