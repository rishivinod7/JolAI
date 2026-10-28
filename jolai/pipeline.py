"""The search pipeline, step by step. Both the web UI (``ui.py``) and the CLI (``cli.py``) call this.

    resume file ──► read_profile ──► Profile (skills, years, level)
                                          │
    config.yaml ──► collect_jobs ──► [Job, Job, …]   (scraped from the sources you picked)
                                          │
                         rank ──► filters drop jobs that break your rules,
                                  then every remaining job is scored ──► [Match, …]
                                          │
                 (optional) ai_rerank ──► Claude double-checks the top few

Your choices about individual jobs (saved, applied, hidden, "filter was wrong") live in
``Tracker``. Each search is logged in results/runs.jsonl. ``stats.py`` turns both into the
numbers on the Stats tab.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path

from . import sources
from .config import DEFAULT_SOURCES, describe_preferences, preferences_from
from .http import Fetcher
from .matcher import Rejected, score_jobs
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
    results: dict[str, dict] = {}

    def record(label, count, error):
        results[label] = {"error": str(error)} if error else {"count": count}
        if on_progress:
            on_progress(label, count, error)

    jobs = sources.collect(fetcher, config.get("sources") or DEFAULT_SOURCES, search_terms(config),
                           on_result=record)
    out = results_dir(config)
    out.mkdir(parents=True, exist_ok=True)
    previous = {j.id for j in load_jobs(out / "jobs.json")}
    (out / "jobs.json").write_text(json.dumps([vars(j) for j in jobs], indent=2), encoding="utf-8")
    run = {"at": datetime.now().isoformat(timespec="seconds"), "total": len(jobs),
           "new": sum(1 for j in jobs if j.id not in previous), "sources": results}
    with (out / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(run) + "\n")
    return jobs


def load_runs(config: dict) -> list[dict]:
    """Every logged search, oldest first."""
    path = results_dir(config) / "runs.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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


@dataclass
class RankResult:
    matches: list[Match]
    filtered: dict[str, int]  # filter reason -> how many jobs it removed
    rejected: list[Rejected] = field(default_factory=list)  # the removed jobs themselves


def rank_all(profile: Profile, jobs: list[Job], config: dict, keep_ids: set[str] | None = None) -> RankResult:
    """Like ``rank``, but also returns the filtered-out jobs, and keeps jobs you rescued from a filter."""
    rejected: list[Rejected] = []
    matches, filtered = score_jobs(profile, jobs, preferences_from(config), keep_ids=keep_ids, rejected=rejected)
    return RankResult(matches, filtered, rejected)


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
    """Remembers what you did with each job, in results/tracker.json.

    Statuses:
      saved     you starred it
      applied   you applied; ``outcome`` records what happened next
      hidden    not for you; ``reason`` says why (feeds the Stats tab)
      rescued   a filter hid it but you said it's a good job; ``reason`` is the filter it failed
    """

    STATUSES = ("saved", "applied", "hidden", "rescued")
    HIDE_REASONS = ("Not interested", "Wrong field", "Too senior", "Too junior", "Location or visa", "Pay",
                    "Already applied elsewhere", "Other")
    OUTCOMES = ("Waiting", "Replied", "Interview", "Offer", "Rejected")

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, dict] = json.loads(self.path.read_text()) if self.path.exists() else {}

    def status(self, job_id: str) -> str | None:
        return self.data.get(job_id, {}).get("status")

    def get(self, job_id: str) -> dict:
        return self.data.get(job_id, {})

    def ids(self, status: str) -> set[str]:
        return {jid for jid, v in self.data.items() if v.get("status") == status}

    def set(self, job: Job | Match, status: str | None, reason: str | None = None,
            score: float | None = None) -> None:
        """Record a decision. ``score`` is the job's score at the time, used to judge the ranking."""
        if isinstance(job, Match):
            score = job.score if score is None else score
            job = job.job
        if status is None:
            self.data.pop(job.id, None)
        else:
            now = datetime.now().isoformat(timespec="seconds")
            entry = {"status": status, "title": job.title, "company": job.company, "url": job.url,
                     "source": job.source, "at": now}
            if reason:
                entry["reason"] = reason
            if score is not None:
                entry["score"] = score
            if status == "applied":
                entry["outcome"] = self.data.get(job.id, {}).get("outcome", "Waiting")
            self.data[job.id] = entry
        self._save()

    def set_outcome(self, job_id: str, outcome: str) -> None:
        if job_id in self.data:
            self.data[job_id]["outcome"] = outcome
            self.data[job_id]["outcome_at"] = datetime.now().isoformat(timespec="seconds")
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
