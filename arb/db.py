"""SQLite log of every opportunity seen, so we learn how often arbs appear and how long they last."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .detector import Leg, Opportunity

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    key TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    sport_key TEXT,
    sport_title TEXT,
    home_team TEXT,
    away_team TEXT,
    commence_time TEXT,
    market TEXT,
    line TEXT,
    legs TEXT NOT NULL,
    margin REAL NOT NULL,
    best_margin REAL NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_opps_active ON opportunities(active, margin DESC);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    sports_scanned INTEGER,
    events_scanned INTEGER,
    arbs_found INTEGER,
    credits_remaining INTEGER,
    credits_used INTEGER,
    error TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def record_scan(conn: sqlite3.Connection, opps: list[Opportunity], *, scanned_event_ids: set[str]) -> None:
    """Upsert current opportunities and close ones that disappeared from scanned events."""
    ts = now_iso()
    seen = set()
    for o in opps:
        seen.add(o.key)
        legs = json.dumps([leg.__dict__ for leg in o.legs])
        conn.execute(
            """
            INSERT INTO opportunities (key, event_id, sport_key, sport_title, home_team, away_team,
                commence_time, market, line, legs, margin, best_margin, first_seen, last_seen, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(key) DO UPDATE SET
                legs = excluded.legs,
                margin = excluded.margin,
                best_margin = MAX(opportunities.best_margin, excluded.margin),
                last_seen = excluded.last_seen,
                first_seen = CASE WHEN opportunities.active = 1 THEN opportunities.first_seen ELSE excluded.first_seen END,
                active = 1
            """,
            (o.key, o.event_id, o.sport_key, o.sport_title, o.home_team, o.away_team,
             o.commence_time, o.market, o.line, legs, o.margin, o.margin, ts, ts),
        )
    # Anything still active for an event we just re-scanned, but not found this time, is gone.
    for row in conn.execute("SELECT key, event_id FROM opportunities WHERE active = 1").fetchall():
        if row["key"] not in seen and row["event_id"] in scanned_event_ids:
            conn.execute("UPDATE opportunities SET active = 0 WHERE key = ?", (row["key"],))
    # Games that have started are no longer bettable pre-match.
    conn.execute("UPDATE opportunities SET active = 0 WHERE active = 1 AND commence_time <= ?", (ts,))
    conn.commit()


def start_scan(conn: sqlite3.Connection) -> int:
    cur = conn.execute("INSERT INTO scans (started_at) VALUES (?)", (now_iso(),))
    conn.commit()
    return cur.lastrowid


def finish_scan(conn: sqlite3.Connection, scan_id: int, **fields) -> None:
    fields["finished_at"] = now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE scans SET {cols} WHERE id = ?", (*fields.values(), scan_id))
    conn.commit()


def row_to_opportunity(row: sqlite3.Row) -> Opportunity:
    return Opportunity(
        event_id=row["event_id"],
        sport_key=row["sport_key"],
        sport_title=row["sport_title"],
        home_team=row["home_team"],
        away_team=row["away_team"],
        commence_time=row["commence_time"],
        market=row["market"],
        line=row["line"],
        legs=[Leg(**leg) for leg in json.loads(row["legs"])],
    )


def active(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM opportunities WHERE active = 1 ORDER BY margin DESC").fetchall()


def history(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM opportunities WHERE active = 0 ORDER BY last_seen DESC LIMIT ?", (limit,)
    ).fetchall()


def stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """
        SELECT COUNT(*) AS total, AVG(best_margin) AS avg_margin, MAX(best_margin) AS max_margin,
               AVG((julianday(last_seen) - julianday(first_seen)) * 86400) AS avg_lifetime_s
        FROM opportunities
        """
    ).fetchone()
    last_scan = conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    return {**dict(row), "last_scan": dict(last_scan) if last_scan else None}
