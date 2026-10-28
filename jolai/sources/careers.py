"""Generic career-page scraper.

Most job pages embed schema.org ``JobPosting`` JSON-LD for Google for Jobs, so we can read
structured data from almost any careers site. Starting from a URL, we extract postings on
that page and follow same-site links that look like job pages, up to ``max_pages``.
robots.txt is respected for every page fetched.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin, urldefrag, urlparse

from bs4 import BeautifulSoup

from ..http import Fetcher
from ..models import Job
from .base import html_to_text, looks_remote, parse_salary_range, to_number

log = logging.getLogger(__name__)

JOB_LINK_RE = re.compile(r"/(jobs?|careers?|positions?|openings?|roles?|vacanc(y|ies)|postings?)(/|$|\?)", re.I)


def career_page(fetcher: Fetcher, start_url: str, max_pages: int = 40) -> list[Job]:
    start_host = urlparse(start_url).netloc
    queue, seen, jobs = [start_url], set(), {}
    while queue and len(seen) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            page = fetcher.get_text(url, check_robots=True)
        except Exception as exc:  # one bad page shouldn't kill the crawl
            log.warning("skipping %s: %s", url, exc)
            continue
        for job in extract_job_postings(page, url):
            jobs.setdefault(job.url, job)
        for link in _job_links(page, url):
            if urlparse(link).netloc == start_host and link not in seen:
                queue.append(link)
    return list(jobs.values())


def extract_job_postings(page: str, page_url: str) -> list[Job]:
    soup = BeautifulSoup(page, "html.parser")
    jobs = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "JobPosting" in types:
                jobs.append(_to_job(node, page_url))
    return jobs


def _walk(data):
    if isinstance(data, list):
        for item in data:
            yield from _walk(item)
    elif isinstance(data, dict):
        yield data
        for key in ("@graph", "itemListElement", "item"):
            if key in data:
                yield from _walk(data[key])


def _to_job(node: dict, page_url: str) -> Job:
    org = node.get("hiringOrganization") or {}
    company = org.get("name", "") if isinstance(org, dict) else str(org)
    description = html_to_text(node.get("description"))
    lo, hi = _salary(node.get("baseSalary"))
    if lo is None and hi is None:
        lo, hi = parse_salary_range(description)
    remote = node.get("jobLocationType") == "TELECOMMUTE"
    location = _location(node.get("jobLocation"))
    return Job(
        title=(node.get("title") or "").strip(),
        company=company.strip() or urlparse(page_url).netloc,
        url=node.get("url") or page_url,
        source="career_page",
        location=location or ("Remote" if remote else ""),
        description=description,
        remote=remote or looks_remote(location),
        posted_at=node.get("datePosted"),
        salary_min=lo,
        salary_max=hi,
        tags=[t for t in [node.get("employmentType")] if isinstance(t, str)],
    )


def _location(value) -> str:
    places = value if isinstance(value, list) else [value]
    names = []
    for place in places:
        if not isinstance(place, dict):
            continue
        address = place.get("address") or {}
        if isinstance(address, str):
            names.append(address)
            continue
        parts = [address.get(k) for k in ("addressLocality", "addressRegion", "addressCountry")]
        parts = [p.get("name") if isinstance(p, dict) else p for p in parts]
        names.append(", ".join(p for p in parts if p))
    return "; ".join(n for n in names if n)


def _salary(value) -> tuple[float | None, float | None]:
    if not isinstance(value, dict):
        return None, None
    amount = value.get("value")
    if isinstance(amount, dict):
        unit = (amount.get("unitText") or "YEAR").upper()
        lo, hi = to_number(amount.get("minValue")), to_number(amount.get("maxValue"))
        if lo is None and hi is None:
            lo = hi = to_number(amount.get("value"))
        factor = {"HOUR": 2080, "WEEK": 52, "MONTH": 12}.get(unit, 1)
        return (lo * factor if lo else None), (hi * factor if hi else None)
    number = to_number(amount)
    return number, number


def _job_links(page: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(page, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = urldefrag(urljoin(base_url, a["href"]))[0]
        if href.startswith("http") and JOB_LINK_RE.search(urlparse(href).path + "/"):
            links.append(href)
    return links
