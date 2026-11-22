from __future__ import annotations

import sqlite3
from pathlib import Path

import click
from flask import current_app, g


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    line_name TEXT NOT NULL,
    line_key TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL DEFAULT '',
    department TEXT NOT NULL DEFAULT '',
    student_id TEXT NOT NULL DEFAULT '',
    grade INTEGER,
    experience REAL NOT NULL DEFAULT 0,
    birthplace TEXT NOT NULL DEFAULT '',
    birthday TEXT NOT NULL DEFAULT '',
    gender TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    source_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    event_name TEXT NOT NULL DEFAULT '',
    member_ids_json TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    teams_json TEXT NOT NULL,
    output_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS formations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name TEXT NOT NULL DEFAULT '',
    settings_json TEXT NOT NULL,
    teams_json TEXT NOT NULL,
    output_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS formation_pairs (
    formation_id INTEGER NOT NULL REFERENCES formations(id) ON DELETE CASCADE,
    member_a INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    member_b INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    CHECK (member_a < member_b),
    UNIQUE (formation_id, member_a, member_b)
);

CREATE INDEX IF NOT EXISTS idx_members_line_key ON members(line_key);
CREATE INDEX IF NOT EXISTS idx_pairs_members ON formation_pairs(member_a, member_b);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        database = Path(current_app.config["DATABASE"])
        database.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(database)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db() -> None:
    connection = get_db()
    connection.executescript(SCHEMA)
    connection.commit()


@click.command("init-db")
def init_db_command() -> None:
    init_db()
    click.echo("データベースを初期化しました。")


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
