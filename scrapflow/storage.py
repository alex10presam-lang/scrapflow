"""Execuções imutáveis. Uma transação publica o lote inteiro no histórico."""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


class RunStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                source TEXT NOT NULL, dataset TEXT NOT NULL)"""
            )

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def save(self, dataset, source):
        run_id = uuid4().hex
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?)",
                (
                    run_id,
                    datetime.now(timezone.utc).isoformat(),
                    source,
                    json.dumps(dataset, ensure_ascii=False),
                ),
            )
        return self.get(run_id)

    def get(self, run_id=None):
        with closing(self.connect()) as db:
            row = (
                db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
                if run_id
                else db.execute(
                    "SELECT * FROM runs ORDER BY created_at DESC, id DESC LIMIT 1"
                ).fetchone()
            )
        if row is None:
            return None
        return {**dict(row), "dataset": json.loads(row["dataset"])}

    def list(self):
        with closing(self.connect()) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id, created_at, source FROM runs ORDER BY created_at DESC, id DESC LIMIT 100"
                )
            ]


class AutomationStore:
    """Apenas um trabalho ativo e publicação do lote na mesma transação do resultado."""

    def __init__(self, runs):
        self.runs = runs
        with closing(runs.connect()) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS automation_jobs (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
                day_key TEXT UNIQUE, owner_pid INTEGER NOT NULL, state TEXT NOT NULL)"""
            )
            db.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS one_active_bot_job
                ON automation_jobs(status) WHERE status = 'running'"""
            )

    def start(self, job, day_key, owner_pid):
        with closing(self.runs.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = (
                db.execute(
                    "SELECT state, day_key FROM automation_jobs WHERE day_key = ?", (day_key,)
                ).fetchone()
                if day_key
                else None
            )
            if row is None:
                row = db.execute(
                    "SELECT state, day_key FROM automation_jobs WHERE status = 'running'"
                ).fetchone()
            if row:
                existing = json.loads(row["state"])
                if day_key and row["day_key"] is None:
                    # Um disparo agendado que reutiliza um trabalho manual também consome a chave diária.
                    db.execute(
                        "UPDATE automation_jobs SET day_key = ? WHERE id = ?",
                        (day_key, existing["id"]),
                    )
                return existing, False
            db.execute(
                "INSERT INTO automation_jobs VALUES (?, ?, ?, ?, ?, ?)",
                (
                    job["id"],
                    job["status"],
                    job["created_at"],
                    day_key,
                    owner_pid,
                    json.dumps(job, ensure_ascii=False),
                ),
            )
        return job, True

    def get(self, job_id):
        with closing(self.runs.connect()) as db:
            row = db.execute("SELECT state FROM automation_jobs WHERE id = ?", (job_id,)).fetchone()
        return json.loads(row["state"]) if row else None

    def list(self):
        with closing(self.runs.connect()) as db:
            return [
                json.loads(row["state"])
                for row in db.execute(
                    "SELECT state FROM automation_jobs ORDER BY created_at DESC, id DESC LIMIT 30"
                )
            ]

    def patch(self, job_id, **patch):
        with closing(self.runs.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM automation_jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            state = json.loads(row["state"])
            if state["status"] != "running" and set(patch) != {"warnings"}:
                return state
            # Mesclar as origens na transação evita perder atualizações dos bots paralelos.
            sources = patch.pop("sources", None)
            if sources:
                state["sources"].update(sources)
            state.update(patch)
            db.execute(
                "UPDATE automation_jobs SET status = ?, state = ? WHERE id = ?",
                (state["status"], json.dumps(state, ensure_ascii=False), job_id),
            )
        return state

    def publish(self, job_id, dataset, final):
        with closing(self.runs.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM automation_jobs WHERE id = ?", (job_id,)).fetchone()
            state = json.loads(row["state"])
            if state["status"] == "done":
                return state
            if state["status"] != "running":
                raise ValueError("Trabalho interrompido; publicação bloqueada.")
            state.update(final, status="done", phase="done", run_id=job_id)
            db.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?)",
                (
                    job_id,
                    datetime.fromisoformat(state["finished_at"])
                    .astimezone(timezone.utc)
                    .isoformat(),
                    "bots",
                    json.dumps(dataset, ensure_ascii=False),
                ),
            )
            db.execute(
                "UPDATE automation_jobs SET status = 'done', state = ? WHERE id = ?",
                (json.dumps(state, ensure_ascii=False), job_id),
            )
        return state

    def recover(self, alive):
        """Não interrompe outro processo vivo que esteja usando o mesmo banco."""
        with closing(self.runs.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute(
                "SELECT id, owner_pid, state FROM automation_jobs WHERE status = 'running'"
            ).fetchall():
                if alive(row["owner_pid"]):
                    continue
                state = json.loads(row["state"])
                state.update(
                    status="interrupted",
                    phase="interrupted",
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    error="A aplicação foi encerrada durante a execução. Inicie um novo trabalho.",
                )
                db.execute(
                    "UPDATE automation_jobs SET status = 'interrupted', state = ? WHERE id = ?",
                    (json.dumps(state, ensure_ascii=False), row["id"]),
                )
