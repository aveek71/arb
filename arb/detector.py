"""Find arbitrage opportunities in The Odds API event payloads (decimal odds)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from .stakes import fee_adjusted_price, implied_sum


@dataclass
class Leg:
    outcome: str
    point: float | None
    book: str
    book_title: str
    price: float  # effective decimal odds, after any exchange fee
    raw_price: float | None = None  # listed decimal odds before fees (exchanges only)

    @property
    def is_exchange(self) -> bool:
        return self.raw_price is not None

    @property
    def contract_cents(self) -> float | None:
        """Exchange contract price in cents, before fees."""
        return 100 / self.raw_price if self.raw_price else None

    def contracts_for(self, stake: float) -> int:
        """Whole $1-payout contracts a stake buys, fees included."""
        return int(stake * self.price + 1e-9)

    @property
    def label(self) -> str:
        if self.point is None:
            return self.outcome
        sign = "+" if self.point > 0 and self.outcome not in ("Over", "Under") else ""
        return f"{self.outcome} {sign}{self.point:g}"


@dataclass
class Opportunity:
    event_id: str
    sport_key: str
    sport_title: str
    home_team: str
    away_team: str
    commence_time: str
    market: str
    line: str
    legs: list[Leg] = field(default_factory=list)

    @property
    def implied_sum(self) -> float:
        return implied_sum([leg.price for leg in self.legs])

    @property
    def margin(self) -> float:
        return 1 / self.implied_sum - 1

    @property
    def key(self) -> str:
        raw = f"{self.event_id}|{self.market}|{self.line}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    @property
    def matchup(self) -> str:
        return f"{self.away_team} @ {self.home_team}"


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_fresh(stamp: str | None, now: datetime, max_age: int | None) -> bool:
    if max_age is None:
        return True
    ts = _parse_time(stamp)
    return ts is None or (now - ts).total_seconds() <= max_age


def _best(candidates: dict[Any, list[Leg]]) -> dict[Any, Leg]:
    return {k: max(legs, key=lambda leg: leg.price) for k, legs in candidates.items()}


def find_arbs(
    event: dict,
    *,
    max_margin: float = 0.10,
    min_margin: float = 0.0,
    max_odds_age: int | None = None,
    now: datetime | None = None,
    fees: dict[str, float] | None = None,
) -> list[Opportunity]:
    """Return every market/line in `event` where the best prices across books arb."""
    now = now or datetime.now(timezone.utc)
    commence = _parse_time(event.get("commence_time"))
    if commence and commence <= now:
        # Live in-play odds move too fast for a polled feed; skip started games.
        return []

    home = event.get("home_team", "")
    fees = fees or {}
    # market -> line key -> outcome slot -> candidate legs
    groups: dict[str, dict[Any, dict[Any, list[Leg]]]] = {}

    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            mkey = market["key"]
            stamp = market.get("last_update") or book.get("last_update")
            if not _is_fresh(stamp, now, max_odds_age):
                continue
            outcomes = market.get("outcomes", [])
            if mkey == "h2h":
                # Group by the set of outcome names so 2-way and 3-way books never mix.
                line_key = tuple(sorted(o["name"] for o in outcomes))
            for o in outcomes:
                point = o.get("point")
                listed = float(o["price"])
                if listed <= 1:
                    continue
                coef = fees.get(book["key"])
                leg = Leg(
                    o["name"], point, book["key"], book.get("title", book["key"]),
                    price=fee_adjusted_price(listed, coef) if coef is not None else listed,
                    raw_price=listed if coef is not None else None,
                )
                if mkey == "h2h":
                    slot = o["name"]
                elif mkey == "spreads" and point is not None:
                    # Home -3.5 pairs with away +3.5: key on the home team's handicap.
                    line_key = point if o["name"] == home else -point
                    slot = "home" if o["name"] == home else "away"
                elif mkey == "totals" and point is not None:
                    line_key = point
                    slot = o["name"]
                else:
                    continue
                groups.setdefault(mkey, {}).setdefault(line_key, {}).setdefault(slot, []).append(leg)

    opportunities = []
    for mkey, lines in groups.items():
        for line_key, slots in lines.items():
            expected = len(line_key) if mkey == "h2h" else 2
            if len(slots) != expected:
                continue
            best = _best(slots)
            legs = [best[s] for s in sorted(best, key=str)]
            if len({leg.book for leg in legs}) < 2:
                continue  # one book can't arb itself; that's a pricing error
            s = implied_sum([leg.price for leg in legs])
            m = 1 / s - 1
            if s >= 1 or m <= min_margin or m > max_margin:
                continue
            if mkey == "h2h":
                line = "moneyline"
            elif mkey == "spreads":
                line = f"{home} {line_key:+g}"
            else:
                line = f"total {line_key:g}"
            opportunities.append(
                Opportunity(
                    event_id=event["id"],
                    sport_key=event.get("sport_key", ""),
                    sport_title=event.get("sport_title", event.get("sport_key", "")),
                    home_team=home,
                    away_team=event.get("away_team", ""),
                    commence_time=event.get("commence_time", ""),
                    market=mkey,
                    line=line,
                    legs=legs,
                )
            )
    return opportunities


def scan_events(events: Iterable[dict], **kwargs) -> list[Opportunity]:
    found: list[Opportunity] = []
    for event in events:
        found.extend(find_arbs(event, **kwargs))
    return sorted(found, key=lambda o: o.margin, reverse=True)
