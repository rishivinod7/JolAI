"""Free, rule-based checks that read a job posting the way you would skim it.

These run on every job (no AI, no cost) and answer three questions:

1. Does it require a language other than English?   -> ``language_requirements``
2. How technical is it, on a 0-100 scale?           -> ``technical_score``
3. How much experience does it ask for?             -> ``matcher.years_required`` (lives with the scorer)

The scorer uses the answers to drop jobs you said you don't want (see ``Preferences``).
"""

from __future__ import annotations

import re

from .skills import NON_TECHNICAL, extract_skills

# --------------------------------------------------------------------------------------
# 1. Language requirements
# --------------------------------------------------------------------------------------

LANGUAGES = [
    "Arabic", "Bengali", "Bulgarian", "Cantonese", "Chinese", "Croatian", "Czech", "Danish", "Dutch", "Estonian",
    "Finnish", "Flemish", "French", "German", "Greek", "Hebrew", "Hindi", "Hungarian", "Indonesian", "Italian",
    "Japanese", "Korean", "Latvian", "Lithuanian", "Malay", "Mandarin", "Norwegian", "Persian", "Farsi", "Polish",
    "Portuguese", "Romanian", "Russian", "Serbian", "Slovak", "Slovenian", "Spanish", "Swahili", "Swedish",
    "Tagalog", "Thai", "Turkish", "Ukrainian", "Urdu", "Vietnamese",
]
_LANG = "(" + "|".join(LANGUAGES) + ")"

# Words that turn a language mention into a requirement ("fluent German", "German: C1", "native Spanish speaker").
_STRONG = r"(?:fluent|fluency|native|mother tongue|proficien\w*|business[- ]level|professional working|excellent|" \
          r"strong|perfect|full professional|written and spoken|spoken and written|C1|C2|B2)"
# Words that make it optional.
_SOFT = r"(?:plus|bonus|nice to have|nice-to-have|advantage|advantageous|preferred|desirable|beneficial|" \
        r"helpful|is a benefit|a benefit)"

REQUIRED_PATTERNS = [
    re.compile(rf"\b{_STRONG}\b[^.\n]{{0,40}}?\b{_LANG}\b", re.I),        # "fluent in German"
    re.compile(rf"\b{_LANG}\b[^.\n]{{0,30}}?\b{_STRONG}\b", re.I),        # "German (C1)", "Spanish, native level"
    re.compile(rf"\b{_LANG}\b\s*(?:language\s*)?(?:skills\s*)?(?:is\s*|are\s*)?(?:required|mandatory|a must|"
               rf"essential)", re.I),                                        # "French is required"
    re.compile(rf"\b(?:speak|speaks|speaking|write|read)\b[^.\n]{{0,20}}?\b{_LANG}\b", re.I),  # "you speak Dutch"
    re.compile(rf"\bbilingual\b[^.\n]{{0,40}}?\b{_LANG}\b|\b{_LANG}\b[^.\n]{{0,20}}?\bbilingual\b", re.I),
]
SOFT_RE = re.compile(_SOFT, re.I)

# A handful of very common words per language, to spot postings written entirely in another language.
FOREIGN_STOPWORDS = {
    "German": {"und", "der", "die", "das", "mit", "für", "wir", "sie", "ist", "nicht", "auf", "eine", "bei"},
    "French": {"et", "les", "des", "une", "pour", "nous", "vous", "avec", "est", "dans", "sur", "aux"},
    "Spanish": {"y", "los", "las", "una", "para", "con", "nuestro", "somos", "por", "del", "como", "más"},
    "Dutch": {"en", "het", "een", "voor", "met", "wij", "jij", "ons", "naar", "bij", "zijn", "van"},
    "Italian": {"e", "il", "della", "per", "con", "una", "siamo", "nostro", "nel", "degli", "che"},
    "Portuguese": {"e", "os", "uma", "para", "com", "nosso", "somos", "não", "das", "dos", "você"},
}
ENGLISH_STOPWORDS = {"the", "and", "to", "of", "you", "we", "for", "with", "our", "in", "is", "are", "will", "your"}


