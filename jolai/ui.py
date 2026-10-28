"""The web UI. Start it with ``jolai ui`` (it runs ``streamlit run jolai/ui.py``).

How the page works:
- The sidebar holds your resume and every setting. "Save settings" writes them to config.yaml,
  so the CLI uses the same settings.
- "Search for jobs" scrapes the sources (this is the slow part) and saves them to results/jobs.json.
- Everything else (changing filters, sorting, saving a job) only re-scores the jobs already
  downloaded, which takes about a second and needs no internet.

Streamlit re-runs this whole file from top to bottom on every click; ``st.session_state``
is how values survive between runs.
"""

from __future__ import annotations

import argparse
import html
import os
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

from jolai import pipeline
from jolai.config import load_config, save_config
from jolai.filters import technical_label
from jolai.resume import LEVELS, read_resume_text

# Rough prices in $ per million tokens (input, output), for the AI cost estimate only.
MODEL_PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}
PAGE_SIZE = 20

CSS = """
<style>
.chip { display:inline-block; padding:1px 9px; margin:2px 4px 2px 0; border-radius:99px; font-size:0.78rem;
        border:1px solid rgba(128,128,128,.35); }
.chip.ok   { background:rgba(46,160,67,.15);  border-color:rgba(46,160,67,.45); }
.chip.miss { background:rgba(219,109,40,.15); border-color:rgba(219,109,40,.45); }
.chip.warn { background:rgba(210,153,34,.18); border-color:rgba(210,153,34,.5); }
.meta { opacity:.75; font-size:.9rem; margin:-.4rem 0 .3rem; }
.why  { font-size:.92rem; margin:.2rem 0 .4rem; }
.score { font-size:2rem; font-weight:700; line-height:1; }
.score small { display:block; font-size:.7rem; font-weight:400; opacity:.7; }
</style>
"""


def chips(items: list[str], kind: str = "") -> str:
    return "".join(f'<span class="chip {kind}">{html.escape(i)}</span>' for i in items)


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.replace(",", "\n").splitlines() if line.strip()]


# ---------------------------------------------------------------------------------------
# Setup: which config file, and load it once per browser session
# ---------------------------------------------------------------------------------------

parser = argparse.ArgumentParser()
parser.add_argument("--config", default="config.yaml")
CONFIG_PATH = Path(parser.parse_known_args(sys.argv[1:])[0].config)

