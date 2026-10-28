"""Command-line entry point: ``jolai profile`` and ``jolai search``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import fields
from pathlib import Path

from rich.console import Console

from . import sources
from .config import DEFAULT_SOURCES, describe_preferences, load_config, preferences_from
from .http import Fetcher
from .matcher import score_jobs
from .models import Job
from .report import print_table, write_outputs
from .resume import LEVELS, load_profile

console = Console()


def _profile(args, config):
    resume_path = args.resume or config.get("resume")
    if not resume_path:
        sys.exit("No resume given. Pass --resume or set `resume:` in the config file.")
    prefs = config.get("preferences") or {}
    return load_profile(resume_path, extra_skills=prefs.get("extra_skills"),
                        years_override=prefs.get("years_experience"))


def _search_terms(config) -> list[str]:
    explicit = (config.get("sources") or {}).get("search_terms")
    if explicit:
        return list(explicit)
    return list(((config.get("preferences") or {}).get("titles") or [])[:3])


def cmd_profile(args) -> None:
    config = load_config(args.config)
    profile = _profile(args, config)
    console.print(f"[bold]Experience:[/bold] ~{profile.years_experience:g} years "
                  f"(reads as [bold]{LEVELS[profile.level]}[/bold] level)")
    console.print(f"[bold]Titles found:[/bold] {', '.join(profile.titles) or 'none'}")
    console.print(f"[bold]Skills found ({len(profile.skills)}):[/bold] {', '.join(sorted(profile.skills)) or 'none'}")
    console.print("\n[dim]If something is missing, add it under preferences.extra_skills / years_experience "
                  "in your config.[/dim]")


def cmd_search(args) -> None:
    config = load_config(args.config)
    profile = _profile(args, config)
    prefs = preferences_from(config)
    out_dir = Path(args.out or (config.get("output") or {}).get("dir") or "results")
    top = args.top or (config.get("output") or {}).get("top") or 25

    if args.jobs_file:
        raw = json.loads(Path(args.jobs_file).read_text(encoding="utf-8"))
        names = {f.name for f in fields(Job)}
        jobs = [Job(**{k: v for k, v in item.items() if k in names}) for item in raw]
        console.print(f"Loaded {len(jobs)} jobs from {args.jobs_file}")
    else:
        fetcher = Fetcher(cache_ttl=0 if args.no_cache else 6 * 3600)
        source_cfg = config.get("sources") or DEFAULT_SOURCES

        def report(label, count, error):
            if error:
                console.print(f"  [red]✗[/red] {label}: {error}")
            else:
                console.print(f"  [green]✓[/green] {label}: {count} jobs")

        console.print("[bold]Collecting jobs…[/bold]")
        jobs = sources.collect(fetcher, source_cfg, _search_terms(config), on_result=report)
        console.print(f"{len(jobs)} unique jobs collected.")
        (out_dir).mkdir(parents=True, exist_ok=True)
        (out_dir / "jobs.json").write_text(json.dumps([vars(j) for j in jobs], indent=2), encoding="utf-8")

    seen_path = out_dir / "seen.json"
    seen = set(json.loads(seen_path.read_text())) if seen_path.exists() else set()
    if args.new_only:
        before = len(jobs)
        jobs = [j for j in jobs if j.id not in seen]
        console.print(f"Skipping {before - len(jobs)} jobs you've already been shown.")

    matches, filtered = score_jobs(profile, jobs, prefs)
    if filtered:
        console.print("Filtered out: " + ", ".join(f"{n} {why}" for why, n in sorted(filtered.items(), key=lambda x: -x[1])))
    if args.min_score:
        matches = [m for m in matches if m.score >= args.min_score]

    llm_cfg = config.get("llm") or {}
    if args.llm or llm_cfg.get("enabled"):
        from .llm import DEFAULT_MODEL, rerank

        n = int(llm_cfg.get("top_n", 20))
        console.print(f"Asking Claude to re-rank the top {min(n, len(matches))} matches…")
        try:
            matches = rerank(matches, profile.text, describe_preferences(prefs), top_n=n,
                             model=llm_cfg.get("model", DEFAULT_MODEL), alpha=prefs.alpha)
        except ImportError:
            console.print("[yellow]Install the LLM extra first: pip install 'jolai[llm]'[/yellow]")

    shown = matches[:top]
    print_table(shown, console)
    paths = write_outputs(matches, profile, out_dir)
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(sorted(seen | {m.job.id for m in shown})), encoding="utf-8")
    console.print(f"\nFull results: {paths['html']}  ({paths['csv'].name}, {paths['json'].name})")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jolai", description="Find jobs that fit your resume.")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-r", "--resume", help="resume file (.pdf, .docx, .txt, .md)")
    common.add_argument("-c", "--config", default="config.yaml" if Path("config.yaml").exists() else None,
                        help="YAML config (default: ./config.yaml if present)")

    p = sub.add_parser("profile", parents=[common], help="show what JolAI read from your resume")
    p.set_defaults(func=cmd_profile)

    s = sub.add_parser("search", parents=[common], help="scrape job sources and rank them")
    s.add_argument("-n", "--top", type=int, help="how many matches to print (default 25)")
    s.add_argument("-o", "--out", help="output directory (default: results)")
    s.add_argument("--llm", action="store_true", help="re-rank the top matches with Claude")
    s.add_argument("--new-only", action="store_true", help="hide jobs shown in earlier runs")
    s.add_argument("--min-score", type=float, help="drop matches scoring below this")
    s.add_argument("--no-cache", action="store_true", help="ignore the 6h HTTP cache")
    s.add_argument("--jobs-file", help="score jobs from a saved jobs.json instead of scraping")
    s.set_defaults(func=cmd_search)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.ERROR, format="%(levelname)s %(message)s")
    args.func(args)


if __name__ == "__main__":
    main()