def written_in(text: str) -> str:
    """Best guess at the language a posting is written in ("English" unless clearly not)."""
    words = re.findall(r"[a-zäöüßéèêàçñóíúãõ]+", text.lower())[:600]
    if len(words) < 30:
        return "English"
    english = sum(w in ENGLISH_STOPWORDS for w in words)
    best_lang, best_count = "English", english
    for lang, stops in FOREIGN_STOPWORDS.items():
        count = sum(w in stops for w in words)
        if count > best_count * 1.5 and count >= 8:
            best_lang, best_count = lang, count
    return best_lang


def language_requirements(text: str) -> tuple[list[str], list[str]]:
    """Return (required, nice_to_have) non-English languages mentioned in a posting.

    A language counts as *required* when it appears next to words like "fluent", "native",
    "required" or a CEFR level, and the same sentence doesn't call it a plus or a bonus.
    A posting written in another language counts as requiring that language.
    """
    required, optional = set(), set()
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", text):
        hits = {m.group(1).title() for p in REQUIRED_PATTERNS for m in p.finditer(sentence)}
        if not hits:
            continue
        (optional if SOFT_RE.search(sentence) else required).update(hits)
    # Mentions without strong wording ("German is a plus") are optional.
    for m in re.finditer(rf"\b{_LANG}\b[^.\n]{{0,40}}{_SOFT}|{_SOFT}[^.\n]{{0,40}}\b{_LANG}\b", text, re.I):
        lang = (m.group(1) or m.group(2)).title()
        if lang not in required:
            optional.add(lang)
    lang = written_in(text)
    if lang != "English":
        required.add(lang)
    return sorted(required), sorted(optional - required)


# --------------------------------------------------------------------------------------
# 2. How technical is the role?
# --------------------------------------------------------------------------------------

TECH_TITLE_RE = re.compile(
    r"\b(engineer\w*|developer|programmer|architect|devops|sre|data scientist|machine learning|ml|ai researcher|"
    r"firmware|embedded|software|backend|back-end|frontend|front-end|full[- ]?stack|security analyst|"
    r"database administrator|dba|sysadmin|systems administrator|network)\b", re.I)
SOFT_TECH_TITLE_RE = re.compile(r"\b(data analyst|analytics|technical|it\b|solutions|product manager|qa|tester|"
                                r"implementation|support engineer)", re.I)
TECH_PHRASES = re.compile(r"\b(coding|programming|write code|codebase|code review|pull requests?|algorithms?|"
                          r"data structures|system design|scalab\w+|deploy\w*|production systems?|apis?|sdk|"
                          r"computer science|cs degree|technical degree|debug\w*|scripting)\b", re.I)
def technical_score(title: str, text: str) -> int:
    """0 = not technical at all (e.g. customer success), 100 = deeply technical (e.g. backend engineer).

    Mixes three signals: an engineering-style title, how many hands-on tech skills the posting
    lists, and phrases like "coding" or "system design".
    """
    title_points = 60 if TECH_TITLE_RE.search(title) else 20 if SOFT_TECH_TITLE_RE.search(title) else 0
    tech_skills = extract_skills(text) - NON_TECHNICAL
    skill_points = min(35, len(tech_skills) * 5)
    phrase_points = min(20, len(set(m.lower() for m in TECH_PHRASES.findall(text))) * 4)
    return min(100, title_points + skill_points + phrase_points)


def technical_label(score: int) -> str:
    return "low" if score < 35 else "medium" if score < 65 else "high"


# --------------------------------------------------------------------------------------
# 3. Can you legally work there? (work permits and visa sponsorship)
# --------------------------------------------------------------------------------------

