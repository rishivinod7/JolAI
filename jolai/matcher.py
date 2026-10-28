"""Score jobs against a candidate profile.

Two scores are computed per job, then blended:

* **chance**: how likely you are to land it. Built from text similarity to your resume,
  coverage of the skills the posting asks for, and seniority/years-of-experience fit.
* **want**: how well it matches your stated preferences (titles, locations/remote,
  keywords, salary).

``overall = alpha * chance + (1 - alpha) * want``, with ``alpha`` set in the config.

Before scoring, ``excluded`` drops jobs that break a hard rule you set: wrong company,
unwanted title words, another language required, too technical, too many years asked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .filters import language_requirements, technical_score, work_authorization
from .models import Job, Match, Profile
from .resume import LEVELS
from .skills import extract_skills

LEVEL_PATTERNS = [
    (0, r"\bintern(ship)?\b|\bco-?op\b"),
    (5, r"\b(principal|distinguished|fellow)\b"),
    (4, r"\bstaff\b|\bhead of\b|\bdirector\b|\bvp\b|\bvice president\b|\bchief\b"),
    (3, r"\b(senior|sr\.?|lead)\b|\b(engineer|developer)\s+(iii|3)\b"),
    (1, r"\b(junior|jr\.?|entry[- ]level|new grad(uate)?|graduate|associate)\b|\b(engineer|developer)\s+(i|1)\b"),
]
MANAGEMENT_RE = re.compile(r"\b(manager|director|head of|vp|vice president)\b", re.I)
PEOPLE_MGMT_RE = re.compile(r"direct reports|people management|manag(e|ing) a team|lead(ing)? a team of|"
                            r"build(ing)? (and lead(ing)? )?a team|hire and (develop|manage)|line management", re.I)
YEARS_REQ_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*(?:\d{1,2})?\s*\+?\s*(?:years|yrs)", re.I)
TITLE_NOISE = {"senior", "sr", "junior", "jr", "staff", "principal", "lead", "i", "ii", "iii", "iv", "the", "of",
               "and", "remote", "hybrid", "contract", "full", "time", "part", "new", "grad"}


@dataclass
class Preferences:
    titles: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    remote: bool = True
    remote_only: bool = False
    keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    exclude_title_keywords: list[str] = field(default_factory=list)
    exclude_companies: list[str] = field(default_factory=list)
    min_salary: float | None = None
    english_only: bool = False  # drop jobs that require another language
    languages_spoken: list[str] = field(default_factory=list)  # other languages you speak; these never filter
    work_permits: list[str] = field(default_factory=list)  # countries you can already work in
    open_to_sponsorship: bool = True  # keep jobs elsewhere if they sponsor visas (or don't say)
    hide_unclear_sponsorship: bool = False  # elsewhere + posting doesn't mention sponsorship -> drop
    max_years: int | None = None  # drop jobs asking for more years than this
    max_level: str | None = None  # drop titles above this level, e.g. "mid" drops senior/staff/principal
    max_technical: int | None = None  # drop jobs whose technical score (0-100) is above this
    alpha: float = 0.6  # weight of "chance" vs "want"


@dataclass
class JobFacts:
    """What we read out of a posting before scoring it. Shown in the UI as badges."""

    level: int
    years_required: int | None
    languages_required: list[str]
    languages_optional: list[str]
    technical: int
    work_authorization: str | None = None  # "ok", "sponsors", "unclear", "blocked" (None = no permits set)


def read_job(job: Job, prefs: Preferences | None = None) -> JobFacts:
    required, optional = language_requirements(job.description)
    permits = prefs.work_permits if prefs else []
    return JobFacts(
        level=job_level(job.title),
        years_required=years_required(job.description),
        languages_required=required,
        languages_optional=optional,
        technical=technical_score(job.title, job.description),
        work_authorization=work_authorization(job.location, job.remote, job.description, permits)
        if permits else None,
    )


def job_level(title: str) -> int:
    for level, pattern in LEVEL_PATTERNS:
        if re.search(pattern, title, re.I):
            return level
    return 2


def years_required(text: str) -> int | None:
    """Smallest 'N+ years' requirement mentioned near the word experience."""
    found = []
    for m in YEARS_REQ_RE.finditer(text):
        window = text[m.end(): m.end() + 60].lower()
        if "experience" in window or "exp" in window[:10]:
            years = int(m.group(1))
            if 0 < years <= 20:
                found.append(years)
    return min(found) if found else None


def _title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9+#]+", title.lower())
    return {w for w in words if w not in TITLE_NOISE}


def title_similarity(job_title: str, wanted: list[str]) -> float:
    job_tokens = _title_tokens(job_title)
    best = 0.0
    for want in wanted:
        want_tokens = _title_tokens(want)
        if want_tokens and job_tokens:
            best = max(best, len(job_tokens & want_tokens) / len(want_tokens))
    return best


def excluded(job: Job, facts: JobFacts, prefs: Preferences) -> str | None:
    """Return why a job breaks one of your hard rules, or None if it's fine."""
    text = job.text.lower()
    title = job.title.lower()
    if any(c.lower() == job.company.lower() for c in prefs.exclude_companies):
        return "excluded company"
    for kw in prefs.exclude_title_keywords:
        if re.search(rf"\b{re.escape(kw.lower())}\b", title):
            return f"title contains '{kw}'"
    for kw in prefs.exclude_keywords:
        if kw.lower() in text:
            return f"mentions '{kw}'"
    if prefs.remote_only and not job.remote:
        return "not remote"
    spoken = {lang.strip().title() for lang in prefs.languages_spoken}
    if prefs.english_only and set(facts.languages_required) - spoken:
        return "needs a language you don't speak"
    auth = facts.work_authorization
    if auth == "blocked":
        return "won't sponsor a visa"
    if auth in {"sponsors", "unclear"} and not prefs.open_to_sponsorship:
        return "outside the countries you can work in"
    if auth == "unclear" and prefs.hide_unclear_sponsorship:
        return "doesn't say if it sponsors visas"
    if prefs.max_years is not None and facts.years_required and facts.years_required > prefs.max_years:
        return "asks for too many years"
    if prefs.max_level and prefs.max_level in LEVELS and facts.level > LEVELS.index(prefs.max_level):
        return "too senior"
    if prefs.max_technical is not None and facts.technical > prefs.max_technical:
        return "too technical"
    return None


