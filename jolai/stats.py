"""Numbers for the Stats tab: is each part of the tool doing its job?

Each function answers one question from the product plan (docs/HOW_IT_WORKS.md, "Checking the tool"):

* ``source_summary``   Coverage: which sources bring in jobs, and which are failing?
* ``filter_rows``      Filtering: how much does each filter remove, and how often was it wrong?
* ``ranking_quality``  Ranking: do the jobs you save and apply to sit near the top?
* ``funnel``           Outcomes: saved -> applied -> heard back -> interview -> offer
* ``hide_reasons``     Why you hide jobs (things the filters could learn to catch)
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta

from .models import Job, Match


def _same_job_key(job: Job) -> str:
    """Company + title, ignoring punctuation and location wording, to spot one job listed on several sites."""
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()  # noqa: E731
    return f"{norm(job.company)}|{norm(job.title)}"


def source_summary(jobs: list[Job], last_run: dict | None) -> list[dict]:
    """One row per source: jobs in the latest download, how many no other source found,
    searches run, and failures with their messages.

    "Only here" is the number to watch when deciding whether a source is worth keeping (or paying for).
    """
    found = Counter(j.source for j in jobs)
    sources_per_job: dict[str, set[str]] = {}
    for j in jobs:
        sources_per_job.setdefault(_same_job_key(j), set()).add(j.source)
    only_here = Counter(next(iter(srcs)) for srcs in sources_per_job.values() if len(srcs) == 1)
    runs: dict[str, dict] = {}
    for label, result in ((last_run or {}).get("sources") or {}).items():
        name = label.split(":", 1)[0]
        name = {"career_pages": "career_page"}.get(name, name)
        row = runs.setdefault(name, {"searches": 0, "failed": 0, "errors": []})
        row["searches"] += 1
        if "error" in result:
            row["failed"] += 1
            if result["error"] not in row["errors"]:
                row["errors"].append(result["error"])
    rows = []
    for name in sorted(set(found) | set(runs), key=lambda n: -found.get(n, 0)):
        run = runs.get(name, {"searches": 0, "failed": 0, "errors": []})
        rows.append({"source": name, "jobs": found.get(name, 0), "only here": only_here.get(name, 0),
                     "searches": run["searches"],
                     "failed": run["failed"], "errors": "; ".join(run["errors"])})
    return rows


def filter_rows(filtered: dict[str, int], tracker_data: dict[str, dict]) -> list[dict]:
    """Per filter: jobs it removes now, jobs you said it was wrong about, and the share that's wrong.

    A rescued job is no longer filtered, so the share is rescued / (removed + rescued). It only
    means something once you've looked through that filter's jobs in the Filtered out tab.
    """
    rescued = Counter(v.get("reason") for v in tracker_data.values() if v.get("status") == "rescued")
    rows = []
    for reason in sorted(set(filtered) | {r for r in rescued if r}, key=lambda r: -filtered.get(r, 0)):
        removed, wrong = filtered.get(reason, 0), rescued.get(reason, 0)
        total = removed + wrong
        rows.append({"filter": reason, "removed": removed, "you said wrong": wrong,
                     "wrong %": round(100 * wrong / total) if total else 0})
    return rows


def ranking_quality(matches: list[Match], tracker_data: dict[str, dict]) -> dict:
    """Where your saved/applied jobs sit in the current ranking, and their scores vs. hidden jobs."""
    position = {m.job.id: i for i, m in enumerate(matches, 1)}
    liked = [jid for jid, v in tracker_data.items() if v.get("status") in ("saved", "applied", "rescued")]
    ranks = [position[jid] for jid in liked if jid in position]

    def avg_score(statuses):
        scores = [v["score"] for v in tracker_data.values() if v.get("status") in statuses and "score" in v]
        return round(sum(scores) / len(scores)) if scores else None

    return {
        "liked": len(liked),
        "ranked": len(ranks),
        "in_top_10": sum(r <= 10 for r in ranks),
        "in_top_25": sum(r <= 25 for r in ranks),
        "avg_score_liked": avg_score({"saved", "applied"}),
        "avg_score_hidden": avg_score({"hidden"}),
    }


def funnel(tracker_data: dict[str, dict]) -> list[tuple[str, int]]:
    """Saved -> applied -> heard back -> interview -> offer. Applied jobs count as saved too."""
    statuses = [v.get("status") for v in tracker_data.values()]
    outcomes = [v.get("outcome", "Waiting") for v in tracker_data.values() if v.get("status") == "applied"]
    applied = len(outcomes)
    return [
        ("Saved", statuses.count("saved") + applied),
        ("Applied", applied),
        ("Heard back", sum(o != "Waiting" for o in outcomes)),
        ("Interview", sum(o in ("Interview", "Offer") for o in outcomes)),
        ("Offer", outcomes.count("Offer")),
    ]


def hide_reasons(tracker_data: dict[str, dict]) -> list[tuple[str, int]]:
    counts = Counter(v.get("reason") or "No reason given" for v in tracker_data.values()
                     if v.get("status") == "hidden")
    return counts.most_common()


def applications_per_week(tracker_data: dict[str, dict], weeks: int = 8, today: date | None = None) -> list[tuple[str, int]]:
    """Applications per week for the last ``weeks`` weeks, oldest first, labelled by the Monday."""
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    starts = [this_monday - timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]
    counts = Counter()
    for v in tracker_data.values():
        if v.get("status") == "applied" and v.get("at"):
            day = datetime.fromisoformat(v["at"]).date()
            counts[day - timedelta(days=day.weekday())] += 1
    return [(f"{s:%b %d}", counts.get(s, 0)) for s in starts]
