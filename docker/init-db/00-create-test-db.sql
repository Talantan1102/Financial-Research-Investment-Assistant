-- Roadmap #2.5: separate test database for backend pytest e2e PG fixture.
-- Tables in this DB are managed by SQLAlchemy Base.metadata.create_all()
-- at app_main lifespan startup, NOT by the legacy 01-init.sql in this dir.
--
-- File ordering: `00-` runs before `01-init.sql` per postgres-entrypoint
-- alphabetical order, but order doesn't matter here (CREATE DATABASE is
-- cross-db). The `00-` prefix is purely semantic — first thing: prepare test db.
--
-- See: docs/superpowers/specs/2026-05-07-v0.9.x-pg-and-ci-setup.md § 决策 3
CREATE DATABASE industry_assistant_test;
