from datetime import datetime, timedelta, timezone

import pytest

from arb import db
from arb.detector import find_arbs, scan_events
from arb.stakes import american_to_decimal, decimal_to_american, margin, stake_plan

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
LATER = (NOW + timedelta(hours=5)).isoformat().replace("+00:00", "Z")
FRESH = (NOW - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")


def book(key, markets, stamp=FRESH):
    return {"key": key, "title": key.title(), "last_update": stamp,
            "markets": [{"key": k, "last_update": stamp, "outcomes": o} for k, o in markets.items()]}


def event(*books, commence=LATER):
    return {"id": "e1", "sport_key": "americanfootball_nfl", "sport_title": "NFL", "commence_time": commence,
            "home_team": "Giants", "away_team": "Cowboys", "bookmakers": list(books)}


# --- math ---------------------------------------------------------------

def test_odds_conversion():
    assert american_to_decimal(150) == pytest.approx(2.5)
    assert american_to_decimal(-120) == pytest.approx(1.8333, rel=1e-3)
    assert decimal_to_american(2.5) == 150
    assert decimal_to_american(1.8333) == -120


def test_margin_and_stakes_equalize_payout():
    prices = [2.10, 2.05]
    assert margin(prices) == pytest.approx(1 / (1 / 2.10 + 1 / 2.05) - 1)
    plan = stake_plan(prices, 1000, rounding=0)
    assert plan.total == pytest.approx(1000)
    assert plan.payouts[0] == pytest.approx(plan.payouts[1])
    assert plan.min_profit > 0


def test_rounding_reports_worst_case_profit():
    plan = stake_plan([2.10, 2.05], 1000, rounding=5)
    assert all(s % 5 == 0 for s in plan.stakes)
    assert plan.min_profit == pytest.approx(min(p - plan.total for p in plan.payouts))


# --- detection ----------------------------------------------------------

def test_moneyline_arb_across_two_books():
    e = event(
        book("draftkings", {"h2h": [{"name": "Giants", "price": 2.20}, {"name": "Cowboys", "price": 1.70}]}),
        book("fanduel", {"h2h": [{"name": "Giants", "price": 1.80}, {"name": "Cowboys", "price": 2.05}]}),
    )
    [opp] = find_arbs(e, now=NOW)
    assert opp.line == "moneyline"
    assert {(l.outcome, l.book) for l in opp.legs} == {("Giants", "draftkings"), ("Cowboys", "fanduel")}
    assert opp.margin == pytest.approx(1 / (1 / 2.20 + 1 / 2.05) - 1)


def test_no_arb_when_book_vig_covers_it():
    e = event(
        book("draftkings", {"h2h": [{"name": "Giants", "price": 1.91}, {"name": "Cowboys", "price": 1.91}]}),
        book("fanduel", {"h2h": [{"name": "Giants", "price": 1.95}, {"name": "Cowboys", "price": 1.87}]}),
    )
    assert find_arbs(e, now=NOW) == []


def test_three_way_soccer_needs_all_outcomes():
    e = event(
        book("a", {"h2h": [{"name": "Giants", "price": 3.4}, {"name": "Cowboys", "price": 2.5}, {"name": "Draw", "price": 3.2}]}),
        book("b", {"h2h": [{"name": "Giants", "price": 2.9}, {"name": "Cowboys", "price": 2.9}, {"name": "Draw", "price": 3.0}]}),
    )
    [opp] = find_arbs(e, now=NOW)
    assert len(opp.legs) == 3


def test_two_way_and_three_way_books_never_mix():
    e = event(
        book("a", {"h2h": [{"name": "Giants", "price": 3.4}, {"name": "Cowboys", "price": 2.5}, {"name": "Draw", "price": 3.2}]}),
        book("b", {"h2h": [{"name": "Giants", "price": 2.0}, {"name": "Cowboys", "price": 2.9}]}),
    )
    assert find_arbs(e, now=NOW) == []


def test_spread_pairs_opposite_lines_only():
    e = event(
        book("a", {"spreads": [{"name": "Giants", "price": 2.10, "point": -3.5}, {"name": "Cowboys", "price": 1.75, "point": 3.5}]}),
        book("b", {"spreads": [{"name": "Giants", "price": 1.75, "point": -3.5}, {"name": "Cowboys", "price": 2.05, "point": 3.5}]}),
        # Different line: must not pair Giants -3.5 with Cowboys +2.5.
        book("c", {"spreads": [{"name": "Giants", "price": 1.6, "point": -2.5}, {"name": "Cowboys", "price": 2.6, "point": 2.5}]}),
    )
    [opp] = find_arbs(e, now=NOW)
    assert opp.line == "Giants -3.5"
    assert {l.point for l in opp.legs} == {-3.5, 3.5}


def test_totals_pair_same_number():
    e = event(
        book("a", {"totals": [{"name": "Over", "price": 2.08, "point": 44.5}, {"name": "Under", "price": 1.78, "point": 44.5}]}),
        book("b", {"totals": [{"name": "Over", "price": 1.80, "point": 44.5}, {"name": "Under", "price": 2.06, "point": 44.5}]}),
        book("c", {"totals": [{"name": "Over", "price": 3.0, "point": 47.5}, {"name": "Under", "price": 1.3, "point": 47.5}]}),
    )
    [opp] = find_arbs(e, now=NOW)
    assert opp.line == "total 44.5"


def test_filters_suspicious_margin_stale_odds_and_started_games():
    lines = {"h2h": [{"name": "Giants", "price": 3.0}, {"name": "Cowboys", "price": 1.5}]}
    other = {"h2h": [{"name": "Giants", "price": 1.4}, {"name": "Cowboys", "price": 3.0}]}
    # 3.0 / 3.0 is a 50% "arb": a palp, not a real opportunity.
    assert find_arbs(event(book("a", lines), book("b", other)), now=NOW) == []
    assert find_arbs(event(book("a", lines), book("b", other)), now=NOW, max_margin=1) != []

    stale = (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    e = event(book("a", lines, stamp=stale), book("b", other))
    assert find_arbs(e, now=NOW, max_margin=1, max_odds_age=600) == []

    started = (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    assert find_arbs(event(book("a", lines), book("b", other), commence=started), now=NOW, max_margin=1) == []


def test_single_book_cannot_arb_itself():
    e = event(book("a", {"h2h": [{"name": "Giants", "price": 2.1}, {"name": "Cowboys", "price": 2.1}]}))
    assert find_arbs(e, now=NOW) == []


# --- storage ------------------------------------------------------------

def test_db_tracks_lifetime_and_closes_vanished_arbs(tmp_path):
    conn = db.connect(str(tmp_path / "t.db"))
    e = event(
        book("draftkings", {"h2h": [{"name": "Giants", "price": 2.20}, {"name": "Cowboys", "price": 1.70}]}),
        book("fanduel", {"h2h": [{"name": "Giants", "price": 1.80}, {"name": "Cowboys", "price": 2.05}]}),
        commence="2099-01-01T00:00:00Z",
    )
    opps = scan_events([e], now=NOW)
    db.record_scan(conn, opps, scanned_event_ids={"e1"})
    assert len(db.active(conn)) == 1

    db.record_scan(conn, [], scanned_event_ids={"e1"})
    assert db.active(conn) == []
    assert len(db.history(conn)) == 1
    assert db.stats(conn)["total"] == 1


# --- exchanges ----------------------------------------------------------

def test_fee_adjusted_price():
    from arb.stakes import fee_adjusted_price

    # 50c contract: fee 0.07 * 0.5 * 0.5 = 1.75c, so all-in 51.75c.
    assert fee_adjusted_price(2.0, 0.07) == pytest.approx(1 / 0.5175)
    assert fee_adjusted_price(2.0, 0.0) == pytest.approx(2.0)


def test_exchange_fees_can_erase_an_apparent_arb():
    # Listed prices arb by ~0.5%, but Kalshi's fee eats it.
    e = event(
        book("kalshi", {"h2h": [{"name": "Giants", "price": 2.04}, {"name": "Cowboys", "price": 1.90}]}),
        book("fanduel", {"h2h": [{"name": "Giants", "price": 1.85}, {"name": "Cowboys", "price": 1.98}]}),
    )
    assert find_arbs(e, now=NOW) != []
    assert find_arbs(e, now=NOW, fees={"kalshi": 0.07}) == []


def test_exchange_leg_carries_contract_details():
    e = event(
        book("polymarket", {"h2h": [{"name": "Giants", "price": 2.5}, {"name": "Cowboys", "price": 1.6}]}),
        book("draftkings", {"h2h": [{"name": "Giants", "price": 1.6}, {"name": "Cowboys", "price": 1.85}]}),
    )
    [opp] = find_arbs(e, now=NOW, fees={"polymarket": 0.0695})
    leg = next(l for l in opp.legs if l.book == "polymarket")
    assert leg.is_exchange and leg.raw_price == 2.5
    assert leg.contract_cents == pytest.approx(40)
    assert leg.price < 2.5
    assert leg.contracts_for(100) == int(100 * leg.price)
