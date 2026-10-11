"""Runtime settings, read from environment variables (or a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Sportsbooks licensed in New York State that The Odds API covers.
# Keys come from https://the-odds-api.com/sports-odds-data/bookmaker-apis.html
NY_BOOKMAKERS = [
    "draftkings",
    "fanduel",
    "betmgm",
    "williamhill_us",  # Caesars
    "betrivers",
    "fanatics",
    "espnbet",  # theScore Bet
    "ballybet",
]

# Prediction-market exchanges (The Odds API "us_ex" region). Their legal status
# for New York residents is being litigated, so they can be switched off with
# EXCHANGES= (empty).
EXCHANGES = ["kalshi", "polymarket"]

# Taker fee coefficient per exchange: fee per contract = coef * p * (1 - p),
# where p is the contract price in dollars. Sources: Kalshi and Polymarket US
# published fee schedules (2026). Prices are adjusted by this before arb math.
EXCHANGE_FEES = {"kalshi": 0.07, "polymarket": 0.0695}

DEFAULT_MARKETS = ["h2h", "spreads", "totals"]


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Settings:
    api_key: str = ""
    bookmakers: list[str] = field(default_factory=lambda: list(NY_BOOKMAKERS))
    exchanges: list[str] = field(default_factory=lambda: list(EXCHANGES))
    exchange_fees: dict[str, float] = field(default_factory=lambda: dict(EXCHANGE_FEES))
    markets: list[str] = field(default_factory=lambda: list(DEFAULT_MARKETS))
    # Empty means every in-season sport the API lists.
    sports: list[str] = field(default_factory=list)
    poll_seconds: int = 300
    # Margins above this are almost always stale lines or palpable errors.
    max_margin: float = 0.10
    min_margin: float = 0.0
    # Ignore a book's price if it was last updated more than this many seconds ago.
    max_odds_age_seconds: int = 600
    bankroll: float = 1000.0
    stake_rounding: float = 1.0
    db_path: str = "arb.db"
    demo: bool = False

    @property
    def sources(self) -> list[str]:
        """Every book and exchange to request odds from."""
        return list(dict.fromkeys(self.bookmakers + self.exchanges))

    @property
    def credits_per_sport(self) -> int:
        regions = max(1, -(-len(self.sources) // 10))
        return len(self.markets) * regions


def load_settings() -> Settings:
    _load_dotenv()
    env = os.environ
    return Settings(
        api_key=env.get("ODDS_API_KEY", ""),
        bookmakers=_list("BOOKMAKERS", NY_BOOKMAKERS),
        exchanges=_list("EXCHANGES", EXCHANGES) if "EXCHANGES" not in env or env["EXCHANGES"] else [],
        markets=_list("MARKETS", DEFAULT_MARKETS),
        sports=_list("SPORTS", []),
        poll_seconds=int(env.get("POLL_SECONDS", 300)),
        max_margin=float(env.get("MAX_MARGIN", 0.10)),
        min_margin=float(env.get("MIN_MARGIN", 0.0)),
        max_odds_age_seconds=int(env.get("MAX_ODDS_AGE_SECONDS", 600)),
        bankroll=float(env.get("BANKROLL", 1000)),
        stake_rounding=float(env.get("STAKE_ROUNDING", 1)),
        db_path=env.get("DB_PATH", "arb.db"),
        demo=env.get("DEMO", "").lower() in {"1", "true", "yes"},
    )
