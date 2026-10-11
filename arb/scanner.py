"""One scan: pull odds for every in-season sport, detect arbs, log them."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time

from . import db, demo
from .config import Settings
from .detector import scan_events
from .odds_client import OddsClient

log = logging.getLogger(__name__)


def _sports_to_scan(client: OddsClient, settings: Settings) -> list[str]:
    if settings.sports:
        return settings.sports
    # Outright/futures markets (e.g. "who wins the Super Bowl") don't have
    # h2h/spreads/totals, so skip them.
    return [s["key"] for s in client.sports() if s.get("active") and not s.get("has_outrights")]


def run_scan(settings: Settings, conn: sqlite3.Connection, client: OddsClient | None = None) -> int:
    scan_id = db.start_scan(conn)
    events: list[dict] = []
    sports: list[str] = []
    error = None
    try:
        if settings.demo:
            events = demo.events()
            sports = sorted({e["sport_key"] for e in events})
        else:
            assert client is not None
            sports = _sports_to_scan(client, settings)
            for sport in sports:
                try:
                    events.extend(client.odds(sport, markets=settings.markets, bookmakers=settings.sources))
                except Exception as exc:  # one bad sport shouldn't kill the sweep
                    log.warning("odds fetch failed for %s: %s", sport, exc)
                    error = f"{sport}: {exc}"
    except Exception as exc:
        log.exception("scan failed")
        error = str(exc)

    opps = scan_events(
        events,
        max_margin=settings.max_margin,
        min_margin=settings.min_margin,
        max_odds_age=settings.max_odds_age_seconds,
        fees=settings.exchange_fees,
    )
    db.record_scan(conn, opps, scanned_event_ids={e["id"] for e in events})
    quota = client.quota if client else None
    db.finish_scan(
        conn,
        scan_id,
        sports_scanned=len(sports),
        events_scanned=len(events),
        arbs_found=len(opps),
        credits_remaining=quota.remaining if quota else None,
        credits_used=quota.used if quota else None,
        error=error,
    )
    log.info("scan %s: %d sports, %d events, %d arbs", scan_id, len(sports), len(events), len(opps))
    return len(opps)


def run_forever(settings: Settings, conn: sqlite3.Connection, stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    client = None if settings.demo else OddsClient(settings.api_key)
    try:
        while not stop.is_set():
            run_scan(settings, conn, client)
            stop.wait(settings.poll_seconds)
    finally:
        if client:
            client.close()


def main() -> None:
    from .config import load_settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    conn = db.connect(settings.db_path)
    run_forever(settings, conn)


if __name__ == "__main__":
    main()
