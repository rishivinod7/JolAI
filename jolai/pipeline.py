"""The search pipeline, step by step. Both the web UI (``ui.py``) and the CLI (``cli.py``) call this.

    resume file ──► read_profile ──► Profile (skills, years, level)
                                          │
    config.yaml ──► collect_jobs ──► [Job, Job, …]   (scraped from the sources you picked)
                                          │
                         rank ──► filters drop jobs that break your rules,
                                  then every remaining job is scored ──► [Match, …]
                                          │
                 (optional) ai_rerank ──► Claude double-checks the top few

Your choices about individual jobs (saved, applied, hidden) live in ``Tracker``.
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from . import sources
from .config import DEFAULT_SOURCES, describe_preferences, preferences_from
from .http import Fetcher
from .matcher import score_jobs
from .models import Job, Match, Profile
from .resume import build_profile, read_resume_text


def results_dir(config: dict) -> Path:
    return Path((config.get("output") or {}).get("dir") or "results")


# -- Step 1: your resume -----------------------------------------------------------------

def read_profile(config: dict, resume_path: str | Path | None = None, resume_text: str | None = None) -> Profile:
    """Read the resume (a file path or already-extracted text) and apply fix-ups from the config."""
    prefs = config.get("preferences") or {}
    if resume_text is None:
        path = resume_path or config.get("resume")
        if not path:
            raise ValueError("No resume given. Set `resume:` in config.yaml or upload one.")
        resume_text = read_resume_text(path)
    return build_profile(resume_text, extra_skills=prefs.get("extra_skills"),
                         years_override=prefs.get("years_experience"))


# -- Step 2: collect jobs ----------------------------------------------------------------

def search_terms(config: dict) -> list[str]:
    """Words sent to sources that support search (Remotive). Defaults to your target titles (up to 6)."""
    explicit = (config.get("sources") or {}).get("search_terms")
    if explicit:
        return list(explicit)
    return list(((config.get("preferences") or {}).get("titles") or [])[:6])


def collect_jobs(config: dict, use_cache: bool = True, on_progress=None) -> list[Job]:
    """Scrape every configured source and save the raw list to results/jobs.json.

    ``on_progress(label, count, error)`` is called once per source as it finishes.
    """
    fetcher = Fetcher(cache_ttl=6 * 3600 if use_cache else 0)
    jobs = sources.collect(fetcher, config.get("sources") or DEFAULT_SOURCES, search_terms(config),
                           on_result=on_progress)
    out = results_dir(config)
    out.mkdir(parents=True, exist_ok=True)
    (out / "jobs.json").write_text(json.dumps([vars(j) for j in jobs], indent=2), encoding="utf-8")
    return jobs


def load_jobs(path: str | Path) -> list[Job]:
    """Load jobs saved by an earlier collect_jobs run."""
    path = Path(path)
    if not path.exists():
        return []
    names = {f.name for f in fields(Job)}
    return [Job(**{k: v for k, v in item.items() if k in names})
            for item in json.loads(path.read_text(encoding="utf-8"))]


# -- Step 3: filter and score ------------------------------------------------------------

def rank(profile: Profile, jobs: list[Job], config: dict) -> tuple[list[Match], dict[str, int]]:
    """Drop jobs that break your rules and score the rest. Returns (matches, why-filtered counts)."""
    return score_jobs(profile, jobs, preferences_from(config))


# -- Step 4 (optional): AI double-check ----------------------------------------------------

def ai_rerank(matches: list[Match], profile: Profile, config: dict, cache_only: bool = False) -> list[Match]:
    """Ask Claude to re-check the top matches. Answers are cached, so each job is paid for once.

    With ``cache_only=True`` nothing is sent to Claude; earlier answers are just re-applied (free).
    """
    from .llm import DEFAULT_MODEL, rerank

    llm_cfg = config.get("llm") or {}
    prefs = preferences_from(config)
    return rerank(matches, profile.text, describe_preferences(prefs),
                  top_n=int(llm_cfg.get("top_n", 10)), model=llm_cfg.get("model", DEFAULT_MODEL),
                  effort=llm_cfg.get("effort", "low"), alpha=prefs.alpha,
                  cache_path=results_dir(config) / "ai_cache.json", cache_only=cache_only)


# -- Your decisions about jobs -----------------------------------------------------------

class Tracker:
    """Remembers which jobs you saved, applied to or hid, in results/tracker.json."""

    STATUSES = ("saved", "applied", "hidden")

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, dict] = json.loads(self.path.read_text()) if self.path.exists() else {}

    def status(self, job_id: str) -> str | None:
        return self.data.get(job_id, {}).get("status")

    def set(self, match: Match, status: str | None) -> None:
        if status is None:
            self.data.pop(match.job.id, None)
        else:
            j = match.job
            self.data[match.job.id] = {"status": status, "title": j.title, "company": j.company, "url": j.url}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
