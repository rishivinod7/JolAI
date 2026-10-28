"""Optional second pass: ask Claude to re-rank the top heuristic matches.

The heuristic scorer is fast and free, but it can't read nuance (e.g. "Python" listed as a
nice-to-have vs. the core of the job, or transferable experience). This pass sends your
resume plus the top N postings to Claude and gets back a structured assessment per job.

Requires ``pip install 'jolai[llm]'`` and an ``ANTHROPIC_API_KEY`` (or ``ant auth login``).
"""

from __future__ import annotations

import logging
from functools import lru_cache

from .models import Match

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You are an experienced technical recruiter helping a candidate decide which jobs to apply to.
For each job posting, judge two things from the candidate's resume and stated preferences:
- fit_score (0-100): how likely this candidate is to get an interview and offer. Weigh hard requirements
  (years, must-have skills, credentials, work authorization notes) far more than nice-to-haves, and give credit
  for clearly transferable experience.
- want_score (0-100): how well the role matches what the candidate says they want.
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

    class Assessments(BaseModel):
        jobs: list[JobAssessment]

    return Assessments


def rerank(matches: list[Match], resume_text: str, preferences_note: str, top_n: int = 20,
           model: str = DEFAULT_MODEL, batch_size: int = 10, alpha: float = 0.6) -> list[Match]:
    import anthropic

    client = anthropic.Anthropic()
    schema = _schema()
    head, tail = matches[:top_n], matches[top_n:]
    by_id = {m.job.id: m for m in head}

    for start in range(0, len(head), batch_size):
        batch = head[start:start + batch_size]
        postings = "\n\n".join(
            f"<job id=\"{m.job.id}\">\nTitle: {m.job.title}\nCompany: {m.job.company}\n"
            f"Location: {m.job.location}{' (remote)' if m.job.remote else ''}\n\n{m.job.description}\n</job>"
            for m in batch
        )
        prompt = (f"<resume>\n{resume_text}\n</resume>\n\n<preferences>\n{preferences_note}\n</preferences>\n\n"
                  f"{postings}\n\nAssess every job above, using its id.")
        try:
            response = client.messages.parse(
                model=model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                output_config={"effort": "medium"},
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
            match = by_id.get(item.job_id)
            if match is None:
                continue
            match.llm_score = round(alpha * item.fit_score + (1 - alpha) * item.want_score, 1)
            gaps = f" Gaps: {'; '.join(item.gaps)}." if item.gaps else ""
            match.llm_summary = item.summary + gaps

    # Jobs Claude scored are ordered by its score; any it skipped keep their heuristic rank.
    head.sort(key=lambda m: m.llm_score if m.llm_score is not None else m.score, reverse=True)
    return head + tail
