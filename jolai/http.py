"""A small, polite HTTP client: on-disk cache, retries, per-host rate limiting, robots.txt."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "JolAI/0.1 (personal job search tool; +https://github.com/rishivinod7/JolAI)"


class Fetcher:
    def __init__(self, cache_dir: str | Path = ".jolai_cache", cache_ttl: float = 6 * 3600,
                 min_interval: float = 1.0, timeout: float = 20.0):
        self.cache_dir = Path(cache_dir)
        self.cache_ttl = cache_ttl
        self.min_interval = min_interval
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"})
        retry = Retry(total=3, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET",), respect_retry_after_header=True)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    # -- public -----------------------------------------------------------------
    def get_text(self, url: str, *, check_robots: bool = False) -> str:
        cached = self._cache_read(url)
        if cached is not None:
            return cached
        if check_robots and not self.allowed(url):
            raise PermissionError(f"robots.txt disallows fetching {url}")
        self._throttle(url)
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        self._cache_write(url, resp.text)
        return resp.text

    def get_json(self, url: str):
        return json.loads(self.get_text(url))

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            if origin not in self._robots:
                parser = RobotFileParser()
                try:
                    resp = self.session.get(origin + "/robots.txt", timeout=self.timeout)
                    if resp.status_code >= 400:
                        parser = None  # no robots.txt -> everything allowed
                    else:
                        parser.parse(resp.text.splitlines())
                except requests.RequestException:
                    parser = None
                self._robots[origin] = parser
            parser = self._robots[origin]
        return parser is None or parser.can_fetch(USER_AGENT, url)

    # -- internals --------------------------------------------------------------
    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        with self._lock:
            wait = self._last_hit.get(host, 0) + self.min_interval - time.monotonic()
            self._last_hit[host] = time.monotonic() + max(wait, 0)
        if wait > 0:
            time.sleep(wait)

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".txt")

    def _cache_read(self, url: str) -> str | None:
        if self.cache_ttl <= 0:
            return None
        path = self._cache_path(url)
        if path.exists() and time.time() - path.stat().st_mtime < self.cache_ttl:
            return path.read_text(encoding="utf-8")
        return None

    def _cache_write(self, url: str, body: str) -> None:
        if self.cache_ttl <= 0:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(url).write_text(body, encoding="utf-8")
