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
