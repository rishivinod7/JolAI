# How JolAI works

This is the 5-minute tour of the code. Every file also starts with a short comment saying what it does.

## The big picture

A search goes through four steps. `jolai/pipeline.py` runs them in order, and both the web UI
and the command line call it, so they always behave the same.

```
 ┌────────────┐   ┌───────────────┐   ┌───────────────────┐   ┌──────────────────┐
 │ 1. Resume  │──►│ 2. Collect    │──►│ 3. Filter + score │──►│ 4. AI check      │
 │ resume.py  │   │ sources/      │   │ filters.py        │   │ llm.py           │
 │            │   │ http.py       │   │ matcher.py        │   │ (optional, paid) │
 └────────────┘   └───────────────┘   └───────────────────┘   └──────────────────┘
   your skills,     jobs from job       drop jobs you said        Claude re-checks
   years, level     boards & sites      you don't want, then      the top few
                                        score the rest 0-100
```

The results are shown by `ui.py` (the web page) or `report.py` (terminal table, HTML, CSV and JSON).

## 1. Reading your resume (`resume.py`, `skills.py`)

- **Text**: PDFs are read with `pypdf` and Word files with `python-docx`.
- **Skills**: `skills.py` has a list of about 120 skills, each with other ways people write it
  ("customer support", "help desk" → *Customer Service*). Any of those found in your resume count.
- **Sections**: headings like EXPERIENCE, EDUCATION and PROJECTS split the resume up.
- **Years of experience**: every date range like "Mar 2023 – Present" *in the work section* is found,
  and the ranges are added up with overlaps counted once. Degree and project dates are ignored.
- **Titles**: the first part of each work line ("Senior Associate – UX Design | Company | Dates").
- **Level**: worked out from your years, bumped up if a title says Senior, Lead and so on:
  intern → entry → mid → senior → staff → principal.

If something comes out wrong, fix it in the UI sidebar ("Fix what was read from your resume").

## 2. Collecting jobs (`sources/`, `http.py`)

Each file in `sources/` knows how to read one kind of site and turns it into the same `Job` shape
(title, company, location, description, salary…), defined in `models.py`:

| File | Reads |
|---|---|
| `ats.py` | Greenhouse, Lever and Ashby, the systems most companies use for their careers pages |
| `aggregators.py` | Remotive, RemoteOK, Hacker News "Who is hiring?" |
| `careers.py` | Any careers page that includes standard job data (schema.org `JobPosting`) |

`sources/__init__.py` runs them all at once and removes duplicates. `http.py` keeps the scraping
polite: it waits between requests to the same site, follows `robots.txt`, retries failures and
keeps downloaded pages for 6 hours so repeat searches don't hit sites again.

## 3. Filtering and scoring (`filters.py`, `matcher.py`)

First, `filters.py` reads each posting and works out:
- **languages**: which non-English languages are *required* ("fluent German", "French is
  required", or a posting written in German) and which are only *a plus*
- **how technical** it is, 0–100: an engineering-style title, how many technical tools it lists,
  and words like "coding" or "system design". Business tools (Power BI, Excel, Jira…) don't count.
- **whether you can work there**, if you've set the countries you hold work permits for:
  - *ok*: the job is in one of them, or is remote for a region that includes them (e.g. APAC)
  - *sponsors*: elsewhere, but the posting mentions visa sponsorship or relocation support
  - *unclear*: elsewhere, and the posting doesn't say (most postings don't)
  - *blocked*: elsewhere, and the posting says "no sponsorship" or "must have the right to work in…"

`matcher.py` adds the **level** from the title and the **years** asked for ("3+ years of
experience"). Then `excluded()` drops jobs that break one of your rules: a language you don't speak,
too technical, too many years, too senior, won't sponsor your visa, hidden words or companies.
Jobs where sponsorship is *unclear* stay, but score lower on "want" and carry a yellow badge.

Every remaining job gets two scores:
- **Chance**, how likely you are to get it:
  - 35% how similar the posting's wording is to your resume
  - 35% how many of the skills it lists you have
  - 30% whether its level and years fit yours
- **Want**, how close it is to what you asked for: title, location or remote, topics, salary.

The final score mixes the two using the "Rank by" slider (`chance_vs_want` in the config).

## 4. AI double-check (`llm.py`), optional

Rules can't catch everything, like a must-have certificate or a role whose title says
"coordinator" but is really sales. When you click the button, the top few matches and your resume
go to Claude. It returns a score, a short summary and any dealbreakers for each job.

To keep this cheap:
- it only looks at your top N jobs (10 by default)
- it uses low effort
- every answer is saved in `results/ai_cache.json`, so the same job is never paid for twice

## Where things are saved

All in `results/` (git-ignored):

| File | What |
|---|---|
| `jobs.json` | the last download; the UI re-scores from this when you change settings |
| `tracker.json` | jobs you saved, applied to or hid |
| `ai_cache.json` | AI answers already paid for |
| `matches.*`, `report.html` | the export from `jolai search` |

## Changing things

| I want to… | Edit |
|---|---|
| Recognise a new skill | add it to `SKILLS` in `skills.py` |
| Catch another way postings phrase language rules | `REQUIRED_PATTERNS` / `_SOFT` in `filters.py` |
| Recognise a city or country, or sponsorship wording | `COUNTRIES`, `SPONSORS_RE`, `NO_SPONSOR_RE` in `filters.py` |
| Change what counts as "technical" | `technical_score` in `filters.py` |
| Change how scores are weighted | `score_jobs` in `matcher.py` |
| Add a job site | a new function in `sources/` returning `list[Job]`, then register it in `sources/__init__.py` |
| Change the page layout | `ui.py` (it's [Streamlit](https://docs.streamlit.io), plain Python) |

Run `pytest` after a change. The tests use saved sample data in `tests/fixtures/`, so they need no internet.
