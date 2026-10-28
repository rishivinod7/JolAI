"""Load the YAML config file."""

from __future__ import annotations

from pathlib import Path

import yaml

from .matcher import Preferences

DEFAULT_SOURCES = {"remotive": True, "remoteok": True, "hackernews": True}


def load_config(path: str | Path | None) -> dict:
    if not path:
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def preferences_from(config: dict) -> Preferences:
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
        alpha=float(weights.get("chance_vs_want", 0.6)),
    )


def describe_preferences(prefs: Preferences) -> str:
    """Plain-language summary of preferences, used in the LLM prompt."""
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
    return "\n".join(lines) or "No stated preferences."
