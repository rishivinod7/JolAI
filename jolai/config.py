"""Load and save the YAML config file (config.yaml). The UI and the CLI share it."""

from __future__ import annotations

from pathlib import Path

import yaml

from .matcher import Preferences

DEFAULT_SOURCES = {"remotive": True, "remoteok": True, "hackernews": True}

# "max_technical" can be written as a word in the config; these are the cut-offs on the 0-100 scale.
TECHNICAL_LIMITS = {"low": 34, "medium": 64, "any": None, "high": None}


def load_config(path: str | Path | None) -> dict:
    if not path or not Path(path).exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_config(config: dict, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(config, fh, sort_keys=False, allow_unicode=True)


def _technical_limit(value) -> int | None:
    if value is None or isinstance(value, int):
        return value
    return TECHNICAL_LIMITS.get(str(value).lower())


def preferences_from(config: dict) -> Preferences:
    """Turn the ``preferences`` and ``weights`` sections into a Preferences object."""
    p = config.get("preferences") or {}
    weights = config.get("weights") or {}
    return Preferences(
        titles=list(p.get("titles") or []),
        locations=list(p.get("locations") or []),
        remote=bool(p.get("remote", True)),
        remote_only=bool(p.get("remote_only", False)),
        keywords=list(p.get("keywords") or []),
        exclude_keywords=list(p.get("exclude_keywords") or []),
        exclude_title_keywords=list(p.get("exclude_title_keywords") or []),
        exclude_companies=list(p.get("exclude_companies") or []),
        min_salary=p.get("min_salary"),
        english_only=bool(p.get("english_only", False)),
        languages_spoken=list(p.get("languages_spoken") or []),
        work_permits=list(p.get("work_permits") or []),
        open_to_sponsorship=bool(p.get("open_to_sponsorship", True)),
        hide_unclear_sponsorship=bool(p.get("hide_unclear_sponsorship", False)),
        max_years=p.get("max_years"),
        max_level=p.get("max_level"),
        max_technical=_technical_limit(p.get("max_technical")),
        alpha=float(weights.get("chance_vs_want", 0.6)),
    )


def describe_preferences(prefs: Preferences) -> str:
    """Plain-language summary of preferences, used in the AI prompt."""
    lines = []
    if prefs.titles:
        lines.append("Target titles: " + ", ".join(prefs.titles))
    if prefs.locations:
        lines.append("Locations: " + ", ".join(prefs.locations))
    lines.append("Remote: " + ("required" if prefs.remote_only else "fine" if prefs.remote else "not wanted"))
    if prefs.keywords:
        lines.append("Interested in: " + ", ".join(prefs.keywords))
    if prefs.min_salary:
        lines.append(f"Minimum salary: ${prefs.min_salary:,.0f}")
    if prefs.english_only:
        spoken = ", ".join(["English"] + prefs.languages_spoken)
        lines.append(f"Speaks only {spoken}: any other required language is a dealbreaker.")
    if prefs.work_permits:
        lines.append("Can already work in: " + ", ".join(prefs.work_permits) + ". " +
                     ("Elsewhere they need visa sponsorship; a posting that rules out sponsorship or requires "
                      "existing local work rights is a dealbreaker." if prefs.open_to_sponsorship else
                      "Not open to other countries."))
    if prefs.max_years is not None:
        lines.append(f"Wants roles asking for at most {prefs.max_years} years of experience.")
    if prefs.max_technical is not None:
        lines.append("Wants roles that are not very technical (little or no coding).")
    return "\n".join(lines) or "No stated preferences."
