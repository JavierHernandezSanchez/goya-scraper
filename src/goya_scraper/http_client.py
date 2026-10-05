"""HTTP with a disk cache, retries, rate limiting and robots.txt.

The only module that knows the internet exists.

Cache is the load-bearing idea here. The server sends no ETag and no
Last-Modified, so there is nothing to revalidate against; "the file is already on
disk" is the only way to avoid re-downloading (ADR-010).
"""

import logging
import re
import time
from pathlib import Path
from urllib.parse import quote
from urllib.robotparser import RobotFileParser

import requests

from .model import SITE_URL

log = logging.getLogger(__name__)

USER_AGENT = "goya-scraper/0.1 (+https://github.com/JavierHernandezSanchez/goya-scraper)"
TIMEOUT = (10, 30)  # (connect, read) seconds
MIN_INTERVAL = 1.2  # seconds between requests
RETRIES = 3
RETRY_DELAYS = (2, 4, 8)  # seconds before retry 1, 2, 3
CACHE_DIR = Path("cache")

# Only these are worth retrying: the server had a bad moment.
# 404 means the page is not there, and 403/429 mean we are not welcome. We do
# not work around either (docs/scraping.md).
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


class HttpError(RuntimeError):
    """A request failed.

    status is the HTTP code when there was one, None for network-level failures.
    That distinction matters: a 404 means the page does not exist, a network
    error means we should try again later.
    """

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class RobotsDisallowed(HttpError):
    """robots.txt does not allow us to fetch this URL."""


def cache_filename(path: str) -> str:
    """Turn a URL path into a filename that stays inside the cache directory.

    Everything outside [A-Za-z0-9._-] is percent-encoded, so no path can contain
    a separator and nothing can escape the directory with "..". Every slug on this
    site is plain ASCII, so the encoding never actually kicks in.

    Known limitation: "/a/b" and "/a_b" map to the same name. That cannot happen
    with this site's URLs, which are only /{n}-edicion/nominaciones/ and
    /pelicula/{slug}/, and it would take a deliberate typo to cause it.
    """
    key = path.strip("/").replace("/", "_")
    return f"{quote(key, safe='-._')}.html"


class HttpClient:
    def __init__(
        self,
        base_url: str = SITE_URL,
        min_interval: float = MIN_INTERVAL,
        timeout: tuple[int, int] = TIMEOUT,
        cache_dir: Path | None = CACHE_DIR,
        retries: int = RETRIES,
        retry_delays: tuple[int, ...] = RETRY_DELAYS,
        respect_robots: bool = True,
        session=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.min_interval = min_interval
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.retries = retries
        self.retry_delays = retry_delays
        self.respect_robots = respect_robots

        self._session = session if session is not None else requests.Session()
        self._session.headers.setdefault("User-Agent", USER_AGENT)

        self._last_request = 0.0
        self._robots: RobotFileParser | None = None
        self._robots_loaded = False

    # -- politeness ---------------------------------------------------------------

    def _wait_turn(self) -> None:
        """Keep at least min_interval between requests that reach the server."""
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def _load_robots(self) -> RobotFileParser | None:
        """Return the parsed robots.txt, or None when there is nothing to obey.

        This site answers 404, which correctly means "no restrictions declared".
        """
        url = f"{self.base_url}/robots.txt"
        try:
            response = self._session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            log.warning("could not read robots.txt (%s); assuming none", exc)
            return None

        if response.status_code == 404:
            log.info("no robots.txt at %s; no restrictions declared", url)
            return None
        if response.status_code != 200:
            log.warning(
                "robots.txt returned HTTP %s; assuming none", response.status_code
            )
            return None

        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        log.info("robots.txt loaded from %s", url)
        return parser

    def _robots_allows(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        if not self._robots_loaded:
            self._robots_loaded = True
            self._robots = self._load_robots()
        if self._robots is None:
            return True
        allowed = self._robots.can_fetch(USER_AGENT, url)
        if not allowed:
            log.error("robots.txt disallows %s; not requesting it", url)
        return allowed

    # -- fetching -----------------------------------------------------------------

    def get(self, path: str) -> str:
        """Return the HTML for a path, from cache when possible."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        cached = self._cache_path(path)

        if cached is not None and cached.exists():
            log.debug("cache hit %s", path)
            return cached.read_text(encoding="utf-8")

        if not self._robots_allows(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")

        html = self._fetch(url)

        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(html, encoding="utf-8")
        return html

    def _cache_path(self, path: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / cache_filename(path)

    def _fetch(self, url: str) -> str:
        """Request a URL, retrying only what is worth retrying."""
        last_error: HttpError | None = None

        for attempt in range(1, self.retries + 1):
            self._wait_turn()
            try:
                response = self._session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = HttpError(f"{url}: {exc}")
            else:
                if response.status_code == 200:
                    if not response.encoding:
                        response.encoding = response.apparent_encoding
                    return response.text

                last_error = HttpError(
                    f"{url}: HTTP {response.status_code}",
                    status=response.status_code,
                )
                if response.status_code not in RETRYABLE_STATUS:
                    raise last_error
            finally:
                # Updated in every case. A timeout still means we spent 30
                # seconds hammering the server, so the next attempt has to wait
                # like any other request.
                self._last_request = time.monotonic()

            if attempt < self.retries:
                delay = self.retry_delays[min(attempt, len(self.retry_delays)) - 1]
                log.warning(
                    "%s (attempt %s/%s), retrying in %ss",
                    last_error, attempt, self.retries, delay,
                )
                time.sleep(delay)

        raise last_error  # type: ignore[misc]  # always set if we got here