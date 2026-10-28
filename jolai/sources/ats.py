"""Public job-board APIs of the common applicant tracking systems.

Most tech companies host their careers page on one of these. The board name is the
last part of the careers URL, e.g. boards.greenhouse.io/<board>, jobs.lever.co/<board>,
jobs.ashbyhq.com/<board>.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..http import Fetcher
from ..models import Job
from .base import html_to_text, looks_remote, parse_salary_range, to_number


def greenhouse(fetcher: Fetcher, board: str) -> list[Job]:
    data = fetcher.get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    jobs = []
    for item in data.get("jobs", []):
        location = (item.get("location") or {}).get("name", "")
        description = html_to_text(item.get("content"))
        lo, hi = parse_salary_range(description)
        company = (item.get("company_name") or board).strip()
        jobs.append(Job(
            title=item.get("title", "").strip(),
            company=company,
            url=item.get("absolute_url", ""),
            source="greenhouse",
            location=location,
            description=description,
            remote=looks_remote(location),
            posted_at=item.get("updated_at") or item.get("first_published"),
            salary_min=lo,
            salary_max=hi,
            tags=[d.get("name", "") for d in item.get("departments", []) if d.get("name")],
        ))
    return jobs


def lever(fetcher: Fetcher, board: str) -> list[Job]:
    data = fetcher.get_json(f"https://api.lever.co/v0/postings/{board}?mode=json")
    jobs = []
    for item in data if isinstance(data, list) else []:
        categories = item.get("categories") or {}
        location = categories.get("location") or ", ".join(categories.get("allLocations") or [])
        sections = [item.get("descriptionPlain") or html_to_text(item.get("description"))]
        for block in item.get("lists") or []:
            sections.append(f"{block.get('text', '')}\n{html_to_text(block.get('content'))}")
        sections.append(item.get("additionalPlain") or "")
        description = "\n\n".join(s for s in sections if s)
        salary = item.get("salaryRange") or {}
        lo, hi = to_number(salary.get("min")), to_number(salary.get("max"))
        if lo is None and hi is None:
            lo, hi = parse_salary_range(description)
        created = item.get("createdAt")
        jobs.append(Job(
            title=item.get("text", "").strip(),
            company=board,
            url=item.get("hostedUrl", ""),
            source="lever",
            location=location,
            description=description,
            remote=item.get("workplaceType") == "remote" or looks_remote(location),
            posted_at=datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat() if created else None,
            salary_min=lo,
            salary_max=hi,
            tags=[v for v in (categories.get("team"), categories.get("commitment")) if v],
        ))
    return jobs


def ashby(fetcher: Fetcher, board: str) -> list[Job]:
    data = fetcher.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true")
    jobs = []
    for item in data.get("jobs", []):
        if item.get("isListed") is False:
            continue
        location = item.get("location", "")
        description = item.get("descriptionPlain") or html_to_text(item.get("descriptionHtml"))
        comp = item.get("compensation") or {}
        lo, hi = parse_salary_range(comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary"))
        jobs.append(Job(
            title=item.get("title", "").strip(),
            company=board,
            url=item.get("jobUrl") or item.get("applyUrl", ""),
            source="ashby",
            location=location,
            description=description,
            remote=bool(item.get("isRemote")) or item.get("workplaceType") == "Remote" or looks_remote(location),
            posted_at=item.get("publishedAt"),
            salary_min=lo,
            salary_max=hi,
            tags=[v for v in (item.get("department"), item.get("team"), item.get("employmentType")) if v],
        ))
    return jobs
