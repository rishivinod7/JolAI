"""Job sources. Each source is a function ``(fetcher, arg) -> list[Job]``."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..http import Fetcher
from ..models import Job
from .aggregators import hackernews, remoteok, remotive
from .ats import ashby, greenhouse, lever
from .careers import career_page
from .search_apis import MissingKey, adzuna, adzuna_keys, jooble, jooble_key

log = logging.getLogger(__name__)

PER_BOARD = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "career_pages": career_page}


def plan_tasks(sources: dict, search_terms: list[str]) -> list[tuple[str, callable, object]]:
    """Turn the ``sources`` config section into a list of (label, function, argument)."""
    tasks = []
    for key, func in PER_BOARD.items():
        for board in sources.get(key) or []:
            tasks.append((f"{key}:{board}", func, board))
    terms = search_terms or [""]
    if sources.get("remotive"):
        tasks += [(f"remotive:{t or 'all'}", remotive, t) for t in terms]
    if sources.get("remoteok"):
        tasks.append(("remoteok", remoteok, ""))
    if sources.get("hackernews"):
        tasks.append(("hackernews", hackernews, int(sources.get("hackernews_months", 1))))
    tasks += _search_api_tasks(sources, [t for t in terms if t])
    return tasks


def _fail(message: str):
    def task(fetcher, arg):
        raise MissingKey(message)
    return task


def _within_budget(service: str, planned: list, remaining: int | None, pages: int) -> list:
    """Trim planned searches to the requests left on a quota; a clear error if none are left."""
    if remaining is None or remaining >= len(planned) * pages:
        return planned
    planned = planned[: max(0, remaining // pages)]
    if planned:
        return planned
    name = service.title()
    return [(service, _fail(f"{name} request limit reached. Upgrade or ask {name} for more requests, "
                            f"then raise sources.{service}.request_limit in config.yaml."), None)]


def _search_api_tasks(sources: dict, terms: list[str]) -> list[tuple[str, callable, object]]:
    """One task per (search term) x (country or place) for Adzuna and Jooble.

    Both have request quotas, so each searches only its first ``max_terms`` titles and stops at
    ``remaining_requests`` (set by pipeline.collect_jobs from results/api_usage.json). Titles are
    the outer loop, so when the budget runs short every place still gets your first titles.
    """
    tasks = []
    terms = terms or [""]
    az = sources.get("adzuna") or {}
    if az and az.get("enabled", True) and az.get("countries"):
        try:
            app_id, app_key = adzuna_keys(az)
        except MissingKey as exc:
            tasks.append(("adzuna", _fail(str(exc)), None))
        else:
            pages = int(az.get("pages", 1))
            planned = [(f"adzuna:{country}:{term or 'all'}", adzuna,
                        {"country": country, "what": term, "app_id": app_id, "app_key": app_key, "pages": pages,
                         "max_days_old": az.get("max_days_old", 30)})
                       for term in terms[: int(az.get("max_terms", 6))] for country in az["countries"]]
            tasks += _within_budget("adzuna", planned, az.get("remaining_requests"), pages)
    jb = sources.get("jooble") or {}
    if jb and jb.get("enabled", True) and jb.get("locations"):
        try:
            key = jooble_key(jb)
        except MissingKey as exc:
            tasks.append(("jooble", _fail(str(exc)), None))
        else:
            pages = int(jb.get("pages", 1))
            planned = [(f"jooble:{location}:{term or 'all'}", jooble,
                        {"location": location, "keywords": term, "api_key": key, "pages": pages})
                       for term in terms[: int(jb.get("max_terms", 4))] for location in jb["locations"]]
            tasks += _within_budget("jooble", planned, jb.get("remaining_requests"), pages)
    return tasks


def collect(fetcher: Fetcher, sources: dict, search_terms: list[str], workers: int = 8,
            on_result=None) -> list[Job]:
    """Fetch every configured source concurrently and de-duplicate the results."""
    jobs: dict[str, Job] = {}
    tasks = plan_tasks(sources, search_terms)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(func, fetcher, arg): label for label, func, arg in tasks}
        for future in as_completed(futures):
            label = futures[future]
            try:
                found = future.result()
            except Exception as exc:
                log.warning("%s failed: %s", label, exc)
                if on_result:
                    on_result(label, None, exc)
                continue
            for job in found:
                if job.title:
                    jobs.setdefault(job.id, job)
            if on_result:
                on_result(label, len(found), None)
    return list(jobs.values())
