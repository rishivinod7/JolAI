"""Helpers shared by the job sources."""

from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup

REMOTE_RE = re.compile(r"\b(remote|anywhere|work from home|wfh|distributed)\b", re.I)


def html_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    # Some APIs (Greenhouse) double-encode their HTML.
    if "&lt;" in raw and "<" not in raw:
        raw = html.unescape(raw)
    soup = BeautifulSoup(raw, "html.parser")
    for br in soup.find_all(["br", "p", "li", "div", "h1", "h2", "h3", "h4"]):
        br.insert_after("\n")
    text = soup.get_text()
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t\xa0]+", " ", text)).strip()


def looks_remote(*values: str | None) -> bool:
    return any(v and REMOTE_RE.search(v) for v in values)


def to_number(value) -> float | None:
    if value in (None, "", 0):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


SALARY_RE = re.compile(r"\$\s?(\d{2,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?\s?[kK])")


def parse_salary_range(text: str | None) -> tuple[float | None, float | None]:
    """Find a "$120k - $150k" or "$120,000-$150,000" style range in free text."""
    if not text:
        return None, None
    values = []
    for raw in SALARY_RE.findall(text)[:2]:
        raw = raw.replace(",", "").replace(" ", "")
        values.append(float(raw[:-1]) * 1000 if raw[-1] in "kK" else float(raw))
    values = [v for v in values if 10_000 <= v <= 2_000_000]
    if not values:
        return None, None
    return min(values), max(values)
