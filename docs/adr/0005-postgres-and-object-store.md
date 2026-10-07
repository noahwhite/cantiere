# ADR-0005: Postgres is the only database; blobs go to S3-compatible storage

- Status: Accepted
- Date: 2026-10-07
- Requirements: OBS-1, OBS-3, UX-5, SEC-5, OSS-2, OSS-6

## Context

The control plane must survive restarts without losing session state (OBS-1), keep a replayable timeline (UX-5) and an append-only audit log (SEC-5), and install with one command (OSS-2).
Every extra stateful service (message broker, workflow server, search engine) is one more thing a self-hoster backs up and upgrades.

## Decision

- **PostgreSQL 17 or later** holds all control-plane state: sessions, workers, installations, personas, workflow state (ADR-0006), timeline events, audit log, and spend.
- **S3-compatible object storage** holds large or binary data: raw runtime transcripts, terminal recordings, screenshots, evidence, and exported timelines, with retention per bucket prefix (OBS-3). Cloudflare R2 for Officina; MinIO or the local filesystem provider for a single-host install.
- **Timeline** events are rows in a time-partitioned `session_events` table keyed by `(tenant_id, session_id, seq)`; payloads over 64 KiB are stored in the object store and referenced by key.
- **Tenancy (OSS-6):** every table carries `tenant_id NOT NULL`, every primary and foreign key includes it, and every query is scoped through one repository layer; Phase 1 runs a single fixed tenant. Row-level security is not enabled now. The workflow engine's own system tables are the one exception (ADR-0006).
- **Migrations** are forward-only, numbered SQL files applied by the server at startup under an advisory lock, following expand/contract for destructive changes.
- **Live fan-out** to browsers uses Postgres `LISTEN/NOTIFY` as a wake-up signal plus reads from `session_events`, so no separate broker is needed.

## Consequences

- Backup and restore covers the Cantiere database and OpenBao's database (two `pg_dump`s, ADR-0010), the cluster's roles and grants (`pg_dumpall --globals-only`, since `pg_dump` omits them), the bucket, and OpenBao's unseal key stored separately (ADR-0019). The backup dumps Cantiere first and OpenBao second, but the two dumps and the bucket copy are separate points in time, so they are not mutually consistent. Secret deletion is a KV v2 soft delete, which keeps the version's data but hides it from normal reads until it is undeleted, and Cantiere destroys secret versions only after the backup retention period; Cantiere's mounts set `max_versions` high enough that the version limit does not remove a version first. A reference in the Cantiere dump whose latest version was soft-deleted is therefore recoverable: the restore undeletes that version and lists it for the operator. Only a destroyed version is unrecoverable. A restore loads roles, then OpenBao, then Cantiere, and reports every secret reference that does not resolve and every object key the database names that the bucket lacks; on a self-hosted install with MinIO, that bucket is the MinIO volume, which is a second durable store to back up.
- Event volume is bounded by partitioning and offloading large payloads; if a deployment outgrows it, the timeline store is behind an interface and can move.
- Full-text search across sessions (KN-2, Phase 3) starts with Postgres full-text search and can add a dedicated index later.

## Alternatives considered

- **SQLite:** simplest single-host option, but no `LISTEN/NOTIFY`, weak concurrent writers, and a migration later when the control plane is hosted (OSS-6).
- **Postgres plus NATS or Redis:** adds a stateful service for fan-out Postgres already covers at this scale.
