"""Counts requests to services with a quota, so a search never goes over it.

* Jooble: 500 requests per key by default.
* Adzuna: 25 test calls while "Pending Activation"; the paid plan allows 5,000 a month and 500 a day.

Set the limits per source in config.yaml (``request_limit`` for the total or monthly allowance,
``limit_period: month`` if it resets monthly, ``daily_limit`` for a per-day cap).

Stored in results/api_usage.json as
{"jooble": {"total": 12, "by_month": {"2026-10": 12}, "by_day": {"2026-10-28": 12}}}.
Only real network requests count; answers served from the 6-hour cache are free.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

# Which host belongs to which service, and the default quota if the config doesn't set one.
SERVICES = {"jooble.org": "jooble", "api.adzuna.com": "adzuna"}
DEFAULT_LIMITS = {"jooble": 500, "adzuna": 25}


class Usage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict = json.loads(self.path.read_text()) if self.path.exists() else {}

    def used(self, service: str) -> int:
        return self.data.get(service, {}).get("total", 0)

    def this_month(self, service: str) -> int:
        return self.data.get(service, {}).get("by_month", {}).get(f"{date.today():%Y-%m}", 0)

    def today(self, service: str) -> int:
        return self.data.get(service, {}).get("by_day", {}).get(f"{date.today():%Y-%m-%d}", 0)

    def remaining(self, service: str, cfg: dict) -> int | None:
        """Requests left before any configured limit is hit, or None if there's no limit."""
        left = []
        limit = limit_for(service, cfg)
        if limit:
            spent = self.this_month(service) if cfg.get("limit_period") == "month" else self.used(service)
            left.append(limit - spent)
        if cfg.get("daily_limit"):
            left.append(int(cfg["daily_limit"]) - self.today(service))
        return max(0, min(left)) if left else None

    def add_requests(self, by_host: dict[str, int]) -> None:
        """Record a Fetcher's ``requests`` counter after a search."""
        month, day = f"{date.today():%Y-%m}", f"{date.today():%Y-%m-%d}"
        for host, n in by_host.items():
            service = SERVICES.get(host)
            if not service or not n:
                continue
            entry = self.data.setdefault(service, {"total": 0, "by_month": {}, "by_day": {}})
            entry["total"] += n
            entry["by_month"][month] = entry["by_month"].get(month, 0) + n
            entry.setdefault("by_day", {})[day] = entry["by_day"].get(day, 0) + n
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


def limit_for(service: str, cfg: dict) -> int | None:
    """The request quota from the config (``sources.<service>.request_limit``), or the default."""
    value = cfg.get("request_limit", DEFAULT_LIMITS.get(service))
    return int(value) if value else None


def usage_text(usage: Usage, service: str, cfg: dict) -> str:
    """'7 of 25 used' / '120 of 5000 this month, 40 of 500 today' for the UI."""
    limit = limit_for(service, cfg)
    monthly = cfg.get("limit_period") == "month"
    parts = []
    if limit:
        parts.append(f"{usage.this_month(service) if monthly else usage.used(service)} of {limit} used"
                     + (" this month" if monthly else ""))
    if cfg.get("daily_limit"):
        parts.append(f"{usage.today(service)} of {cfg['daily_limit']} today")
    return ", ".join(parts) or f"{usage.used(service)} used"