# Country names, short forms and big cities, so a location like "Bengaluru" or "Remote - US" maps to a country.
COUNTRIES: dict[str, list[str]] = {
    "India": ["india", "bengaluru", "bangalore", "mumbai", "delhi", "new delhi", "gurgaon", "gurugram", "noida",
              "hyderabad", "pune", "chennai", "kolkata", "ahmedabad", "jaipur", "kochi"],
    "Hong Kong": ["hong kong", "hongkong", "hk", "hksar", "kowloon"],
    "Singapore": ["singapore", "sg"],
    "United States": ["united states", "usa", "us", "u.s.", "america", "new york", "nyc", "san francisco", "seattle",
                      "boston", "chicago", "austin", "los angeles", "denver", "atlanta", "washington, dc",
                      "miami", "dallas", "remote us", "ca", "ny", "tx", "wa", "ma", "il", "co", "ga", "fl"],
    "Canada": ["canada", "toronto", "vancouver", "montreal", "ontario", "british columbia"],
    "United Kingdom": ["united kingdom", "uk", "u.k.", "england", "scotland", "london", "manchester", "edinburgh",
                       "glasgow", "birmingham", "bristol", "cambridge"],
    "Ireland": ["ireland", "dublin"],
    "Germany": ["germany", "berlin", "munich", "hamburg", "frankfurt", "cologne"],
    "Netherlands": ["netherlands", "amsterdam", "rotterdam", "utrecht"],
    "France": ["france", "paris", "lyon"],
    "Spain": ["spain", "madrid", "barcelona"],
    "Portugal": ["portugal", "lisbon", "porto"],
    "Switzerland": ["switzerland", "zurich", "geneva"],
    "United Arab Emirates": ["united arab emirates", "uae", "dubai", "abu dhabi"],
    "Saudi Arabia": ["saudi arabia", "riyadh", "jeddah"],
    "Australia": ["australia", "sydney", "melbourne", "brisbane", "perth"],
    "New Zealand": ["new zealand", "auckland", "wellington"],
    "Japan": ["japan", "tokyo", "osaka"],
    "South Korea": ["south korea", "korea", "seoul"],
    "China": ["china", "shanghai", "beijing", "shenzhen", "guangzhou"],
    "Taiwan": ["taiwan", "taipei"],
    "Malaysia": ["malaysia", "kuala lumpur"],
    "Indonesia": ["indonesia", "jakarta"],
    "Philippines": ["philippines", "manila"],
    "Thailand": ["thailand", "bangkok"],
    "Vietnam": ["vietnam", "ho chi minh", "hanoi"],
}
# Remote jobs open to these regions include India and Hong Kong-style permits only if the region covers them.
REGIONS: dict[str, set[str]] = {
    "worldwide": set(), "anywhere": set(), "global": set(),  # empty set = everywhere
    "apac": {"India", "Hong Kong", "Singapore", "Australia", "New Zealand", "Japan", "South Korea", "China",
             "Taiwan", "Malaysia", "Indonesia", "Philippines", "Thailand", "Vietnam"},
    "asia": {"India", "Hong Kong", "Singapore", "Japan", "South Korea", "China", "Taiwan", "Malaysia",
             "Indonesia", "Philippines", "Thailand", "Vietnam"},
    "emea": {"United Kingdom", "Ireland", "Germany", "Netherlands", "France", "Spain", "Portugal", "Switzerland",
             "United Arab Emirates", "Saudi Arabia"},
    "europe": {"United Kingdom", "Ireland", "Germany", "Netherlands", "France", "Spain", "Portugal",
               "Switzerland"},
    "north america": {"United States", "Canada"},
    "middle east": {"United Arab Emirates", "Saudi Arabia"},
}

SPONSORS_RE = re.compile(
    r"(visa sponsorship (is )?(available|provided|offered)|we (can |will |do )?sponsor|sponsorship (is )?available|"
    r"(will|can) sponsor|offer(s)? (visa )?sponsorship|provide (visa )?sponsorship|relocation (support|package|"
    r"assistance)|help (you )?(with |obtain )?(a |your )?(work )?visa|employment pass support|visa support)", re.I)
NO_SPONSOR_RE = re.compile(
    r"(no (visa )?sponsorship|not (able|in a position) to (offer |provide )?(visa )?sponsor|unable to (offer |provide )?"
    r"(visa )?sponsor|(cannot|can't|can not|do not|don't|will not|won't) (offer |provide )?(visa )?sponsor|"
    r"without (the need for )?(visa )?sponsorship|must (already )?(be|have) (legally )?(authori[sz]ed|eligible|"
    r"the (legal )?right) to work|must have (valid )?(work|working) (rights|authori[sz]ation|permit)|"
    r"(us|u\.s\.) citizens? (only|required)|citizenship (is )?required|green card|security clearance)", re.I)


