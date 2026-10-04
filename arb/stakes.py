"""Arbitrage math: implied probabilities, margins and stake sizing."""

from __future__ import annotations

from dataclasses import dataclass


def american_to_decimal(american: float) -> float:
    if american >= 100:
        return 1 + american / 100
    if american <= -100:
        return 1 + 100 / abs(american)
    raise ValueError(f"invalid American odds: {american}")


def decimal_to_american(decimal: float) -> int:
    if decimal <= 1:
        raise ValueError(f"invalid decimal odds: {decimal}")
    if decimal >= 2:
        return round((decimal - 1) * 100)
    return round(-100 / (decimal - 1))


def implied_sum(prices: list[float]) -> float:
    """Sum of 1/odds. Below 1.0 means an arbitrage exists."""
    return sum(1 / p for p in prices)


def margin(prices: list[float]) -> float:
    """Guaranteed return on total stake, e.g. 0.031 for 3.1%."""
    return 1 / implied_sum(prices) - 1


@dataclass
class StakePlan:
    stakes: list[float]
    total: float
    payouts: list[float]
    min_profit: float
    max_profit: float

    @property
    def min_roi(self) -> float:
        return self.min_profit / self.total if self.total else 0.0


def stake_plan(prices: list[float], bankroll: float, rounding: float = 1.0) -> StakePlan:
    """Split `bankroll` so every outcome pays roughly the same.

    Stakes are rounded to `rounding` units (books dislike odd amounts like $437.21),
    and profit is recomputed after rounding, so `min_profit` is what you are
    actually guaranteed.
    """
    s = implied_sum(prices)
    raw = [bankroll * (1 / p) / s for p in prices]
    if rounding > 0:
        stakes = [round(x / rounding) * rounding for x in raw]
    else:
        stakes = raw
    total = sum(stakes)
    payouts = [st * p for st, p in zip(stakes, prices)]
    profits = [pay - total for pay in payouts]
    return StakePlan(
        stakes=stakes,
        total=total,
        payouts=payouts,
        min_profit=min(profits),
        max_profit=max(profits),
    )
