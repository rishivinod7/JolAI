import json
from pathlib import Path

import pytest

from jolai import cli, sources
from jolai.matcher import Preferences, job_level, score_jobs, years_required
from jolai.models import Job
from jolai.resume import estimate_years, extract_titles, load_profile
from jolai.skills import extract_skills
from jolai.sources.base import parse_salary_range

FIX = Path(__file__).parent / "fixtures"

ROUTES = {
    "boards-api.greenhouse.io": "greenhouse.json",
    "api.lever.co": "lever.json",
    "api.ashbyhq.com": "ashby.json",
    "remoteok.com/api": "remoteok.json",
    "remotive.com": "remotive.json",
    "hn.algolia.com/api/v1/search": "hn_search.json",
    "hn.algolia.com/api/v1/items": "hn_item.json",
    "bar.example/careers/other": "careers_other.html",
    "bar.example/careers": "careers.html",
}


class FakeFetcher:
    """Serves fixture files instead of hitting the network."""

    def __init__(self):
        self.calls = []

    def get_text(self, url, check_robots=False):
        self.calls.append(url)
        for prefix, name in ROUTES.items():
            if prefix in url:
                return (FIX / name).read_text()
        raise FileNotFoundError(url)

    def get_json(self, url):
        return json.loads(self.get_text(url))


@pytest.fixture
def profile():
    return load_profile(FIX / "resume.txt")


def test_profile_extraction(profile):
    assert {"Python", "Go", "Kubernetes", "Kafka", "PostgreSQL", "AWS", "Django", "gRPC"} <= profile.skills
    assert "C" not in profile.skills
    assert 7 <= profile.years_experience <= 8.5  # Jun 2019 -> today (Oct 2026)
    assert profile.titles[0] == "Senior Software Engineer"
    assert profile.level == 3


def test_skill_boundaries():
    assert extract_skills("C++ and C# on .NET") == {"C++", "C#", ".NET"}
    assert "Go" not in extract_skills("go to the store")
    assert "Java" not in extract_skills("JavaScript only")
    assert "Swift" not in extract_skills("swift delivery")


def test_years_and_titles():
    assert estimate_years("Engineer 2015 - 2016\nEngineer 2016 - 2017") == pytest.approx(3.0, abs=0.1)
    assert estimate_years("10+ years of professional experience") == 10
    assert extract_titles("Data Scientist | Foo\nlorem ipsum") == ["Data Scientist"]


def test_job_heuristics():
    assert job_level("Senior Staff Engineer") == 4
    assert job_level("Software Engineer II") == 2
    assert job_level("New Grad Software Engineer") == 1
    assert years_required("Requires 3-5 years of professional experience; 10 years in business") == 3
    assert parse_salary_range("Pay: $150k - $190k") == (150_000, 190_000)
    assert parse_salary_range("$180,000 - $220,000") == (180_000, 220_000)


def test_all_sources_parse():
    fetcher = FakeFetcher()
    config = {"greenhouse": ["stripe"], "lever": ["palantir"], "ashby": ["ramp"],
              "career_pages": ["https://bar.example/careers"],
              "remotive": True, "remoteok": True, "hackernews": True}
    errors = []
    jobs = sources.collect(fetcher, config, ["backend"], on_result=lambda l, n, e: e and errors.append((l, e)))
    assert not errors
    by_title = {j.title: j for j in jobs}

    gh = by_title["Senior Backend Engineer, Payments"]
    assert gh.company == "Stripe" and "Kafka" in gh.description and gh.salary_max == 220_000
    lv = by_title["Platform Engineer"]
    assert lv.remote and lv.salary_min == 160_000 and "Terraform" in lv.description
    assert "Hidden" not in by_title
    assert by_title["Backend Developer (Python)"].source == "remoteok"
    assert by_title["Software Engineer, Distributed Systems"].salary_min == 150_000
    hn = by_title["Senior Backend Engineer"]
    assert hn.company == "Foo Labs" and hn.remote and hn.salary_max == 210_000
    sre = by_title["Site Reliability Engineer"]
    assert sre.company == "Bar Corp" and sre.location == "Brooklyn, NY, US" and sre.salary_max == 208_000
    assert by_title["Data Analyst"].remote  # found by following the link from the first page
    assert len(jobs) == 10


