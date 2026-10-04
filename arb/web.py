"""Web dashboard: live arbs with stake sizing, recent history and quota stats."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import db
from .config import load_settings
from .scanner import run_forever, run_scan
from .stakes import decimal_to_american, stake_plan

log = logging.getLogger(__name__)
settings = load_settings()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_stop = threading.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if settings.api_key or settings.demo:
        thread = threading.Thread(
            target=run_forever, args=(settings, db.connect(settings.db_path), _stop), daemon=True
        )
        thread.start()
    else:
        log.warning("No ODDS_API_KEY set and DEMO is off: dashboard will show stored data only")
    yield
    _stop.set()


app = FastAPI(title="Arb Finder", lifespan=lifespan)


def _ago(iso: str | None) -> str:
    if not iso:
        return "never"
    secs = (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds()
    if secs < 90:
        return f"{int(secs)}s ago"
    if secs < 5400:
        return f"{int(secs // 60)}m ago"
    return f"{secs / 3600:.1f}h ago"


def _view(row, bankroll: float) -> dict:
    opp = db.row_to_opportunity(row)
    plan = stake_plan([leg.price for leg in opp.legs], bankroll, settings.stake_rounding)
    return {
        "opp": opp,
        "margin": row["margin"],
        "best_margin": row["best_margin"],
        "first_seen": _ago(row["first_seen"]),
        "last_seen": _ago(row["last_seen"]),
        "commence": datetime.fromisoformat(opp.commence_time.replace("Z", "+00:00"))
        .astimezone(ZoneInfo("America/New_York"))
        .strftime("%a %b %d, %I:%M %p ET"),
        "legs": [
            {"leg": leg, "american": decimal_to_american(leg.price), "stake": st, "payout": pay}
            for leg, st, pay in zip(opp.legs, plan.stakes, plan.payouts)
        ],
        "plan": plan,
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, bankroll: float | None = None):
    bankroll = bankroll or settings.bankroll
    conn = db.connect(settings.db_path)
    try:
        live = [_view(r, bankroll) for r in db.active(conn)]
        past = [_view(r, bankroll) for r in db.history(conn, 50)]
        stats = db.stats(conn)
    finally:
        conn.close()
    last = stats.get("last_scan") or {}
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "live": live,
            "past": past,
            "stats": stats,
            "last_scan": last,
            "last_scan_ago": _ago(last.get("finished_at") or last.get("started_at")),
            "bankroll": bankroll,
            "settings": settings,
            "configured": bool(settings.api_key or settings.demo),
        },
    )


@app.post("/scan")
def scan_now():
    """Run one sweep immediately (costs API credits unless in demo mode)."""
    from .odds_client import OddsClient

    conn = db.connect(settings.db_path)
    client = None if settings.demo else OddsClient(settings.api_key)
    try:
        run_scan(settings, conn, client)
    finally:
        conn.close()
        if client:
            client.close()
    return RedirectResponse("/", status_code=303)


@app.get("/api/opportunities")
def api_opportunities(bankroll: float | None = None):
    bankroll = bankroll or settings.bankroll
    conn = db.connect(settings.db_path)
    try:
        out = []
        for row in db.active(conn):
            v = _view(row, bankroll)
            o = v["opp"]
            out.append({
                "key": o.key,
                "sport": o.sport_title,
                "matchup": o.matchup,
                "commence_time": o.commence_time,
                "market": o.market,
                "line": o.line,
                "margin": round(v["margin"], 5),
                "first_seen": row["first_seen"],
                "legs": [
                    {"outcome": x["leg"].label, "book": x["leg"].book_title, "price": x["leg"].price,
                     "american": x["american"], "stake": x["stake"]}
                    for x in v["legs"]
                ],
                "guaranteed_profit": round(v["plan"].min_profit, 2),
            })
        return out
    finally:
        conn.close()


def main() -> None:
    import os

    import uvicorn

    uvicorn.run("arb.web:app", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)))


if __name__ == "__main__":
    main()
