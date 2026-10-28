"""Command-line entry point: ``jolai ui``, ``jolai profile`` and ``jolai search``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from rich.console import Console

from . import pipeline
from .config import load_config
from .report import print_table, write_outputs
from .resume import LEVELS

console = Console()


def _profile(args, config):
    try:
        return pipeline.read_profile(config, resume_path=args.resume)
    except ValueError as exc:
        sys.exit(str(exc))


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
    if args.out:
        config.setdefault("output", {})["dir"] = args.out
    profile = _profile(args, config)
    out_dir = pipeline.results_dir(config)
    top = args.top or (config.get("output") or {}).get("top") or 25

    if args.jobs_file:
        jobs = pipeline.load_jobs(args.jobs_file)
        console.print(f"Loaded {len(jobs)} jobs from {args.jobs_file}")
    else:
        def report(label, count, error):
            if error:
                console.print(f"  [red]✗[/red] {label}: {error}")
            else:
                console.print(f"  [green]✓[/green] {label}: {count} jobs")

        console.print("[bold]Collecting jobs…[/bold]")
        jobs = pipeline.collect_jobs(config, use_cache=not args.no_cache, on_progress=report)
        console.print(f"{len(jobs)} unique jobs collected.")

    seen_path = out_dir / "seen.json"
    seen = set(json.loads(seen_path.read_text())) if seen_path.exists() else set()
    if args.new_only:
        before = len(jobs)
        jobs = [j for j in jobs if j.id not in seen]
        console.print(f"Skipping {before - len(jobs)} jobs you've already been shown.")

    matches, filtered = pipeline.rank(profile, jobs, config)
    if filtered:
        console.print("Filtered out: " + ", ".join(f"{n} {why}" for why, n in sorted(filtered.items(), key=lambda x: -x[1])))
    if args.min_score:
        matches = [m for m in matches if m.score >= args.min_score]

    if args.llm or (config.get("llm") or {}).get("enabled"):
        console.print("Asking Claude to double-check the top matches…")
        try:
            matches = pipeline.ai_rerank(matches, profile, config)
        except ImportError:
            console.print("[yellow]Install the LLM extra first: pip install 'jolai[llm]'[/yellow]")

    shown = matches[:top]
    print_table(shown, console)
    paths = write_outputs(matches, profile, out_dir)
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(sorted(seen | {m.job.id for m in shown})), encoding="utf-8")
    console.print(f"\nFull results: {paths['html']}  ({paths['csv'].name}, {paths['json'].name})")


def cmd_ui(args) -> None:
    """Start the web UI (Streamlit) in your browser."""
    from streamlit.web import cli as stcli

    ui_file = str(Path(__file__).with_name("ui.py"))
    sys.argv = ["streamlit", "run", ui_file, "--server.port", str(args.port), "--client.toolbarMode", "minimal",
                "--browser.gatherUsageStats", "false", "--", "--config", args.config or "config.yaml"]
    sys.exit(stcli.main())


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

    u = sub.add_parser("ui", parents=[common], help="open the web UI in your browser")
    u.add_argument("--port", type=int, default=8501)
    u.set_defaults(func=cmd_ui)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.ERROR, format="%(levelname)s %(message)s")
    args.func(args)


if __name__ == "__main__":
    main()
