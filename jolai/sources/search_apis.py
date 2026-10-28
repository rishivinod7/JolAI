"""Job-search engines with official APIs: Adzuna and Jooble.

They gather listings from many job boards, so one search covers a whole country. Both
need a free API key:

* Adzuna: sign up at https://developer.adzuna.com/ and get an app_id and app_key.
  Covers India and Singapore (and the UK, US, Australia, much of Europe), but not Hong Kong.
* Jooble: request a key at https://jooble.org/api/about. Covers Hong Kong, India,
  Singapore and most other countries.

Put the keys in config.yaml (sources.adzuna.app_id / app_key, sources.jooble.api_key) or in
the environment variables ADZUNA_APP_ID, ADZUNA_APP_KEY and JOOBLE_API_KEY.

Both return a short summary of each job rather than the full description, so the scores
for these jobs rely more on the title. Open the job to read the whole posting.
"""

from __future__ import annotations

import os
from urllib.parse import quote, urlencode

import requests

from ..http import Fetcher
from ..models import Job
from .base import html_to_text, looks_remote, to_number

# Adzuna country codes we know about -> country name (used so the work-permit check can read the location).
ADZUNA_COUNTRIES = {
    "in": "India", "sg": "Singapore", "gb": "United Kingdom", "us": "United States", "au": "Australia",
    "nz": "New Zealand", "ca": "Canada", "de": "Germany", "fr": "France", "nl": "Netherlands", "es": "Spain",
    "it": "Italy", "at": "Austria", "be": "Belgium", "ch": "Switzerland", "pl": "Poland", "br": "Brazil",
    "mx": "Mexico", "za": "South Africa",
}
ADZUNA_CURRENCY = {"in": "INR", "sg": "SGD", "gb": "GBP", "us": "USD", "au": "AUD", "nz": "NZD", "ca": "CAD",
                   "de": "EUR", "fr": "EUR", "nl": "EUR", "es": "EUR", "it": "EUR", "at": "EUR", "be": "EUR",
                   "ch": "CHF", "pl": "PLN", "br": "BRL", "mx": "MXN", "za": "ZAR"}


class MissingKey(RuntimeError):
    pass


def _http_error(exc: requests.HTTPError, service: str) -> RuntimeError:
    """Re-raise HTTP errors without the URL, which contains your API key."""
    code = exc.response.status_code if exc.response is not None else "?"
    hint = " (check your API key)" if code in (401, 403) else " (rate limit, try later)" if code == 429 else ""
    return RuntimeError(f"{service} returned HTTP {code}{hint}")


# -- Adzuna ------------------------------------------------------------------------------

def adzuna_keys(cfg: dict) -> tuple[str, str]:
    app_id = cfg.get("app_id") or os.environ.get("ADZUNA_APP_ID")
    app_key = cfg.get("app_key") or os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise MissingKey("Adzuna needs an app_id and app_key: sign up free at developer.adzuna.com")
    return app_id, app_key


def adzuna(fetcher: Fetcher, query: dict) -> list[Job]:
    """One search: ``query = {"country": "in", "what": "business analyst", "app_id": …, "app_key": …}``."""
    country = query["country"].lower()
    jobs = []
    for page in range(1, int(query.get("pages", 1)) + 1):
        params = {"app_id": query["app_id"], "app_key": query["app_key"], "results_per_page": 50,
                  "what": query.get("what", ""), "max_days_old": int(query.get("max_days_old", 30)),
                  "content-type": "application/json"}
        if query.get("where"):
            params["where"] = query["where"]
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}?{urlencode(params)}"
        try:
            data = fetcher.get_json(url)
        except requests.HTTPError as exc:
            raise _http_error(exc, "Adzuna") from None
        results = data.get("results") or []
        jobs += [_adzuna_job(item, country) for item in results]
        if len(results) < 50:
            break
    return jobs


def _adzuna_job(item: dict, country: str) -> Job:
    location = item.get("location") or {}
    name = location.get("display_name") or ""
    country_name = ADZUNA_COUNTRIES.get(country, "")
    # Make sure the country is in the location text, so "Bengaluru, Karnataka" reads as India.
    if country_name and country_name.lower() not in name.lower():
        name = f"{name}, {country_name}" if name else country_name
    predicted = str(item.get("salary_is_predicted", "0")) == "1"  # Adzuna's own estimate, not from the posting
    title = html_to_text(item.get("title"))
    description = html_to_text(item.get("description"))
    category = (item.get("category") or {}).get("label")
    return Job(
        title=title,
        company=((item.get("company") or {}).get("display_name") or "").strip(),
        url=item.get("redirect_url", ""),
        source="adzuna",
        location=name,
        description=description,
        remote=looks_remote(title, name),
        posted_at=item.get("created"),
        salary_min=None if predicted else to_number(item.get("salary_min")),
        salary_max=None if predicted else to_number(item.get("salary_max")),
        salary_currency=ADZUNA_CURRENCY.get(country),
        tags=[t for t in (category, item.get("contract_time"), item.get("contract_type")) if t],
    )


# -- Jooble ------------------------------------------------------------------------------

def jooble_key(cfg: dict) -> str:
    key = cfg.get("api_key") or os.environ.get("JOOBLE_API_KEY")
    if not key:
        raise MissingKey("Jooble needs an API key: request one free at jooble.org/api/about")
    return key


def jooble(fetcher: Fetcher, query: dict) -> list[Job]:
    """One search: ``query = {"location": "Hong Kong", "keywords": "business analyst", "api_key": …}``."""
    url = f"https://jooble.org/api/{quote(query['api_key'])}"
    jobs = []
    for page in range(1, int(query.get("pages", 1)) + 1):
        body = {"keywords": query.get("keywords", ""), "location": query.get("location", ""), "page": str(page)}
        try:
            data = fetcher.post_json(url, body)
        except requests.HTTPError as exc:
            raise _http_error(exc, "Jooble") from None
        results = data.get("jobs") or []
        jobs += [_jooble_job(item, query.get("location", "")) for item in results]
        if not results:
            break
    return jobs


def _jooble_job(item: dict, searched_location: str) -> Job:
    location = html_to_text(item.get("location")) or searched_location
    # Jooble often gives just a city or district ("Central"); add the place we searched so the
    # work-permit check can tell which country it's in.
    if searched_location and searched_location.lower() not in location.lower():
        location = f"{location}, {searched_location}"
    title = html_to_text(item.get("title"))
    salary = (item.get("salary") or "").strip()
    return Job(
        title=title,
        company=(item.get("company") or "").strip(),
        url=item.get("link", ""),
        source="jooble",
        location=location,
        description=html_to_text(item.get("snippet")),
        remote=looks_remote(title, location),
        posted_at=item.get("updated"),
        # Jooble's salary is free text in local currency ("HK$25,000 - 30,000 per month"); kept as a tag.
        tags=[t for t in (item.get("type"), item.get("source"), f"pay: {salary}" if salary else "") if t],
    )
