"""Optional second pass: ask Claude to re-rank the top heuristic matches.

The heuristic scorer is fast and free, but it can't read nuance (e.g. "Python" listed as a
nice-to-have vs. the core of the job, or transferable experience). This pass sends your
resume plus the top N postings to Claude and gets back a structured assessment per job.

It's off by default and costs a little per job (see README "Cost"), so it only looks at
the top few matches and remembers every answer it has already paid for.

Requires ``pip install 'jolai[llm]'`` and an ``ANTHROPIC_API_KEY`` (or ``ant auth login``).
"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path

from .models import Match

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You are an experienced technical recruiter helping a candidate decide which jobs to apply to.
For each job posting, judge two things from the candidate's resume and stated preferences:
- fit_score (0-100): how likely this candidate is to get an interview and offer. Weigh hard requirements
  (years, must-have skills, credentials, work authorization notes) far more than nice-to-haves, and give credit
  for clearly transferable experience.
- want_score (0-100): how well the role matches what the candidate says they want.
List as dealbreakers only things that rule the candidate out given their stated preferences or resume,
such as a required language they don't speak or a required license or degree they lack.
Be calibrated: a 90+ fit means the resume clearly meets every hard requirement. Keep the summary to one or two
sentences, written to the candidate ("you"). List at most three concrete gaps."""


@lru_cache(maxsize=1)
def _schema():
    from pydantic import BaseModel, Field

    class JobAssessment(BaseModel):
        job_id: str
        fit_score: int = Field(description="0-100 likelihood of landing the role")
        want_score: int = Field(description="0-100 match with the candidate's preferences")
        summary: str
        gaps: list[str]
        dealbreakers: list[str] = Field(description="hard blockers given the preferences, e.g. a required "
                                                    "language other than English; empty if none")

    class Assessments(BaseModel):
        jobs: list[JobAssessment]

    return Assessments


def _cache_key(match: Match, resume_text: str, preferences_note: str, model: str) -> str:
    """Same job + same resume + same preferences + same model -> reuse the earlier answer."""
    blob = "\x00".join([match.job.id, match.job.description, resume_text, preferences_note, model])
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def rerank(matches: list[Match], resume_text: str, preferences_note: str, top_n: int = 10,
           model: str = DEFAULT_MODEL, batch_size: int = 10, alpha: float = 0.6, effort: str = "low",
           cache_path: str | Path | None = None, cache_only: bool = False) -> list[Match]:
    """Send the top ``top_n`` matches to Claude in batches and re-order them by its scores.

    Cost control: answers are stored in ``cache_path`` and reused on later runs, so you only
    pay for jobs Claude hasn't seen yet with your current resume and preferences.
    """
    cache_file = Path(cache_path) if cache_path else None
    cache: dict = json.loads(cache_file.read_text()) if cache_file and cache_file.exists() else {}
    head, tail = matches[:top_n], matches[top_n:]
    keys = {m.job.id: _cache_key(m, resume_text, preferences_note, model) for m in head}
    todo = [m for m in head if keys[m.job.id] not in cache]

    if todo and not cache_only:
        import anthropic

        client = anthropic.Anthropic()
        schema = _schema()
        by_id = {m.job.id: m for m in todo}
        for start in range(0, len(todo), batch_size):
            batch = todo[start:start + batch_size]
            postings = "\n\n".join(
                f"<job id=\"{m.job.id}\">\nTitle: {m.job.title}\nCompany: {m.job.company}\n"
                f"Location: {m.job.location}{' (remote)' if m.job.remote else ''}\n\n{m.job.description}\n</job>"
                for m in batch
            )
            prompt = (f"<resume>\n{resume_text}\n</resume>\n\n<preferences>\n{preferences_note}\n</preferences>"
                      f"\n\n{postings}\n\nAssess every job above, using its id.")
            try:
                response = client.messages.parse(
                    model=model,
                    max_tokens=16000,
                    system=SYSTEM_PROMPT,
                    output_config={"effort": effort},
                    messages=[{"role": "user", "content": prompt}],
                    output_format=schema,
                )
            except anthropic.APIStatusError as exc:
                log.warning("Claude re-rank failed for batch starting at %d (HTTP %s): %s", start, exc.status_code, exc)
                continue
            except anthropic.APIConnectionError as exc:
                log.warning("Could not reach the Claude API: %s", exc)
                break
            if response.stop_reason == "refusal" or response.parsed_output is None:
                log.warning("Claude declined or returned no assessment for batch starting at %d", start)
                continue
            for item in response.parsed_output.jobs:
                if item.job_id in by_id:
                    cache[keys[item.job_id]] = item.model_dump()
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    for match in head:
        item = cache.get(keys[match.job.id])
        if not item:
            continue
        fit = item["fit_score"]
        if item.get("dealbreakers"):
            fit = min(fit, 20)  # a dealbreaker (e.g. a required language you don't speak) caps the score
        match.llm_score = round(alpha * fit + (1 - alpha) * item["want_score"], 1)
        notes = [item["summary"]]
        if item.get("dealbreakers"):
            notes.append("Dealbreakers: " + "; ".join(item["dealbreakers"]) + ".")
        if item.get("gaps"):
            notes.append("Gaps: " + "; ".join(item["gaps"]) + ".")
        match.llm_summary = " ".join(notes)

    # Jobs Claude scored are ordered by its score; any it skipped keep their heuristic rank.
    head.sort(key=lambda m: m.llm_score if m.llm_score is not None else m.score, reverse=True)
    return head + tail
