from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from grammar.config import LanguageToolSettings


LOGGER = logging.getLogger(__name__)


class LanguageToolUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class LanguageToolResponse:
    text: str
    language: str
    matches: list[dict[str, Any]]
    raw: dict[str, Any]


class LanguageToolClient:
    def __init__(self, settings: LanguageToolSettings) -> None:
        self.settings = settings
        self.session = requests.Session()

    def check(self, text: str) -> LanguageToolResponse:
        if not self.settings.enabled:
            raise LanguageToolUnavailable("LanguageTool is disabled by config")

        timeout = (self.settings.connect_timeout_seconds, self.settings.read_timeout_seconds)
        payload = {
            "language": self.settings.language,
            "level": self.settings.level,
            "text": text,
        }

        last_error: Exception | None = None
        for attempt in range(self.settings.retries + 1):
            try:
                started = time.perf_counter()
                response = self.session.post(self.settings.url, data=payload, timeout=timeout)
                elapsed = time.perf_counter() - started
                response.raise_for_status()
                raw = response.json()
                matches = raw.get("matches", [])
                LOGGER.debug(
                    "languagetool_response",
                    extra={
                        "latency_seconds": round(elapsed, 4),
                        "match_count": len(matches),
                        "language": self.settings.language,
                        "enabled": True,
                    },
                )
                return LanguageToolResponse(
                    text=text,
                    language=self.settings.language,
                    matches=matches,
                    raw=raw,
                )
            except (requests.Timeout, requests.ConnectionError) as error:
                last_error = error
                if attempt >= self.settings.retries:
                    break
                time.sleep(self.settings.backoff_seconds * (attempt + 1))
            except requests.HTTPError as error:
                status = getattr(error.response, "status_code", None)
                if status in {429, 500, 502, 503, 504} and attempt < self.settings.retries:
                    last_error = error
                    time.sleep(self.settings.backoff_seconds * (attempt + 1))
                    continue
                raise LanguageToolUnavailable(f"LanguageTool request failed: {error}") from error
            except ValueError as error:
                raise LanguageToolUnavailable(f"LanguageTool returned invalid JSON: {error}") from error

        raise LanguageToolUnavailable(f"LanguageTool unavailable: {last_error}") from last_error

