import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

GENESIS_HASH = "0" * 64
DEFAULT_DB_PATH = Path(__file__).with_name("agentproof.db")


def _db_path():
    return Path(os.getenv("DB_PATH", str(DEFAULT_DB_PATH)))


def connect():
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with connect() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                ts REAL NOT NULL,
                purchase_id TEXT,
                event_type TEXT NOT NULL,
                data TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                hash TEXT NOT NULL
            )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS mandates (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                data_json TEXT NOT NULL,
                signature TEXT NOT NULL
            )"""
        )


def _event_hash(ts, purchase_id, event_type, data, prev_hash):
    content = json.dumps(
        {
            "ts": ts,
            "purchase_id": purchase_id,
            "event_type": event_type,
            "data": data,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def append_event(purchase_id, event_type, data):
    init_db()
    ts = time.time()
    data_json = json.dumps(data, sort_keys=True)
    with connect() as db:
        row = db.execute("SELECT hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = row["hash"] if row else GENESIS_HASH
        entry_hash = _event_hash(ts, purchase_id, event_type, data, prev_hash)
        cursor = db.execute(
            """INSERT INTO events
               (ts, purchase_id, event_type, data, prev_hash, hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ts, purchase_id, event_type, data_json, prev_hash, entry_hash),
        )
        return cursor.lastrowid


def get_log():
    init_db()
    with connect() as db:
        rows = db.execute("SELECT * FROM events ORDER BY id").fetchall()
    events = []
    for row in rows:
        event = dict(row)
        event["data"] = json.loads(event["data"])
        events.append(event)
    return events


def verify_chain():
    events = get_log()
    previous_hash = GENESIS_HASH
    for event in events:
        expected_hash = _event_hash(
            event["ts"],
            event["purchase_id"],
            event["event_type"],
            event["data"],
            previous_hash,
        )
        if event["prev_hash"] != previous_hash or event["hash"] != expected_hash:
            return False, event["id"]
        previous_hash = event["hash"]
    return True, None


def tamper_oldest_entry():
    with connect() as db:
        row = db.execute("SELECT id, data FROM events ORDER BY id LIMIT 1").fetchone()
        if row is None:
            raise ValueError("There are no audit entries to tamper with.")
        changed_data = json.dumps(
            {"tampered": True, "original": json.loads(row["data"])}, sort_keys=True
        )
        db.execute("UPDATE events SET data = ? WHERE id = ?", (changed_data, row["id"]))
    return {"tampered_entry_id": row["id"]}
