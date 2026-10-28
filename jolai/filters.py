"""Free, rule-based checks that read a job posting the way you would skim it.

These run on every job (no AI, no cost) and answer three questions:

1. Does it require a language other than English?   -> ``language_requirements``
2. How technical is it, on a 0-100 scale?           -> ``technical_score``
3. How much experience does it ask for?             -> ``matcher.years_required`` (lives with the scorer)

The scorer uses the answers to drop jobs you said you don't want (see ``Preferences``).
"""

from __future__ import annotations

import re

from .skills import extract_skills

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
# Skills from the vocabulary that signal hands-on technical work.
NON_TECH_SKILLS = {"Excel", "Salesforce", "SEO", "Agile", "Jira", "Project Management", "Leadership",
                   "Product Management", "UX Design", "Figma", "Tableau", "Power BI", "Looker",
                   "Communication", "Customer Service", "Sales", "Marketing", "Social Media", "Content Writing",
                   "Operations", "Recruiting", "Accounting", "HubSpot", "Zendesk", "Google Workspace",
                   "Microsoft Office", "Event Planning", "Copywriting", "Research", "Data Entry", "Teaching",
                   "Administration", "Bookkeeping", "Statistics", "A/B Testing", "Canva"}


def technical_score(title: str, text: str) -> int:
    """0 = not technical at all (e.g. customer success), 100 = deeply technical (e.g. backend engineer).

    Mixes three signals: an engineering-style title, how many hands-on tech skills the posting
    lists, and phrases like "coding" or "system design".
    """
    title_points = 45 if TECH_TITLE_RE.search(title) else 20 if SOFT_TECH_TITLE_RE.search(title) else 0
    tech_skills = extract_skills(text) - NON_TECH_SKILLS
    skill_points = min(35, len(tech_skills) * 5)
    phrase_points = min(20, len(set(m.lower() for m in TECH_PHRASES.findall(text))) * 4)
    return min(100, title_points + skill_points + phrase_points)


def technical_label(score: int) -> str:
    return "low" if score < 35 else "medium" if score < 65 else "high"
