"""Persistência em SQLite: histórico, deduplicação e controle de notificações.

A chave primária é o `fingerprint` (título + empresa normalizados), então a
mesma vaga publicada em duas fontes vira um único registro, com as fontes
acumuladas na coluna `sources`.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from jobcrawler.models import Job

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    fingerprint   TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    company       TEXT NOT NULL,
    url           TEXT NOT NULL,
    source        TEXT NOT NULL,
    sources       TEXT NOT NULL,
    location      TEXT,
    regions       TEXT,
    timezone      TEXT,
    area          TEXT,
    junior_signal TEXT,
    note          TEXT,
    workplace     TEXT,
    profile       TEXT,
    source_level  TEXT,
    tags          TEXT,
    salary        TEXT,
    published_at  TEXT,
    description   TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    notified      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_notified ON jobs(notified);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    fetched     INTEGER,
    accepted    INTEGER,
    new_jobs    INTEGER,
    errors      TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            # Migração: bancos criados antes destas colunas existirem
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
            for column in ("note", "workplace", "profile"):
                if column not in columns:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
            if "profile" not in columns:
                # Antes dos perfis, o crawler só buscava vagas remotas.
                conn.execute("UPDATE jobs SET profile = 'remoto' WHERE profile IS NULL")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    def upsert(self, jobs: list[Job]) -> list[Job]:
        """Grava as vagas aceitas e devolve apenas as NOVAS (nunca vistas antes)."""
        new_jobs: list[Job] = []
        now = _now()
        with self._conn() as conn:
            for job in jobs:
                rec = job.to_record(excerpt_chars=2000)
                row = conn.execute("SELECT sources FROM jobs WHERE fingerprint = ?",
                                   (rec["fingerprint"],)).fetchone()
                if row:
                    sources = sorted(set(json.loads(row["sources"])) | {job.source})
                    conn.execute("UPDATE jobs SET last_seen = ?, sources = ? WHERE fingerprint = ?",
                                 (now, json.dumps(sources), rec["fingerprint"]))
                    continue
                conn.execute(
                    """INSERT INTO jobs (fingerprint, title, company, url, source, sources,
                           location, regions, timezone, area, junior_signal, note, workplace, profile, source_level,
                           tags, salary, published_at, description, first_seen, last_seen)
                       VALUES (:fingerprint, :title, :company, :url, :source, :sources,
                           :location, :regions, :timezone, :area, :junior_signal, :note, :workplace, :profile, :source_level,
                           :tags, :salary, :published_at, :description, :first_seen, :last_seen)""",
                    {**rec, "sources": json.dumps([job.source]), "first_seen": now, "last_seen": now},
                )
                new_jobs.append(job)
        return new_jobs

    def pending_notifications(self, limit: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE notified = 0 ORDER BY published_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    def mark_notified(self, fingerprints: list[str]) -> None:
        if not fingerprints:
            return
        with self._conn() as conn:
            conn.executemany("UPDATE jobs SET notified = 1 WHERE fingerprint = ?",
                             [(fp,) for fp in fingerprints])

    def recent(self, days: int = 7) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE first_seen >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?) "
                "ORDER BY published_at DESC", (f"-{int(days)} days",)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    def start_run(self) -> int:
        with self._conn() as conn:
            cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (_now(),))
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, fetched: int, accepted: int, new: int, errors: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET finished_at=?, fetched=?, accepted=?, new_jobs=?, errors=? WHERE id=?",
                (_now(), fetched, accepted, new, json.dumps(errors, ensure_ascii=False), run_id))
