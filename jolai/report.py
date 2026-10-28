"""Write results to the terminal, JSON, CSV and a standalone HTML report."""

from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .models import Match, Profile


def _row(m: Match) -> dict:
    j = m.job
    return {
        "id": j.id, "score": m.score, "chance": m.chance, "want": m.want, "llm_score": m.llm_score,
        "title": j.title, "company": j.company, "location": j.location, "remote": j.remote,
        "salary_min": j.salary_min, "salary_max": j.salary_max, "source": j.source, "url": j.url,
        "posted_at": j.posted_at, "matched_skills": m.matched_skills, "missing_skills": m.missing_skills,
        "reasons": m.reasons, "llm_summary": m.llm_summary,
    }


def print_table(matches: list[Match], console: Console | None = None) -> None:
    console = console or Console()
    table = Table(show_lines=False, header_style="bold")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("Chance", justify="right")
    table.add_column("Want", justify="right")
    table.add_column("Role")
    table.add_column("Company")
    table.add_column("Location")
    table.add_column("Why", overflow="fold", max_width=50)
    for i, m in enumerate(matches, 1):
        score = f"{m.llm_score:.0f}*" if m.llm_score is not None else f"{m.score:.0f}"
        why = m.llm_summary or "; ".join(m.reasons[:3])
        role = f"[link={m.job.url}]{m.job.title}[/link]" if m.job.url else m.job.title
        location = (m.job.location or "")[:30] + (" 🌐" if m.job.remote else "")
        table.add_row(str(i), score, f"{m.chance:.0f}", f"{m.want:.0f}", role, m.job.company, location, why)
    console.print(table)
    if any(m.llm_score is not None for m in matches):
        console.print("[dim]* score from Claude re-rank[/dim]")


def write_outputs(matches: list[Match], profile: Profile, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [_row(m) for m in matches]

    json_path = out / "matches.json"
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    csv_path = out / "matches.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["id"])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: "; ".join(v) if isinstance(v, list) else v for k, v in row.items()})

    html_path = out / "report.html"
    html_path.write_text(render_html(matches, profile), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "html": html_path}


def render_html(matches: list[Match], profile: Profile) -> str:
    e = html.escape
    cards = []
    for i, m in enumerate(matches, 1):
        j = m.job
        pay = ""
        if j.salary_min or j.salary_max:
            pay = " · $" + "–".join(f"{v:,.0f}" for v in dict.fromkeys(x for x in (j.salary_min, j.salary_max) if x))
        skills = "".join(f'<span class="chip ok">{e(s)}</span>' for s in m.matched_skills)
        skills += "".join(f'<span class="chip miss">{e(s)}</span>' for s in m.missing_skills)
        why = e(m.llm_summary) if m.llm_summary else "<br>".join(e(r) for r in m.reasons)
        score = m.llm_score if m.llm_score is not None else m.score
        cards.append(f"""
<article>
  <div class="score" title="overall">{score:.0f}</div>
  <div class="body">
    <h2>{i}. <a href="{e(j.url)}" target="_blank" rel="noopener">{e(j.title)}</a></h2>
    <p class="meta">{e(j.company)} · {e(j.location or 'Location n/a')}{' · remote' if j.remote else ''}{pay}
       · <span class="src">{e(j.source)}</span></p>
    <p class="bars">Chance <meter min="0" max="100" value="{m.chance}"></meter> {m.chance:.0f}
       &nbsp; Want <meter min="0" max="100" value="{m.want}"></meter> {m.want:.0f}</p>
    <p class="why">{why}</p>
    <p>{skills}</p>
  </div>
</article>""")
    skills = ", ".join(sorted(profile.skills)) or "none detected"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JolAI matches</title>
<style>
:root {{ --bg:#f7f7f5; --card:#fff; --ink:#1d1d1b; --muted:#6b6b66; --line:#e3e3de; --ok:#d8f0dc; --okink:#1e5b2a;
        --miss:#f6e3d6; --missink:#7a3b12; --accent:#2f5bd3; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#151514; --card:#1f1f1d; --ink:#eeeeea; --muted:#a3a39c;
        --line:#33332f; --ok:#1f3b25; --okink:#a8dfb3; --miss:#43291a; --missink:#f1c3a3; --accent:#8fb0ff; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui,sans-serif; }}
main {{ max-width:880px; margin:0 auto; padding:24px 16px; }}
header p {{ color:var(--muted); }}
article {{ display:flex; gap:16px; background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:16px; margin:12px 0; }}
.score {{ font-size:28px; font-weight:700; min-width:48px; text-align:center; color:var(--accent); }}
.body {{ min-width:0; }}
h2 {{ font-size:17px; margin:0 0 4px; }} a {{ color:var(--accent); }}
.meta, .bars {{ color:var(--muted); margin:2px 0; }} .src {{ font-family:ui-monospace,monospace; font-size:12px; }}
.why {{ margin:8px 0; }}
.chip {{ display:inline-block; padding:1px 8px; margin:2px; border-radius:99px; font-size:12px; }}
.ok {{ background:var(--ok); color:var(--okink); }} .miss {{ background:var(--miss); color:var(--missink); }}
</style></head><body><main>
<header><h1>Your job matches</h1>
<p>Generated {datetime.now():%Y-%m-%d %H:%M} · {len(matches)} roles · ~{profile.years_experience:g} yrs experience detected.
Green skills are on your resume, orange ones the posting asks for and your resume doesn't show.</p>
<p><strong>Skills detected:</strong> {e(skills)}</p></header>
{''.join(cards)}
</main></body></html>"""