def _seniority_fit(profile: Profile, job: Job, facts: JobFacts) -> tuple[float, list[str]]:
    """How well the posting's level and years requirement fit yours (0-1), with reasons."""
    reasons = []
    # "Partnerships Manager" is usually an individual role; only count it as managing people when
    # the title is director-level or the posting talks about leading a team.
    is_mgmt = bool(re.search(r"\b(director|head of|vp|vice president|chief)\b", job.title, re.I)) or (
        bool(MANAGEMENT_RE.search(job.title)) and bool(PEOPLE_MGMT_RE.search(job.description)))
    level = facts.level
    diff = level - profile.level
    level_score = {0: 1.0, -1: 0.85, 1: 0.6, -2: 0.55, 2: 0.25}.get(diff, 0.05)
    if diff >= 1:
        reasons.append(f"title is {LEVELS[level]}-level, you read as {LEVELS[profile.level]}")
    elif diff <= -2:
        reasons.append(f"{LEVELS[level]}-level role may be below your experience")
    if is_mgmt and not profile.has_management:
        level_score *= 0.5
        reasons.append("people-management role; no management titles on your resume")

    required = facts.years_required
    if required is None:
        years_score = 0.8
    else:
        gap = required - profile.years_experience
        years_score = 1.0 if gap <= 0 else max(0.0, 1 - gap / 4)
        if gap > 0:
            reasons.append(f"asks for {required}+ yrs, you have ~{profile.years_experience:g}")
    return 0.5 * level_score + 0.5 * years_score, reasons


def _location_fit(job: Job, prefs: Preferences, facts: JobFacts) -> float | None:
    """1.0 = somewhere you can and want to work; lower for visa uncertainty or unwanted places."""
    auth = {"ok": 1.0, "sponsors": 0.85, "unclear": 0.45}.get(facts.work_authorization or "", None)
    if not prefs.locations and not prefs.remote_only:
        return auth
    if job.remote and (prefs.remote or prefs.remote_only):
        return 1.0
    loc = job.location.lower()
    if any(p.lower() in loc for p in prefs.locations if p.lower() != "remote"):
        return 1.0 if auth is None else auth
    return 0.15 if auth is None else min(auth, 0.6)


@dataclass
class Rejected:
    """A job a filter removed, kept so you can check the filter got it right."""

    job: Job
    facts: JobFacts
    reason: str


