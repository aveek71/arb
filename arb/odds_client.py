"""Thin client for The Odds API v4 (https://the-odds-api.com/liveapi/guides/v4/)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

BASE_URL = "https://api.the-odds-api.com/v4"


@dataclass
class Quota:
    remaining: int | None = None
    used: int | None = None
    last_cost: int | None = None


class OddsClient:
    def __init__(self, api_key: str, *, timeout: float = 20.0, base_url: str = BASE_URL):
        if not api_key:
            raise ValueError("ODDS_API_KEY is not set (or run with DEMO=1)")
        self.api_key = api_key
        self.quota = Quota()
        self._http = httpx.Client(base_url=base_url, timeout=timeout)

    def _get(self, path: str, **params) -> list[dict]:
        resp = self._http.get(path, params={"apiKey": self.api_key, **params})
        headers = resp.headers
        if "x-requests-remaining" in headers:
            self.quota = Quota(
                remaining=int(float(headers["x-requests-remaining"])),
                used=int(float(headers.get("x-requests-used", 0))),
                last_cost=int(float(headers.get("x-requests-last", 0))),
            )
        resp.raise_for_status()
        return resp.json()

    def sports(self) -> list[dict]:
        """In-season sports. Free: does not count against the quota."""
        return self._get("/sports")

    def odds(self, sport_key: str, *, markets: list[str], bookmakers: list[str]) -> list[dict]:
        """Upcoming events with odds. Costs len(markets) x ceil(len(bookmakers)/10) credits."""
        return self._get(
            f"/sports/{sport_key}/odds",
            markets=",".join(markets),
            bookmakers=",".join(bookmakers),
            oddsFormat="decimal",
            dateFormat="iso",
        )

    def close(self) -> None:
        self._http.close()
