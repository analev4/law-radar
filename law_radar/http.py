"""One polite HTTP client for every source.

- about one request per second per host;
- a user agent that names the project;
- backoff and retry on 429 and 5xx;
- no retry on 403 or a bot challenge: those raise Blocked and the source is skipped.
"""
from __future__ import annotations

import os
import time
from typing import Dict, Optional
from urllib.parse import urlparse

import httpx

from . import __version__

def _repo_url() -> str:
    if os.environ.get("LAW_RADAR_REPO_URL"):
        return os.environ["LAW_RADAR_REPO_URL"]
    if os.environ.get("GITHUB_REPOSITORY"):   # set by GitHub Actions
        return f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ['GITHUB_REPOSITORY']}"
    return ""


USER_AGENT = f"law-radar/{__version__}" + (f" (+{_repo_url()})" if _repo_url() else "")
MIN_INTERVAL_SECONDS = 1.0
MAX_RETRIES = 3


class Blocked(Exception):
    """The publisher refused automated access. Never retried."""


class FetchError(Exception):
    pass


class PoliteClient:
    def __init__(self, min_interval: float = MIN_INTERVAL_SECONDS, timeout: float = 60.0):
        self.min_interval = min_interval
        self._last: Dict[str, float] = {}
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
        )

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            delay = self.min_interval - (time.monotonic() - last)
            if delay > 0:
                time.sleep(delay)
        self._last[host] = time.monotonic()

    def get(self, url: str, headers: Optional[Dict[str, str]] = None,
            params: Optional[Dict[str, str]] = None) -> httpx.Response:
        host = urlparse(url).netloc
        backoff = 2.0
        for attempt in range(MAX_RETRIES + 1):
            self._wait(host)
            try:
                resp = self._client.get(url, headers=headers, params=params)
            except httpx.TransportError as exc:
                if attempt == MAX_RETRIES:
                    raise FetchError(f"{url}: {exc}") from exc
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.headers.get("x-amzn-waf-action") or (resp.status_code == 202 and not resp.content):
                raise Blocked(f"{url}: bot challenge (HTTP {resp.status_code})")
            if resp.status_code == 403:
                raise Blocked(f"{url}: HTTP 403")
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == MAX_RETRIES:
                    raise FetchError(f"{url}: HTTP {resp.status_code} after {MAX_RETRIES} retries")
                retry_after = resp.headers.get("retry-after")
                time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else backoff)
                backoff *= 2
                continue
            return resp
        raise FetchError(url)  # unreachable

    def close(self) -> None:
        self._client.close()