def test_ranking(profile):
    jobs = sources.collect(FakeFetcher(), {"greenhouse": ["stripe"], "lever": ["palantir"], "ashby": ["ramp"],
                                           "remotive": True}, [])
    prefs = Preferences(titles=["Backend Engineer", "Platform Engineer"], locations=["New York"],
                        keywords=["fintech"], exclude_title_keywords=["intern"], min_salary=150_000)
    matches, filtered = score_jobs(profile, jobs, prefs)
    titles = [m.job.title for m in matches]
    assert filtered == {"title contains 'intern'": 1}
    assert titles[0] == "Senior Backend Engineer, Payments"
    assert titles.index("Platform Engineer") < titles.index("Staff Machine Learning Engineer")
    assert titles[-1] in {"Product Designer", "Staff Machine Learning Engineer"}
    ml = next(m for m in matches if "Machine Learning" in m.job.title)
    assert any("10+ yrs" in r for r in ml.reasons)


def test_cli_end_to_end(tmp_path, monkeypatch):
    jobs_file = tmp_path / "jobs.json"
    jobs = sources.collect(FakeFetcher(), {"greenhouse": ["stripe"], "lever": ["palantir"]}, [])
    jobs_file.write_text(json.dumps([vars(j) for j in jobs]))
    out = tmp_path / "out"
    cli.main(["search", "-r", str(FIX / "resume.txt"), "--jobs-file", str(jobs_file), "-o", str(out)])
    rows = json.loads((out / "matches.json").read_text())
    assert len(rows) == 4 and rows[0]["score"] >= rows[-1]["score"]
    assert "<article>" in (out / "report.html").read_text()
    assert (out / "matches.csv").exists()

    # Second run with --new-only hides everything already shown.
    cli.main(["search", "-r", str(FIX / "resume.txt"), "--jobs-file", str(jobs_file), "-o", str(out), "--new-only"])
    assert json.loads((out / "matches.json").read_text()) == []


def test_llm_rerank_reorders_and_caches(monkeypatch, profile, tmp_path):
    anthropic = pytest.importorskip("anthropic")
    from types import SimpleNamespace

    from jolai import llm
    from jolai.models import Match

    def make():
        return [Match(job=Job("Role A", "Co", "u1", "test", description="a"), score=90, chance=90, want=90),
                Match(job=Job("Role B", "Co", "u2", "test", description="b"), score=50, chance=50, want=50)]

    a, b = make()
    schema = llm._schema()
    parsed = schema(jobs=[
        {"job_id": b.job.id, "fit_score": 95, "want_score": 90, "summary": "Great fit.", "gaps": [], "dealbreakers": []},
        {"job_id": a.job.id, "fit_score": 90, "want_score": 60, "summary": "Needs German.", "gaps": ["X"],
         "dealbreakers": ["Fluent German required"]}])
    calls = []

    class FakeClient:
        def __init__(self):
            self.messages = SimpleNamespace(parse=lambda **kw: calls.append(kw) or SimpleNamespace(
                stop_reason="end_turn", parsed_output=parsed))

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    cache = tmp_path / "ai.json"
    ranked = llm.rerank([a, b], profile.text, "Remote: fine", cache_path=cache)
    assert [m.job.title for m in ranked] == ["Role B", "Role A"]
    assert ranked[1].llm_score <= 50  # the dealbreaker caps the fit score
    assert "Dealbreakers: Fluent German required." in ranked[1].llm_summary
    assert calls[0]["model"] == "claude-opus-5-5" and calls[0]["output_format"] is schema
    assert calls[0]["output_config"] == {"effort": "low"}

    # Second run: same jobs, same resume -> answered from the cache, no new API call.
    again = llm.rerank(make(), profile.text, "Remote: fine", cache_path=cache)
    assert len(calls) == 1 and again[0].job.title == "Role B"
    # cache_only never calls the API, even for unseen jobs.
    new = [Match(job=Job("Role C", "Co", "u3", "test"), score=10, chance=10, want=10)]
    assert llm.rerank(new, profile.text, "x", cache_path=cache, cache_only=True)[0].llm_score is None
    assert len(calls) == 1