st.set_page_config(page_title="JolAI · job finder", page_icon="🔎", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

if "config" not in st.session_state:
    st.session_state.config = load_config(CONFIG_PATH)
config: dict = st.session_state.config
prefs: dict = config.setdefault("preferences", {})
src: dict = config.setdefault("sources", {"remotive": True, "remoteok": True, "hackernews": False})
out_dir = pipeline.results_dir(config)
tracker = pipeline.Tracker(out_dir / "tracker.json")


@st.cache_data(show_spinner=False)
def cached_rank(resume_text: str, jobs_mtime: float, config_snapshot: dict):
    """Re-score only when the resume, the downloaded jobs or the settings change."""
    profile = pipeline.read_profile(config_snapshot, resume_text=resume_text)
    jobs = pipeline.load_jobs(pipeline.results_dir(config_snapshot) / "jobs.json")
    matches, filtered = pipeline.rank(profile, jobs, config_snapshot)
    return profile, matches, filtered, len(jobs)


# ---------------------------------------------------------------------------------------
# Sidebar: resume + settings
# ---------------------------------------------------------------------------------------

with st.sidebar:
    st.header("1 · Your resume")
    upload = st.file_uploader("Upload a PDF, Word or text file", type=["pdf", "docx", "txt", "md"])
    if upload is not None:
        saved = CONFIG_PATH.parent / f"resume{Path(upload.name).suffix.lower()}"
        if not saved.exists() or saved.read_bytes() != upload.getvalue():
            saved.write_bytes(upload.getvalue())
        config["resume"] = str(saved)
    resume_path = config.get("resume")
    if resume_path and Path(resume_path).exists():
        st.caption(f"Using `{resume_path}`")
    else:
        st.info("Upload your resume to get started.")

    st.header("2 · What you want")
    prefs["titles"] = lines(st.text_area(
        "Job titles you're after (one per line)", "\n".join(prefs.get("titles", [])),
        placeholder="Customer Success Manager\nOperations Coordinator\nProject Coordinator"))
    prefs["locations"] = lines(st.text_input("Cities or countries (comma separated)",
                                             ", ".join(prefs.get("locations", []))))
    prefs["remote"] = st.toggle("Remote jobs are OK", prefs.get("remote", True))
    prefs["remote_only"] = st.toggle("Only show remote jobs", prefs.get("remote_only", False))
    prefs["keywords"] = lines(st.text_input("Topics you'd enjoy (comma separated)",
                                            ", ".join(prefs.get("keywords", [])),
                                            placeholder="education, healthcare, travel"))

    st.subheader("Filters")
    prefs["english_only"] = st.toggle("English only", prefs.get("english_only", False),
                                      help="Hide jobs that require another language. Jobs where another "
                                           "language is just 'a plus' stay, with a note.")
    tech_options = {"Not technical": "low", "A little technical is fine": "medium", "Any": "any"}
    current_tech = next((k for k, v in tech_options.items() if v == str(prefs.get("max_technical", "any"))), "Any")
    prefs["max_technical"] = tech_options[st.select_slider(
        "How technical can the job be?", list(tech_options), current_tech,
        help="Based on the job title, how many technical tools it lists, and words like 'coding'.")]
    years = st.slider("Most years of experience a job may ask for", 0, 15,
                      prefs.get("max_years") if prefs.get("max_years") is not None else 15,
                      help="15 means no limit. Jobs that don't say how many years always stay.")
    prefs["max_years"] = None if years >= 15 else years
    level_options = ["any", "entry", "mid", "senior"]
    prefs["max_level"] = st.selectbox("Highest seniority", level_options,
                                      level_options.index(prefs.get("max_level") or "any"),
                                      help="'mid' hides titles with Senior, Lead, Staff or Principal.")
    if prefs["max_level"] == "any":
        prefs["max_level"] = None
    prefs["exclude_title_keywords"] = lines(st.text_input(
        "Hide titles containing", ", ".join(prefs.get("exclude_title_keywords", [])), placeholder="sales, intern"))
    min_salary = st.number_input("Minimum yearly salary (0 = don't care)", 0, 1_000_000,
                                 int(prefs.get("min_salary") or 0), step=5000)
    prefs["min_salary"] = min_salary or None
    weight = st.slider("Rank by", 0.0, 1.0, float((config.get("weights") or {}).get("chance_vs_want", 0.6)), 0.1,
                       help="Left: roles that best match what you want. Right: roles you're most likely to get.")
    st.caption("← what you want · · · · · · · · · your best chances →")
    config.setdefault("weights", {})["chance_vs_want"] = weight

    with st.expander("3 · Where to look"):
        src["remotive"] = st.checkbox("Remotive (remote jobs, many non-technical)", src.get("remotive", True))
        src["remoteok"] = st.checkbox("RemoteOK", src.get("remoteok", True))
        src["hackernews"] = st.checkbox("Hacker News 'Who is hiring' (mostly technical)", src.get("hackernews", False))
        st.caption("Company job boards: the name at the end of the company's careers URL.")
        for key, label in [("greenhouse", "boards.greenhouse.io/…"), ("lever", "jobs.lever.co/…"),
                           ("ashby", "jobs.ashbyhq.com/…")]:
            src[key] = lines(st.text_input(label, ", ".join(src.get(key) or [])))
        src["career_pages"] = lines(st.text_area("Other careers page URLs (one per line)",
                                                 "\n".join(src.get("career_pages") or [])))

    with st.expander("Fix what was read from your resume"):
        prefs["extra_skills"] = lines(st.text_input("Skills it missed (comma separated)",
                                                    ", ".join(prefs.get("extra_skills") or [])))
        override = st.number_input("Years of experience (0 = work it out)", 0.0, 50.0,
                                   float(prefs.get("years_experience") or 0), 0.5)
        prefs["years_experience"] = override or None

    if st.button("💾 Save settings", width="stretch"):
        save_config(config, CONFIG_PATH)
        st.toast(f"Saved to {CONFIG_PATH}")

# ---------------------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------------------

st.title("🔎 JolAI")
st.caption("Finds jobs that fit your resume, and tells you why.")

if not resume_path or not Path(resume_path).exists():
    st.stop()

resume_text = read_resume_text(resume_path)
jobs_file = out_dir / "jobs.json"

top_left, top_right = st.columns([3, 1])
with top_right:
    search_clicked = st.button("🔍 Search for jobs", type="primary", width="stretch")
with top_left:
    if jobs_file.exists():
        when = datetime.fromtimestamp(jobs_file.stat().st_mtime)
        st.caption(f"Jobs last downloaded {when:%b %d, %H:%M}. Search again to refresh; "
                   "changing settings re-scores instantly.")
    else:
        st.caption("No jobs downloaded yet. Pick your sources in the sidebar, then search.")

if search_clicked:
    with st.status("Collecting jobs…", expanded=True) as status:
        def progress(label, count, error):
            status.write(f"❌ {label}: {error}" if error else f"✅ {label}: {count} jobs")

        jobs = pipeline.collect_jobs(config, on_progress=progress)
        status.update(label=f"Collected {len(jobs)} jobs", state="complete", expanded=False)

if not jobs_file.exists():
    st.stop()

profile, matches, filtered, total = cached_rank(resume_text, jobs_file.stat().st_mtime, config)

# Apply any AI answers already paid for (free: read from results/ai_cache.json, no API call).
ai_cfg = config.setdefault("llm", {})
matches = pipeline.ai_rerank(list(matches), profile, config, cache_only=True)

with st.expander(f"What JolAI read from your resume: ~{profile.years_experience:g} years, "
                 f"{LEVELS[profile.level]} level, {len(profile.skills)} skills"):
    st.markdown("**Titles:** " + (", ".join(profile.titles) or "none found"))
    st.markdown(chips(sorted(profile.skills), "ok") or "No skills found", unsafe_allow_html=True)
    st.caption("Something wrong? Fix it under 'Fix what was read from your resume' in the sidebar.")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Jobs downloaded", total)
m2.metric("Filtered out", sum(filtered.values()))
m3.metric("Matches", len(matches))
m4.metric("Saved", sum(1 for v in tracker.data.values() if v["status"] == "saved"))
if filtered:
    st.caption("Filtered out: " + " · ".join(f"{n} {why}" for why, n in sorted(filtered.items(), key=lambda x: -x[1])))

# -- AI double-check ---------------------------------------------------------------------
with st.expander("✨ Double-check the top matches with AI (optional, costs a little)"):
    has_sdk = True
    try:
        import anthropic  # noqa: F401
    except ImportError:
        has_sdk = False
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    st.write("Claude reads your resume and each posting in full, catches things the free filters miss "
             "(like a must-have certificate), and re-scores them. Answers are saved, so you never pay "
             "twice for the same job.")
    c1, c2 = st.columns(2)
    ai_cfg["model"] = c1.selectbox("Model", list(MODEL_PRICES),
                                   list(MODEL_PRICES).index(ai_cfg.get("model", "claude-opus-5-5"))
                                   if ai_cfg.get("model", "claude-opus-5-5") in MODEL_PRICES else 0)
    ai_cfg["top_n"] = c2.slider("How many top jobs", 5, 30, int(ai_cfg.get("top_n", 10)), 5)
    sample = matches[: ai_cfg["top_n"]]
    in_price, out_price = MODEL_PRICES[ai_cfg["model"]]
    batches = -(-len(sample) // 10)  # the resume is sent once per batch of 10 jobs
    in_tokens = sum(len(m.job.description) for m in sample) / 4 + len(resume_text) / 4 * batches
    estimate = (in_tokens * in_price + len(sample) * 400 * out_price) / 1_000_000
    st.caption(f"Estimated cost for {len(sample)} jobs: about ${estimate:.2f} (less if some were checked before).")
    if not has_sdk:
        st.warning("Install the AI extra first: `pip install -e '.[llm]'`")
    elif not has_key:
        st.warning("Set the ANTHROPIC_API_KEY environment variable before starting `jolai ui`.")
    elif st.button("Run AI double-check"):
        with st.spinner("Asking Claude…"):
            pipeline.ai_rerank(list(matches), profile, config)
        st.rerun()

# -- Job lists ---------------------------------------------------------------------------
tab_matches, tab_saved, tab_applied, tab_hidden = st.tabs(["Matches", "⭐ Saved", "📨 Applied", "🙈 Hidden"])


def job_card(m, key_prefix: str) -> None:
    j, f = m.job, m.facts
    with st.container(border=True):
        left, right = st.columns([1, 7])
        score = m.llm_score if m.llm_score is not None else m.score
        left.markdown(f'<div class="score">{score:.0f}<small>{"AI score" if m.llm_score is not None else "score"}'
                      f'</small></div>', unsafe_allow_html=True)
        left.caption(f"chance {m.chance:.0f}  \nwant {m.want:.0f}")
        with right:
            st.markdown(f"#### [{j.title}]({j.url})")
            pay = ""
            if j.salary_min or j.salary_max:
                pay = " · $" + "–".join(f"{v:,.0f}" for v in dict.fromkeys(v for v in (j.salary_min, j.salary_max) if v))
            st.markdown(f'<div class="meta">{html.escape(j.company)} · {html.escape(j.location or "location n/a")}'
                        f'{" · remote" if j.remote and "remote" not in j.location.lower() else ""}{pay} · via {j.source}</div>', unsafe_allow_html=True)
            badges = [f"{technical_label(f.technical)} technical", f"{LEVELS[f.level]} level"]
            if f.years_required:
                badges.append(f"asks {f.years_required}+ yrs")
            warn = [f"needs {lang}" for lang in f.languages_required] + \
                   [f"{lang} a plus" for lang in f.languages_optional]
            st.markdown(chips(badges) + chips(warn, "warn"), unsafe_allow_html=True)
            why = m.llm_summary or " · ".join(m.reasons[:4])
            if why:
                st.markdown(f'<div class="why">{html.escape(why)}</div>', unsafe_allow_html=True)
            if m.matched_skills or m.missing_skills:
                st.markdown(chips(m.matched_skills, "ok") + chips(m.missing_skills, "miss"), unsafe_allow_html=True)
            with st.expander("Job description"):
                st.text(j.description[:6000] + ("…" if len(j.description) > 6000 else ""))
            b1, b2, b3, _ = st.columns([1, 1, 1, 3])
            status = tracker.status(j.id)
            for col, name, label in [(b1, "saved", "⭐ Save"), (b2, "applied", "📨 Applied"), (b3, "hidden", "🙈 Hide")]:
                active = status == name
                if col.button(("✓ " if active else "") + label, key=f"{key_prefix}-{name}-{j.id}",
                              type="primary" if active else "secondary", width="stretch"):
                    tracker.set(m, None if active else name)
                    st.rerun()


with tab_matches:
    f1, f2, f3 = st.columns([2, 1, 1])
    query = f1.text_input("Search within results", placeholder="e.g. support, Berlin, healthcare")
    sort = f2.selectbox("Sort by", ["Best overall", "Best chance", "Best fit with wants", "Newest"])
    min_score = f3.slider("Minimum score", 0, 100, 0, 5)

    visible = [m for m in matches if tracker.status(m.job.id) != "hidden"
               and (m.llm_score if m.llm_score is not None else m.score) >= min_score]
    if query:
        q = query.lower()
        visible = [m for m in visible if q in m.job.text.lower()]
    if sort == "Best chance":
        visible.sort(key=lambda m: m.chance, reverse=True)
    elif sort == "Best fit with wants":
        visible.sort(key=lambda m: m.want, reverse=True)
    elif sort == "Newest":
        visible.sort(key=lambda m: m.job.posted_at or "", reverse=True)

    shown = st.session_state.get("shown", PAGE_SIZE)
    if not visible:
        st.info("No matches. Try loosening a filter in the sidebar, or add more sources.")
    for m in visible[:shown]:
        job_card(m, "all")
    if len(visible) > shown and st.button(f"Show more ({len(visible) - shown} left)"):
        st.session_state.shown = shown + PAGE_SIZE
        st.rerun()

for tab, status_name in [(tab_saved, "saved"), (tab_applied, "applied"), (tab_hidden, "hidden")]:
    with tab:
        picked = [m for m in matches if tracker.status(m.job.id) == status_name]
        # Jobs you marked that your current filters hide (or that are no longer listed) still show, as links.
        listed = {m.job.id for m in picked}
        others = [(jid, v) for jid, v in tracker.data.items() if v["status"] == status_name and jid not in listed]
        if not picked and not others:
            st.caption("Nothing here yet.")
        for m in picked:
            job_card(m, status_name)
        if others:
            st.caption("Not in the current results (filtered out or no longer posted):")
            for jid, v in others:
                st.markdown(f"- [{v['title']}]({v['url']}) · {v['company']}")
