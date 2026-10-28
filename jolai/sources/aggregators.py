"""Multi-company sources: Remotive, RemoteOK and Hacker News "Who is hiring?"."""

from __future__ import annotations

import re
from urllib.parse import quote

from ..http import Fetcher
from ..models import Job
from .base import html_to_text, looks_remote, parse_salary_range, to_number


def remotive(fetcher: Fetcher, search: str = "") -> list[Job]:
    url = "https://remotive.com/api/remote-jobs" + (f"?search={quote(search)}" if search else "")
    jobs = []
    for item in fetcher.get_json(url).get("jobs", []):
        description = html_to_text(item.get("description"))
        lo, hi = parse_salary_range(item.get("salary"))
        jobs.append(Job(
            title=item.get("title", "").strip(),
            company=item.get("company_name", "").strip(),
            url=item.get("url", ""),
            source="remotive",
            location=item.get("candidate_required_location") or "Remote",
            description=description,
            remote=True,
            posted_at=item.get("publication_date"),
            salary_min=lo,
            salary_max=hi,
            tags=list(item.get("tags") or []) + [v for v in (item.get("category"), item.get("job_type")) if v],
        ))
    return jobs


def remoteok(fetcher: Fetcher, tag: str = "") -> list[Job]:
    # RemoteOK asks API users to link back to the original posting, which we do via Job.url.
    url = "https://remoteok.com/api" + (f"?tag={quote(tag)}" if tag else "")
    jobs = []
    for item in fetcher.get_json(url):
        if not isinstance(item, dict) or "position" not in item:
            continue  # first element is the legal notice
        jobs.append(Job(
            title=item.get("position", "").strip(),
            company=item.get("company", "").strip(),
            url=item.get("url") or item.get("apply_url", ""),
            source="remoteok",
            location=item.get("location") or "Remote",
            description=html_to_text(item.get("description")),
            remote=True,
            posted_at=item.get("date"),
            salary_min=to_number(item.get("salary_min")),
            salary_max=to_number(item.get("salary_max")),
            tags=list(item.get("tags") or []),
        ))
    return jobs


def hackernews(fetcher: Fetcher, months: int = 1) -> list[Job]:
    """Parse the top-level comments of the latest monthly "Ask HN: Who is hiring?" threads.

    Posts conventionally start with "Company | Role | Location | ..." on the first line.
    """
    search = fetcher.get_json(
        "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=10"
    )
    threads = [h for h in search.get("hits", []) if "who is hiring" in (h.get("title") or "").lower()][:months]
    jobs = []
    for thread in threads:
        item = fetcher.get_json(f"https://hn.algolia.com/api/v1/items/{thread['objectID']}")
        for comment in item.get("children") or []:
            job = _parse_hn_comment(comment)
            if job:
                jobs.append(job)
    return jobs


def _parse_hn_comment(comment: dict) -> Job | None:
    raw = comment.get("text") or ""
    if not raw:
        return None
    text = html_to_text(raw)
    first_line = text.split("\n", 1)[0]
    parts = [p.strip() for p in re.split(r"\s+\|\s+|\s+\|\||\|", first_line) if p.strip()]
    if len(parts) < 2:
        return None
    company = re.sub(r"\s*\(.*?\)\s*", " ", parts[0]).strip()
    role_part = next((p for p in parts[1:] if re.search(
        r"engineer|developer|scientist|designer|manager|analyst|lead|architect|sre|devops|intern|researcher|product",
        p, re.I)), parts[1])
    location_part = next((p for p in parts[1:] if p is not role_part and (
        looks_remote(p) or re.search(r"\b[A-Z][a-z]+,\s*[A-Z]{2}\b|onsite|on-site|hybrid", p, re.I))), "")
    lo, hi = parse_salary_range(first_line)
    return Job(
        title=role_part[:150],
        company=company[:80],
        url=f"https://news.ycombinator.com/item?id={comment.get('id')}",
        source="hackernews",
        location=location_part,
        description=text,
        remote=looks_remote(first_line),
        posted_at=comment.get("created_at"),
        salary_min=lo,
        salary_max=hi,
    )
