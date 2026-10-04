"""Synthetic odds so the dashboard can be tried without an API key (DEMO=1)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

BOOKS = [
    ("draftkings", "DraftKings"),
    ("fanduel", "FanDuel"),
    ("betmgm", "BetMGM"),
    ("williamhill_us", "Caesars"),
    ("betrivers", "BetRivers"),
    ("fanatics", "Fanatics"),
]

TOTALS = {"americanfootball_nfl": 44.5, "basketball_nba": 221.5, "icehockey_nhl": 6.5, "baseball_mlb": 8.5}

GAMES = [
    ("americanfootball_nfl", "NFL", "New York Giants", "Dallas Cowboys", False),
    ("americanfootball_nfl", "NFL", "Buffalo Bills", "Miami Dolphins", False),
    ("basketball_nba", "NBA", "New York Knicks", "Boston Celtics", False),
    ("icehockey_nhl", "NHL", "New York Rangers", "New Jersey Devils", False),
    ("baseball_mlb", "MLB", "New York Yankees", "Toronto Blue Jays", False),
    ("soccer_epl", "EPL", "Arsenal", "Chelsea", True),
]


def _price(fair_prob: float, vig: float, rng: random.Random) -> float:
    noisy = fair_prob * (1 + vig) * rng.uniform(0.95, 1.05)
    return round(1 / min(max(noisy, 0.02), 0.98), 2)


def events(seed: int | None = None) -> list[dict]:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    out = []
    for i, (sport_key, title, home, away, three_way) in enumerate(GAMES):
        p_home = rng.uniform(0.35, 0.65)
        books = []
        for key, name in BOOKS:
            vig = rng.uniform(0.03, 0.05)
            if three_way:
                p_draw = 0.25
                ph, pa = p_home * 0.75, (1 - p_home) * 0.75
                h2h = [(home, ph), (away, pa), ("Draw", p_draw)]
            else:
                h2h = [(home, p_home), (away, 1 - p_home)]
            markets = [{
                "key": "h2h",
                "last_update": stamp,
                "outcomes": [{"name": n, "price": _price(p, vig, rng)} for n, p in h2h],
            }]
            if not three_way:
                spread = -3.5 if p_home > 0.5 else 3.5
                markets.append({
                    "key": "spreads",
                    "last_update": stamp,
                    "outcomes": [
                        {"name": home, "price": _price(0.5, vig, rng), "point": spread},
                        {"name": away, "price": _price(0.5, vig, rng), "point": -spread},
                    ],
                })
                markets.append({
                    "key": "totals",
                    "last_update": stamp,
                    "outcomes": [
                        {"name": "Over", "price": _price(0.5, vig, rng), "point": TOTALS[sport_key]},
                        {"name": "Under", "price": _price(0.5, vig, rng), "point": TOTALS[sport_key]},
                    ],
                })
            books.append({"key": key, "title": name, "last_update": stamp, "markets": markets})
        commence = (now + timedelta(hours=3 + i * 5)).isoformat(timespec="seconds").replace("+00:00", "Z")
        out.append({
            "id": f"demo{i}",
            "sport_key": sport_key,
            "sport_title": title,
            "commence_time": commence,
            "home_team": home,
            "away_team": away,
            "bookmakers": books,
        })
    return out
