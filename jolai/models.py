"""Core data types shared across the pipeline."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Job:
    title: str
    company: str
    url: str
    source: str
    location: str = ""
    description: str = ""
    remote: bool = False
    posted_at: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None  # e.g. "INR"; None means USD or unknown
    tags: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        """Stable id used for de-duplication and the 'seen jobs' history."""
        key = f"{_norm(self.company)}|{_norm(self.title)}|{_norm(self.location)}"
        return hashlib.sha1(key.encode()).hexdigest()[:12]

    @property
    def text(self) -> str:
        return "\n".join([self.title, self.company, self.location, " ".join(self.tags), self.description])


@dataclass
class Profile:
    """What we learned about the candidate from their resume."""

    text: str
    skills: set[str] = field(default_factory=set)
    titles: list[str] = field(default_factory=list)
    years_experience: float = 0.0
    level: int = 2  # index into matcher.LEVELS
    has_management: bool = False


@dataclass
class Match:
    job: Job
    score: float  # overall 0-100
    chance: float  # how likely you are to get it, 0-100
    want: float  # how well it fits your stated preferences, 0-100
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    llm_score: Optional[float] = None
    llm_summary: Optional[str] = None
    facts: Optional[object] = None  # matcher.JobFacts: level, years, languages, technical score


def pay_text(job: Job) -> str:
    """'$120,000–150,000' or 'INR 1,200,000' style pay range, or '' when the posting has none."""
    values = list(dict.fromkeys(v for v in (job.salary_min, job.salary_max) if v))
    if not values:
        return ""
    prefix = "$" if job.salary_currency in (None, "USD") else f"{job.salary_currency} "
    return prefix + "–".join(f"{v:,.0f}" for v in values)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
