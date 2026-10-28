"""Counts requests to services with a quota (Jooble gives 500 requests per key by default).

Stored in results/api_usage.json as {"jooble": {"total": 12, "by_month": {"2026-10": 12}}}.
Only real network requests count; answers served from the 6-hour cache are free.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

# Which host belongs to which service, and the default quota if the config doesn't set one.
SERVICES = {"jooble.org": "jooble", "api.adzuna.com": "adzuna"}
DEFAULT_LIMITS = {"jooble": 500}


class Usage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict = json.loads(self.path.read_text()) if self.path.exists() else {}

    def used(self, service: str) -> int:
        return self.data.get(service, {}).get("total", 0)

    def this_month(self, service: str) -> int:
        return self.data.get(service, {}).get("by_month", {}).get(f"{date.today():%Y-%m}", 0)

    def add_requests(self, by_host: dict[str, int]) -> None:
        """Record a Fetcher's ``requests`` counter after a search."""
        month = f"{date.today():%Y-%m}"
        for host, n in by_host.items():
            service = SERVICES.get(host)
            if not service or not n:
                continue
            entry = self.data.setdefault(service, {"total": 0, "by_month": {}})
            entry["total"] += n
            entry["by_month"][month] = entry["by_month"].get(month, 0) + n
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


def limit_for(service: str, cfg: dict) -> int | None:
    """The request quota from the config (``sources.<service>.request_limit``), or the default."""
    value = cfg.get("request_limit", DEFAULT_LIMITS.get(service))
    return int(value) if value else None
