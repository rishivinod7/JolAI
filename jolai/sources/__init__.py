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


def _search_api_tasks(sources: dict, terms: list[str]) -> list[tuple[str, callable, object]]:
    """One task per (country or city) x (search term) for Adzuna and Jooble."""
    tasks = []
    terms = terms or [""]
    az = sources.get("adzuna") or {}
    if az and az.get("enabled", True) and az.get("countries"):
        try:
            app_id, app_key = adzuna_keys(az)
        except MissingKey as exc:
            tasks.append(("adzuna", _fail(str(exc)), None))
        else:
            for country in az["countries"]:
                for term in terms:
                    tasks.append((f"adzuna:{country}:{term or 'all'}", adzuna,
                                  {"country": country, "what": term, "app_id": app_id, "app_key": app_key,
                                   "pages": az.get("pages", 1), "max_days_old": az.get("max_days_old", 30)}))
    jb = sources.get("jooble") or {}
    if jb and jb.get("enabled", True) and jb.get("locations"):
        try:
            key = jooble_key(jb)
        except MissingKey as exc:
            tasks.append(("jooble", _fail(str(exc)), None))
        else:
            # Jooble keys have a request quota, so use fewer titles (max_terms, default 4) and stop
            # at the remaining budget. Titles go in the outer loop, so if the budget runs short every
            # place still gets your first titles.
            pages = int(jb.get("pages", 1))
            remaining = jb.get("remaining_requests")  # set by pipeline.collect_jobs from api_usage.json
            planned = []
            for term in terms[: int(jb.get("max_terms", 4))]:
                for location in jb["locations"]:
                    planned.append((f"jooble:{location}:{term or 'all'}", jooble,
                                    {"location": location, "keywords": term, "api_key": key, "pages": pages}))
            if remaining is not None and remaining < len(planned) * pages:
                planned = planned[: max(0, remaining // pages)]
                if not planned:
                    tasks.append(("jooble", _fail("Jooble request limit reached. Ask Jooble for more requests "
                                                  "(reply to their email), or raise jooble.request_limit "
                                                  "if they already did."), None))
            tasks += planned
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