def score_jobs(profile: Profile, jobs: list[Job], prefs: Preferences, keep_ids: set[str] | None = None,
               rejected: list[Rejected] | None = None) -> tuple[list[Match], dict[str, int]]:
    """Return matches sorted best-first, plus a count of why jobs were filtered out.

    ``keep_ids``: jobs you said a filter was wrong about. They skip the filters and are scored
    like any other job, with ``Match.overridden`` set to the filter they would have failed.
    ``rejected``: if given, every filtered-out job is appended to it with its reason.
    """
    filtered: dict[str, int] = {}
    kept: list[Job] = []
    facts_by_id: dict[str, JobFacts] = {}
    overridden: dict[str, str] = {}
    for job in jobs:
        facts = read_job(job, prefs)
        reason = excluded(job, facts, prefs)
        if reason and keep_ids and job.id in keep_ids:
            overridden[job.id] = reason
            reason = None
        if reason:
            filtered[reason] = filtered.get(reason, 0) + 1
            if rejected is not None:
                rejected.append(Rejected(job, facts, reason))
        else:
            kept.append(job)
            facts_by_id[job.id] = facts
    if not kept:
        return [], filtered

    vectorizer = TfidfVectorizer(stop_words="english", sublinear_tf=True, ngram_range=(1, 2),
                                 max_features=50_000, min_df=1)
    matrix = vectorizer.fit_transform([profile.text] + [j.text for j in kept])
    sims = cosine_similarity(matrix[0], matrix[1:]).ravel()
    top_sim = max(float(sims.max()), 1e-9)

    wanted_titles = prefs.titles or profile.titles
    matches = []
    for job, sim in zip(kept, sims):
        reasons: list[str] = []
        semantic = float(sim) / top_sim  # relative to the best match in this batch

        job_skills = extract_skills(job.text)
        matched = sorted(job_skills & profile.skills)
        missing = sorted(job_skills - profile.skills)
        skill_score = len(matched) / len(job_skills) if job_skills else 0.5

        facts = facts_by_id[job.id]
        seniority, seniority_reasons = _seniority_fit(profile, job, facts)
        reasons += seniority_reasons
        chance = 0.35 * semantic + 0.35 * skill_score + 0.30 * seniority

        # "want" components; ones you didn't configure are left out instead of guessed.
        parts: list[tuple[float, float]] = []
        if wanted_titles:
            title_score = title_similarity(job.title, wanted_titles)
            parts.append((0.5, title_score))
            if title_score >= 0.99:
                reasons.insert(0, "title matches what you're looking for")
        location_score = _location_fit(job, prefs, facts)
        if location_score is not None:
            parts.append((0.25, location_score))
            if facts.work_authorization == "sponsors":
                reasons.append("says it sponsors visas or helps with relocation")
            elif facts.work_authorization == "unclear":
                reasons.append("outside your work-permit countries; doesn't say if it sponsors visas")
            elif location_score < 0.5:
                reasons.append(f"location '{job.location or 'unknown'}' isn't in your list")
        if prefs.keywords:
            text = job.text.lower()
            hits = [k for k in prefs.keywords if k.lower() in text]
            parts.append((0.25, min(1.0, len(hits) / max(1, min(3, len(prefs.keywords))))))
            if hits:
                reasons.append("mentions " + ", ".join(hits))
        # Only compare pay in USD; the minimum you set isn't converted between currencies.
        if prefs.min_salary and (job.salary_max or job.salary_min) and job.salary_currency in (None, "USD"):
            top = job.salary_max or job.salary_min
            parts.append((0.2, 1.0 if top >= prefs.min_salary else 0.2))
            if top < prefs.min_salary:
                reasons.append(f"pay tops out at ${top:,.0f}")
        want = sum(w * s for w, s in parts) / sum(w for w, _ in parts) if parts else chance

        overall = prefs.alpha * chance + (1 - prefs.alpha) * want
        if matched:
            reasons.append(f"{len(matched)}/{len(job_skills)} listed skills match")
        if facts.languages_optional:
            reasons.append(f"{', '.join(facts.languages_optional)} is a plus, not required")
        matches.append(Match(job=job, score=round(overall * 100, 1), chance=round(chance * 100, 1),
                             want=round(want * 100, 1), matched_skills=matched, missing_skills=missing,
                             reasons=reasons, facts=facts, overridden=overridden.get(job.id)))
    matches.sort(key=lambda m: m.score, reverse=True)
    return matches, filtered
