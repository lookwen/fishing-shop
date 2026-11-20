"""HTTP fetching with robots.txt support, rate limiting, and bounded retries."""

import logging
import time
from dataclasses import dataclass
from email.message import Message
from threading import Lock, local
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

LOGGER = logging.getLogger("scraper.fetcher")
MIN_REQUEST_INTERVAL_SECONDS = 0.5
RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5


class FetchError(RuntimeError):
    """Raised when an HTTP page cannot be fetched successfully."""


class RobotsDeniedError(FetchError):
    """Raised when robots.txt disallows a URL."""


@dataclass(frozen=True)
class PageResponse:
    url: str
    status: int
    headers: Message
    body: bytes


class _NoAutomaticRedirect(HTTPRedirectHandler):
    """Expose redirects so each individual request passes through the limiter."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PageFetcher:
    """Fetch pages with one shared two-requests-per-second limit."""

    def __init__(
        self,
        user_agent: str,
        timeout_seconds: float = 20,
        max_retries: int = 2,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("user_agent cannot be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be between 0 and 5")

        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._thread_state = local()
        self._robots_lock = Lock()
        self._rate_lock = Lock()
        self._last_request_at = 0.0
        self._robots_cache: dict[str, RobotFileParser] = {}

    def fetch_page(self, url: str) -> PageResponse:
        """Fetch a URL only when its robots.txt policy permits it."""
        self._check_robots(url)
        response = self._request_following_redirects(
            url, check_redirect_policy=True
        )
        if not 200 <= response.status < 300:
            raise FetchError(f"Unexpected HTTP status {response.status} for {url}")
        LOGGER.info(
            "Fetched %s (HTTP %s, %s bytes)",
            response.url,
            response.status,
            len(response.body),
        )
        return response

    def _check_robots(self, url: str) -> None:
        with self._robots_lock:
            self._check_robots_locked(url)

    def _check_robots_locked(self, url: str) -> None:
        parts = urlsplit(url)
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        parser = self._robots_cache.get(origin)
        if parser is None:
            robots_url = urljoin(origin + "/", "robots.txt")
            LOGGER.info("Fetching robots policy: %s", robots_url)
            response = self._request_following_redirects(
                robots_url, accepted_statuses={401, 403, 404}
            )
            parser = RobotFileParser()
            parser.set_url(robots_url)
            if response.status == 404:
                parser.parse([])
                LOGGER.info("No robots.txt found at %s", robots_url)
            elif response.status in {401, 403}:
                parser.parse(["User-agent: *", "Disallow: /"])
                LOGGER.warning("Robots policy at %s denies crawling", robots_url)
            elif 200 <= response.status < 300:
                parser.parse(response.body.decode("utf-8", errors="replace").splitlines())
            else:
                raise FetchError(
                    f"Cannot determine robots policy at {robots_url}: "
                    f"HTTP {response.status}"
                )
            self._robots_cache[origin] = parser

        if not parser.can_fetch(self.user_agent, url):
            LOGGER.warning("Skipping URL disallowed by robots.txt: %s", url)
            raise RobotsDeniedError(f"robots.txt disallows {url}")

    def _request_following_redirects(
        self,
        url: str,
        *,
        check_redirect_policy: bool = False,
        accepted_statuses: set[int] | None = None,
    ) -> PageResponse:
        current_url = url
        accepted_statuses = accepted_statuses or set()
        for redirect_count in range(MAX_REDIRECTS + 1):
            response = self._request_with_retries(current_url, accepted_statuses)
            if response.status not in REDIRECT_STATUSES:
                return response

            location = response.headers.get("Location")
            if not location:
                raise FetchError(f"Redirect from {current_url} has no Location header")
            if redirect_count == MAX_REDIRECTS:
                raise FetchError(f"Too many redirects while fetching {url}")

            next_url = urljoin(current_url, location)
            LOGGER.info(
                "Following HTTP %s redirect: %s -> %s",
                response.status,
                current_url,
                next_url,
            )
            if check_redirect_policy:
                self._check_robots(next_url)
            current_url = next_url

        raise FetchError(f"Too many redirects while fetching {url}")

    def _request_with_retries(
        self, url: str, accepted_statuses: set[int]
    ) -> PageResponse:
        for attempt in range(self.max_retries + 1):
            try:
                response = self._single_request(url)
                if response.status in accepted_statuses:
                    return response
                if response.status in RETRYABLE_STATUSES:
                    raise FetchError(f"HTTP {response.status} for {url}")
                if response.status >= 400:
                    raise FetchError(f"HTTP {response.status} for {url}")
                return response
            except (FetchError, URLError, TimeoutError, OSError) as exc:
                retryable = not isinstance(exc, FetchError) or any(
                    f"HTTP {status}" in str(exc) for status in RETRYABLE_STATUSES
                )
                if not retryable or attempt >= self.max_retries:
                    LOGGER.error(
                        "Request failed after %s attempt(s): %s (%s)",
                        attempt + 1,
                        url,
                        exc,
                    )
                    if isinstance(exc, FetchError):
                        raise
                    raise FetchError(f"Request failed for {url}: {exc}") from exc

                delay = min(2**attempt, 8)
                LOGGER.warning(
                    "Request failed (%s); retry %s/%s in %s second(s): %s",
                    exc,
                    attempt + 1,
                    self.max_retries,
                    delay,
                    url,
                )
                time.sleep(delay)

        raise FetchError(f"Request failed for {url}")

    def _single_request(self, url: str) -> PageResponse:
        self._wait_for_rate_limit()
        request = Request(url, headers={"User-Agent": self.user_agent})
        if not hasattr(self._thread_state, "opener"):
            self._thread_state.opener = build_opener(_NoAutomaticRedirect())
        try:
            with self._thread_state.opener.open(request, timeout=self.timeout_seconds) as response:
                return PageResponse(
                    url=response.geturl(),
                    status=response.status,
                    headers=response.headers,
                    body=response.read(),
                )
        except HTTPError as response:
            try:
                return PageResponse(
                    url=response.geturl(),
                    status=response.code,
                    headers=response.headers,
                    body=response.read(),
                )
            finally:
                response.close()
        except (URLError, TimeoutError, OSError) as exc:
            LOGGER.warning("Network request error for %s: %s", url, exc)
            raise

    def _wait_for_rate_limit(self) -> None:
        with self._rate_lock:
            now = time.monotonic()
            wait_seconds = MIN_REQUEST_INTERVAL_SECONDS - (now - self._last_request_at)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._last_request_at = time.monotonic()
