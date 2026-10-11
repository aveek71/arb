# Arb Finder

Finds sports betting arbitrage across New York–licensed sportsbooks and the Kalshi and Polymarket prediction markets and shows it on a web dashboard with stake sizing. It **alerts only**; it never places bets.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add your ODDS_API_KEY, or set DEMO=1
arb-web                       # http://127.0.0.1:8000
```

`DEMO=1 arb-web` runs with fake odds so you can try the dashboard without a key.

## How it works

1. Every `POLL_SECONDS`, it lists in-season sports from [The Odds API](https://the-odds-api.com) (free call) and fetches moneyline, spread and total odds for each from the NY books: DraftKings, FanDuel, BetMGM, Caesars, BetRivers, Fanatics, theScore Bet and Bally Bet, plus Kalshi and Polymarket.
2. For each game and line it takes the best price per outcome across books. If `sum(1/odds) < 1`, that's an arb with margin `1/sum - 1`.
3. Stakes are `bankroll × (1/odds) / sum`, rounded to `STAKE_ROUNDING`; the dashboard shows the worst-case profit after rounding.
4. Every opportunity is logged to SQLite with when it appeared and disappeared, so you can see how often arbs show up and how long they last.

Kalshi and Polymarket prices are adjusted for taker fees before any math (`coef × p × (1 − p)` per contract: 0.07 for Kalshi, 0.0695 for Polymarket US), so an arb only shows if it survives the fee. The dashboard shows the contract price in cents and how many contracts the stake buys. Turn them off with `EXCHANGES=` (empty).

Filters that stop false alarms:
- Spreads only pair opposite sides of the same number (home −3.5 with away +3.5); totals pair Over/Under of the same number.
- 2-way and 3-way moneylines are never mixed.
- Margins above `MAX_MARGIN` (default 10%) are dropped as likely stale or erroneous lines.
- Prices older than `MAX_ODDS_AGE_SECONDS` and games that have started are skipped.
- Both legs at the same book are ignored.

## API cost

Each sport costs `markets × ceil(books / 10)` credits per sweep, which is 3 with the defaults. With ~30 in-season sports that's ~90 credits a sweep:

| Poll interval | Credits / month | Plan |
|---|---|---|
| 30 min | ~130K | $59 (100K) is tight; use `SPORTS=` to narrow it |
| 5 min | ~780K | $119 (5M) |
| 1 min | ~3.9M | $119 (5M) |

Set `SPORTS=americanfootball_nfl,basketball_nba,...` to scan fewer sports while on the free tier (500 credits).

## Before you bet

- Kalshi's and Polymarket's sports contracts are being litigated in New York (the state sued Kalshi in July 2026 and has sued Polymarket US). Check that each market is open to you before trading.
- On an exchange, the listed price may not have depth for your full size. Check the order book.

- Re-check both prices in the apps before placing either leg; polled odds can be minutes old.
- Place the leg at the softer book first, then the sharper one.
- Soft books limit accounts that consistently arb. Keep stakes round and unremarkable.
- Confirm both books settle the market the same way (overtime, pushes, voids).

## Development

```bash
pytest
```

Layout: `arb/detector.py` (arb detection), `arb/stakes.py` (math), `arb/odds_client.py` (API), `arb/db.py` (SQLite log), `arb/scanner.py` (polling loop), `arb/web.py` + `arb/templates/` (dashboard).
