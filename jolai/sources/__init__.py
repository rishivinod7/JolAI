"""Job sources. Each source is a function ``(fetcher, arg) -> list[Job]``."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..http import Fetcher
from ..models import Job
from .aggregators import hackernews, remoteok, remotive
from .ats import ashby, greenhouse, lever
from .careers import career_page

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
