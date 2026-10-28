# JolAI

JolAI is a job finder that starts from your resume. It collects postings from job boards and
company careers pages, removes the ones that don't suit you, and ranks the rest on two things:
how likely you are to get the job (**chance**) and how close it is to what you want (**want**).

The filtering and ranking are free and run on your computer. AI is an optional extra you turn on
per search.

- **English only**: hides jobs that need another language; "German is a plus" stays, with a note
- **Not too technical**: rates every job from not technical to very technical, and lets you set a limit
- **Not too much experience**: hides jobs asking for more years, or a more senior level, than you choose
- **Work permits and visas**: tell it where you can already work. Jobs elsewhere are kept only if
  they don't rule out visa sponsorship, and they're marked "sponsors visas" or "sponsorship unclear"
- **Explains every match**: which of your skills fit, what's missing, and why it ranked where it did
- **Keeps track**: save, mark as applied (and what happened next), or hide jobs with a reason
- **Checks itself**: a *Filtered out* tab shows every hidden job and why, so you can spot filter
  mistakes. A *Stats* tab shows which sources work, which filters are too strict, whether
  your favourite jobs rank near the top, and your reply and interview rates

## Getting started

You need Python 3.10 or newer.

Mac / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
jolai ui
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
jolai ui
```

If PowerShell says "running scripts is disabled on this system", run
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once, then activate again.
Your prompt shows `(.venv)` when it's active. Activate again in each new terminal before `jolai ui`.

Your browser opens JolAI. Then:
1. Upload your resume (PDF, Word or text) in the sidebar.
2. Type the job titles you're after and set the filters.
3. Click **Search for jobs**. The first search takes a minute or two.
4. Change filters as much as you like. Results update instantly, without downloading again.
5. Click **Save settings** so they're remembered next time.

Your resume and results stay on your computer (`resume.*`, `config.yaml` and `results/` are
git-ignored).

## Finding more jobs

Out of the box JolAI searches **Remotive** and **RemoteOK**, both free and with many
non-technical remote roles.

**Search whole countries with Adzuna and Jooble (recommended).** These job search engines collect
listings from many job sites, through official APIs. Both are free, but you need a key:

| | Covers | Get a key |
|---|---|---|
| **Jooble** | Hong Kong, India, Singapore and most other countries | [jooble.org/api/about](https://jooble.org/api/about) |
| **Adzuna** | India, Singapore, UK, US, Australia, much of Europe (not Hong Kong) | [developer.adzuna.com](https://developer.adzuna.com/) |

In the UI, open **Where to look**, pick the countries or places, and paste the keys. They're saved
in `config.yaml`, which is git-ignored. Each search runs once per job title (up to 6) per place.
These sites only return a short summary of each job, so their scores lean more on the title.

Both have request limits: Jooble gives 500 per key by default; Adzuna gives 25 test calls, then
5,000 a month (500 a day) on its paid plan. JolAI counts every request, searches only your first
few titles on each (change this under **Where to look**), reuses results for 6 hours, and stops
before a limit. The Stats tab shows requests used, and how many jobs each source found that no
other source did ("only here"), which helps decide whether a paid plan is worth it.

**Add companies you like:**

1. Open its careers page and look at the address. If it's `boards.greenhouse.io/acme`,
   `jobs.lever.co/acme` or `jobs.ashbyhq.com/acme`, put `acme` in that box under **Where to look**.
2. Otherwise, paste the careers page address into **Other careers page URLs**. JolAI reads the
   job data most careers sites publish for Google.

LinkedIn, Indeed and Glassdoor are not supported. Their terms forbid scraping and they block it.

## Cost

| What | Cost |
|---|---|
| Searching, filtering, ranking | Free |
| AI double-check (optional) | Rough estimates for 10 jobs: **under $0.01** with `claude-haiku-5-5`, about **$0.05** with `claude-sonnet-5-5`, about **$0.10** with `claude-opus-5-5` (the default) |

The UI shows an estimate before you run the AI check. Each job is only ever sent once, because
answers are saved. To use it, install `pip install -e '.[llm]'`, get an API key from
[console.anthropic.com](https://console.anthropic.com), and start the app with
`ANTHROPIC_API_KEY=sk-... jolai ui`. You can pick the model in the UI or in `config.yaml`.

## Command line

The UI and these commands share `config.yaml` (see `config.example.yaml`):

```bash
jolai profile                 # what JolAI read from your resume
jolai search                  # download, rank, print a table, write results/report.html
jolai search --new-only       # only jobs you haven't seen before
jolai search --jobs-file results/jobs.json   # re-rank the last download, no internet needed
jolai search --llm            # include the AI double-check
```

## How it works

See **[docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md)**: a short tour of the code, what each file
does, and where to change things.

## Development

```bash
pip install -e '.[llm,dev]'
pytest
```

The tests use saved sample data in `tests/fixtures/`, including the web UI, so no internet is needed.