# ---- filters for non-technical, English-only, not-too-senior searches ----------------

def test_language_detection():
    from jolai.filters import language_requirements

    assert language_requirements("Fluent German is required.") == (["German"], [])
    assert language_requirements("You speak Dutch and English.") == (["Dutch"], [])
    assert language_requirements("Spanish is a plus.") == ([], ["Spanish"])
    assert language_requirements("Fluent French would be a bonus.") == ([], ["French"])
    assert language_requirements("Work with our German customers in English.") == ([], [])
    mixed = json.loads((FIX / "jobs_mixed.json").read_text())
    german_posting = next(j for j in mixed if j["company"] == "Hallo GmbH")["description"]
    assert language_requirements(german_posting)[0] == ["German"]


def test_technical_score():
    from jolai.filters import technical_score

    assert technical_score("Customer Support Specialist", "Help customers in Zendesk.") < 35
    assert technical_score("Senior Backend Engineer", "Python, Go, Kubernetes, AWS, system design") > 65


def test_nontech_search_filters():
    from jolai import pipeline

    config = {"resume": str(FIX / "resume_nontech.txt"),
              "preferences": {"titles": ["Customer Support Specialist", "Social Media Coordinator"],
                              "english_only": True, "max_technical": "low", "max_years": 3, "max_level": "mid"}}
    profile = pipeline.read_profile(config)
    assert "Administrative Assistant" in profile.titles and "Zendesk" in profile.skills
    matches, filtered = pipeline.rank(profile, pipeline.load_jobs(FIX / "jobs_mixed.json"), config)
    assert [m.job.title for m in matches] == ["Customer Support Specialist", "Social Media Coordinator"]
    assert filtered == {"needs a language other than English": 2, "asks for too many years": 2, "too technical": 1}
    assert any("Spanish is a plus" in r for r in matches[0].reasons)

    # Without the filters everything comes back, and the engineering job ranks low on chance.
    config["preferences"] = {"titles": config["preferences"]["titles"]}
    everything, _ = pipeline.rank(profile, pipeline.load_jobs(FIX / "jobs_mixed.json"), config)
    assert len(everything) == 7
    assert everything[-1].job.title in {"Senior Backend Engineer", "Technical Support Engineer",
                                        "Head of Customer Operations"}


def test_config_round_trip(tmp_path):
    from jolai.config import load_config, preferences_from, save_config

    path = tmp_path / "config.yaml"
    save_config({"preferences": {"english_only": True, "max_technical": "medium", "max_years": 2}}, path)
    prefs = preferences_from(load_config(path))
    assert prefs.english_only and prefs.max_technical == 64 and prefs.max_years == 2


def test_tracker(tmp_path):
    from jolai.models import Match
    from jolai.pipeline import Tracker

    m = Match(job=Job("Role", "Co", "u", "test"), score=1, chance=1, want=1)
    t = Tracker(tmp_path / "t.json")
    t.set(m, "saved")
    assert Tracker(tmp_path / "t.json").status(m.job.id) == "saved"
    t.set(m, None)
    assert Tracker(tmp_path / "t.json").status(m.job.id) is None


def test_ui_renders(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    import shutil

    shutil.copy(FIX / "jobs_mixed.json", tmp_path / "jobs.json")
    config = tmp_path / "config.yaml"
    config.write_text(f"resume: {FIX / 'resume_nontech.txt'}\noutput:\n  dir: {tmp_path}\n"
                      "preferences:\n  english_only: true\n  max_technical: low\n")
    monkeypatch.setattr("sys.argv", ["ui.py", "--config", str(config)])
    app = AppTest.from_file(str(Path(__file__).parents[1] / "jolai" / "ui.py"), default_timeout=30).run()
    assert not app.exception
    titles = [md.value for md in app.markdown if md.value.startswith("#### ")]
    assert any("Customer Support Specialist" in t for t in titles)
    assert not any("Kundenservice" in t or "Backend Engineer" in t for t in titles)

    # Saving a job moves it to the Saved tab.
    next(b for b in app.button if b.label == "⭐ Save").click().run()
    assert not app.exception
    assert "saved" in (tmp_path / "tracker.json").read_text()