def countries_in(location: str) -> set[str]:
    """Countries mentioned in a location string, e.g. "Remote - US; London" -> {"United States", "United Kingdom"}."""
    loc = f" {location.lower()} "
    found = set()
    for country, names in COUNTRIES.items():
        for name in names:
            short = len(name) <= 3  # "us", "uk", "hk", state codes: only as standalone tokens
            pattern = rf"(?<![a-z]){re.escape(name)}(?![a-z])" if not short else rf"(?<![a-z.]){re.escape(name)}(?![a-z])"
            if re.search(pattern, loc):
                if short and name in {"ca", "ny", "tx", "wa", "ma", "il", "co", "ga", "fl"} and not re.search(
                        rf",\s*{name}\b", loc):
                    continue  # state codes only count after a comma: "Austin, TX"
                found.add(country)
                break
    return found


def work_authorization(job_location: str, remote: bool, text: str, permits: list[str]) -> str:
    """Can you work this job, given the countries you already hold permits for?

    Returns one of:
      "ok"        the job is in (or open to) a country you can already work in
      "sponsors"  it's elsewhere, but the posting says it sponsors visas or helps relocate
      "unclear"   it's elsewhere and the posting doesn't say
      "blocked"   it's elsewhere and the posting says no sponsorship / must already have the right to work
    """
    permits_set = set().union(*(countries_in(p) for p in permits)) if permits else set()
    loc = job_location.lower()
    countries = countries_in(job_location)
    regions = [members for region, members in REGIONS.items() if re.search(rf"\b{region}\b", loc)]
    if countries & permits_set:
        return "ok"
    if not countries:
        if regions:
            # "Remote - APAC" includes you; "Remote - Europe" doesn't.
            if any(not members or members & permits_set for members in regions):
                return "ok"
        elif remote:
            return "ok"  # remote with no country or region limit
        else:
            return "unclear"  # no usable location at all
    if NO_SPONSOR_RE.search(text):
        return "blocked"
    if SPONSORS_RE.search(text):
        return "sponsors"
    return "unclear"


# --------------------------------------------------------------------------------------
# 4. Does it need a background you don't have? (e.g. sales, consulting, a certification)
# --------------------------------------------------------------------------------------
# Changing field is fine when the door is open: an entry-level sales job doesn't need past sales
# experience. A "Key Account Manager" asking for "3+ years in account management" does. For each
# background we know:
#   title:     job titles that, above entry level, assume you've done this before
#   asks:      words that, after "experience in/as/of" or before "experience", name the background
#   evidence:  skills, past titles or resume wording that show you have it

_SOFT_ASK = re.compile(r"\b(preferred|a plus|plus\b|bonus|advantage|advantageous|nice to have|nice-to-have|ideally|"
                       r"desirable|beneficial|not required|not necessary)\b", re.I)
_OPEN_DOOR = re.compile(r"no (prior |previous )?(\w+ )?experience (is )?(required|needed|necessary)|"
                        r"fresh graduates?|graduates? welcome|will train|training provided|entry[- ]level", re.I)

EXPERIENCE_AREAS: dict[str, dict] = {
    "sales": {
        "title": r"\b(sales|account (manager|executive|director|lead)|key account|business development|"
                 r"bd (manager|executive|lead)|territory manager|channel (sales|manager)|inside sales)\b",
        "asks": r"(b2b |b2c |enterprise |field |direct )?(sales|selling|account management|key account management|"
                r"business development|new business|quota|revenue targets?|sales targets?)",
        "skills": {"Sales"},
        "evidence": r"sales targets?|quota|closed deals|closing deals|revenue targets?|new business|"
                    r"account executive|sales (manager|executive|representative)|business development (manager|executive)",
    },
    "management consulting": {
        "title": r"\b(management|strategy) consult(ant|ing)\b|\bengagement manager\b",
        "asks": r"(management|strategy|strategic|top[- ]tier|mbb|big 4|big four) consulting|consulting firm",
        "skills": set(),
        "evidence": r"(management|strategy) consult|consulting firm|mckinsey|boston consulting|\bbcg\b|\bbain\b|"
                    r"deloitte|\bpwc\b|\bkpmg\b|ernst|accenture strategy",
    },
    "finance": {
        "title": r"\b(financial analyst|finance (manager|analyst|business partner)|fp&a|accountant|controller|"
                 r"auditor|investment banking|credit analyst|treasury)\b",
        "asks": r"(corporate finance|fp&a|financial planning|accounting|audit|investment banking|equity research|"
                r"treasury|private equity)",
        "skills": {"Financial Analysis", "Accounting", "Bookkeeping"},
        "evidence": r"financial (analyst|modell?ing)|accountant|\baudit|investment bank|fp&a",
    },
    "marketing": {
        "title": r"\b(marketing (manager|lead|specialist|executive)|brand manager|performance marketing|growth marketer|"
                 r"seo (manager|specialist)|content marketing)\b",
        "asks": r"(digital marketing|performance marketing|brand management|growth marketing|marketing)",
        "skills": set(),  # the Marketing skill alone is too weak ("supported marketing decks")
        "evidence": r"marketing (manager|executive|specialist|campaigns?)|brand manager|campaigns",
    },
    "people management": {
        "title": r"(?!x)x",  # never matches; level filters already handle Head of / Director titles
        "asks": r"(people management|line management|managing (a )?teams?|leading (a )?teams?|direct reports)",
        "skills": set(),
        "evidence": r"\b(managed|led) (a )?team of|direct reports|line managed|people manager",
    },
    "recruiting": {
        "title": r"\b(recruiter|talent acquisition|recruitment consultant)\b",
        "asks": r"(recruiting|recruitment|talent acquisition)",
        "skills": {"Recruiting"},
        "evidence": r"recruit(er|ing|ment)|talent acquisition",
    },
}
_NOT_THE_AREA = r"(?!\s+(teams?|stakeholders?|department|colleagues|leaders|leadership|functions?|data|reports?|tools?))"

