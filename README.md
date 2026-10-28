# JolAI

JolAI is a job finder that starts from your resume. It scrapes job boards, then ranks each posting on two
things: how likely you are to get it (**chance**) and how close it is to what you're looking for (**want**).
It writes the results to the terminal, a standalone HTML report, CSV and JSON.

```
┏━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ # ┃ Score ┃ Chance ┃ Want ┃ Role                              ┃ Company  ┃ Location      ┃ Why                                         ┃
┡━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1 │    90 │     93 │   86 │ Senior Backend Engineer, Payments │ Stripe   │ New York, NY  │ title matches; mentions fintech; 6/6 skills │
│ 2 │    78 │     78 │   79 │ Platform Engineer                 │ palantir │ Remote - US   │ title matches; 5/5 listed skills match      │
│ … │       │        │      │                                   │          │               │                                             │
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .                 # or: pip install -e '.[llm]' to enable the Claude re-rank
cp config.example.yaml config.yaml
# put your resume next to it (resume.pdf / .docx / .txt are git-ignored) and edit config.yaml

jolai profile                    # check what was read from your resume
jolai search                     # scrape, rank, and write results/report.html
```

Useful flags for `jolai search`:

| Flag | What it does |
|---|---|
| `--llm` | Re-rank the top matches with Claude (see below) |
| `--new-only` | Hide jobs you were shown in earlier runs, handy when you run it daily |
| `-n 50` | Print the top 50 instead of 25 (the files always hold every match) |
| `--min-score 60` | Drop weak matches |
| `--jobs-file results/jobs.json` | Re-score the last scrape without hitting the network, e.g. after changing preferences |
| `--no-cache` | Skip the 6-hour HTTP cache |

## Where jobs come from

| Source | Config key | Notes |
|---|---|---|
| Greenhouse | `greenhouse: [board, …]` | Public board API. The board is the last part of `boards.greenhouse.io/<board>` |
| Lever | `lever: [board, …]` | `jobs.lever.co/<board>` |
| Ashby | `ashby: [board, …]` | `jobs.ashbyhq.com/<board>` |
| Any careers page | `career_pages: [url, …]` | Reads schema.org `JobPosting` JSON-LD, which most career sites publish for Google Jobs. Follows same-site job links (up to 40 pages) and respects `robots.txt` |
| Remotive | `remotive: true` | Searched with your target titles |
| RemoteOK | `remoteok: true` | |
| Hacker News | `hackernews: true` | Parses the latest "Ask HN: Who is hiring?" thread |

LinkedIn, Indeed and Glassdoor are left out on purpose. Their terms forbid scraping and they block it
quickly. Most companies you'd find there post the same roles on one of the boards above, so add those
companies' boards instead.

All requests go through a polite client (`jolai/http.py`). It sends an identifying User-Agent, waits at
least 1 s between requests to the same host, retries with backoff, and caches responses for 6 hours.

## How ranking works

The resume parser (`jolai/resume.py`) finds:
- **skills**, using a vocabulary of about 120 skills with aliases (`jolai/skills.py`)
- **years of experience**, by merging the date ranges in your work history
- **titles**, and from those plus your years, a **level** (intern, entry, mid, senior, staff, principal)

Each job then gets these scores (`jolai/matcher.py`):

- **Chance** (likelihood of getting it):
  - 35% text similarity: TF-IDF cosine between your resume and the posting, relative to the best match
  - 35% skill coverage: the share of the skills the posting mentions that are on your resume
  - 30% seniority fit: the posting's level against yours, and its "N+ years" against your years.
    Reaching up one level is penalised a little, two levels a lot. People-management roles are
    penalised if you've never held one.
- **Want** (matches what you asked for): title similarity to `preferences.titles`, location or remote fit,
  your `keywords`, and `min_salary` when the posting lists pay. Preferences you leave blank are skipped,
  not guessed.
- **Score** = `chance_vs_want × chance + (1 − chance_vs_want) × want`. The default is 0.6. Raise it to see
  the roles you're most likely to land, lower it to see the ones you'd most like.

Hard filters (`exclude_*`, `remote_only`) drop jobs before scoring. The run prints how many each filter
removed.

### Optional: Claude re-rank

Keyword scoring can't tell a must-have skill from a nice-to-have, or credit transferable experience. With
`--llm` (or `llm.enabled: true`), the top `llm.top_n` heuristic matches are sent with your resume to Claude
(`claude-opus-5-5` by default). Claude returns a structured fit/want score, a one-line summary and up to three
gaps for each job, and those jobs are re-ordered by its score.

This needs `pip install -e '.[llm]'` and either `ANTHROPIC_API_KEY` or `ant auth login`. It costs API
credits: roughly one request per 10 jobs, each carrying your full resume and the job descriptions.

## Output

`results/` holds:
- `report.html`: cards with scores, reasons, and which skills you have (green) or are missing (orange)
- `matches.csv` and `matches.json`: every match with all its fields
- `jobs.json`: the raw scrape, for `--jobs-file`
- `seen.json`: the jobs already shown, for `--new-only`

## Development

```bash
pip install -e '.[llm,dev]'
pytest
```

The tests run every source parser against recorded fixtures in `tests/fixtures/`, so no network is needed.
