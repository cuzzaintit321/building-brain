"""SQLite schema and SQL utilities. A separate DB per deployment; property scoping per query."""
from __future__ import annotations
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(os.environ.get('DATA_DIR', './appdata'))

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS properties (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS buildings (
 id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
 name TEXT NOT NULL, template_id INTEGER REFERENCES buildings(id) ON DELETE SET NULL,
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 UNIQUE(property_id, name)
);
CREATE TABLE IF NOT EXISTS documents (
 id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
 building_id INTEGER REFERENCES buildings(id) ON DELETE CASCADE,
 filename TEXT NOT NULL, kind TEXT NOT NULL, sha256 TEXT NOT NULL,
 size_bytes INTEGER NOT NULL, pages INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 UNIQUE(property_id, building_id, sha256)
);
CREATE TABLE IF NOT EXISTS assets (
 id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
 building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
 name TEXT NOT NULL, system TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '',
 model TEXT NOT NULL DEFAULT '', serial TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '', warranty_until TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS field_notes (
 id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
 building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
 title TEXT NOT NULL, body TEXT NOT NULL, author TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS exceptions (
 id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
 building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
 label TEXT NOT NULL, details TEXT NOT NULL, author TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
 created_at TEXT NOT NULL DEFAULT (datetime('now')), reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
 id INTEGER PRIMARY KEY,
 property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
 building_id INTEGER REFERENCES buildings(id) ON DELETE CASCADE,
 document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
 asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
 note_id INTEGER REFERENCES field_notes(id) ON DELETE CASCADE,
 exception_id INTEGER REFERENCES exceptions(id) ON DELETE CASCADE,
 source_type TEXT NOT NULL,
 page_number INTEGER, chunk_index INTEGER NOT NULL DEFAULT 0,
 body TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(body, content='chunks', content_rowid='id', tokenize='unicode61');
CREATE TRIGGER IF NOT EXISTS chunks_after_insert AFTER INSERT ON chunks BEGIN
 INSERT INTO chunk_fts(rowid,body) VALUES(new.id,new.body);
END;
CREATE TRIGGER IF NOT EXISTS chunks_after_delete AFTER DELETE ON chunks BEGIN
 INSERT INTO chunk_fts(chunk_fts,rowid,body) VALUES('delete',old.id,old.body);
END;
CREATE TRIGGER IF NOT EXISTS chunks_after_update AFTER UPDATE ON chunks BEGIN
 INSERT INTO chunk_fts(chunk_fts,rowid,body) VALUES('delete',old.id,old.body);
 INSERT INTO chunk_fts(rowid,body) VALUES(new.id,new.body);
END;
CREATE INDEX IF NOT EXISTS idx_chunks_scope ON chunks(property_id,building_id);
CREATE INDEX IF NOT EXISTS idx_docs_scope ON documents(property_id,building_id);
"""

def database_path() -> Path:
    path = Path(os.environ.get('DATA_DIR', str(DATA_DIR)))
    path.mkdir(parents=True, exist_ok=True)
    return path / 'building_brain.sqlite3'

def connect() -> sqlite3.Connection:
    con = sqlite3.connect(database_path(), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=15000')
    return con

def initialize() -> None:
    with connect() as con:
        con.executescript(SCHEMA)

@contextmanager
def db():
    con = connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def one(con, sql: str, params=()):
    return con.execute(sql, params).fetchone()

def rowdict(row):
    return dict(row) if row is not None else None

def ensure_property(con, property_id):
    row = one(con, 'SELECT * FROM properties WHERE id=?',(property_id,))
    if row is None:
        raise LookupError('Property not found')
    return row

def ensure_building(con, property_id, building_id):
    row = one(con, 'SELECT * FROM buildings WHERE id=? AND property_id=?',(building_id,property_id))
    if row is None:
        raise LookupError('Building not found within this property')
    return row

def remove_chunks(con, **source):
    assert len(source)==1
    key,value=next(iter(source.items()))
    if key not in {'document_id','asset_id','note_id','exception_id'}:
        raise ValueError('Unsupported source key')
    con.execute(f'DELETE FROM chunks WHERE {key}=?',(value,))