# Certifications postings sometimes make mandatory.
CREDENTIALS = {"PMP": r"\bpmp\b", "PRINCE2": r"\bprince ?2\b", "CPA": r"\bcpa\b", "ACCA": r"\bacca\b",
               "CFA": r"\bcfa\b", "CIMA": r"\bcima\b", "Scrum Master certification": r"\b(csm|certified scrum master)\b",
               "Six Sigma": r"six sigma"}


def experience_required(title: str, text: str, level: int) -> list[str]:
    """Backgrounds a posting requires: from an explicit ask ("3+ years in account management",
    "sales experience required"), or from the title when the role is above entry level and
    doesn't say it will train you. Also mandatory certifications ("PMP required")."""
    needed = []
    open_door = bool(_OPEN_DOOR.search(text))
    for area, spec in EXPERIENCE_AREAS.items():
        asks = spec["asks"]
        patterns = [
            rf"\b(experience|background|track record|years)\s+(\w+\s+){{0,2}}(in|within|as|of|selling)\s+"
            rf"(an?\s+|the\s+)?(\w+\s+){{0,2}}?{asks}\b{_NOT_THE_AREA}",
            rf"\b{asks}\b{_NOT_THE_AREA}\s+(\w+\s+){{0,1}}(experience|background)",
        ]
        if area == "sales":
            patterns.append(r"track record of (meeting|exceeding|achieving|hitting) (\w+ ){0,2}targets")
        asked = False
        for sentence in re.split(r"(?<=[.!?;])\s+|\n+", text):
            if any(re.search(p, sentence, re.I) for p in patterns) and not _SOFT_ASK.search(sentence):
                asked = True
                break
        by_title = level >= 2 and not open_door and bool(re.search(spec["title"], title, re.I))
        if asked or by_title:
            needed.append(area)
    for name, pattern in CREDENTIALS.items():
        for sentence in re.split(r"(?<=[.!?;])\s+|\n+", text):
            if re.search(pattern, sentence, re.I) and re.search(r"required|mandatory|must", sentence, re.I) \
                    and not _SOFT_ASK.search(sentence):
                needed.append(f"{name} certification" if "certification" not in name else name)
                break
    return needed


def experience_you_have(resume_text: str, skills: set[str], titles: list[str]) -> set[str]:
    """The backgrounds from EXPERIENCE_AREAS (and certifications) your resume shows."""
    have = set()
    joined_titles = " ".join(titles)
    for area, spec in EXPERIENCE_AREAS.items():
        if spec["skills"] & skills or re.search(spec["title"], joined_titles, re.I) or \
                re.search(rf"\b(?:{spec['evidence']})\b", resume_text, re.I):  # \b: "quota" isn't "quotations"
            have.add(area)
    for name, pattern in CREDENTIALS.items():
        if re.search(pattern, resume_text, re.I):
            have.add(f"{name} certification" if "certification" not in name else name)
    return have
