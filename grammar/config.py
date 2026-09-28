from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_PATH = BASE_DIR / "models.json"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None else int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None else float(raw)


def _load_models() -> dict[str, Any]:
    with MODELS_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@dataclass(slots=True)
class LanguageToolSettings:
    enabled: bool = True
    url: str = "http://localhost:8081/v2/check"
    language: str = "en-US"
    level: str = "picky"
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 7.0
    retries: int = 1
    backoff_seconds: float = 0.5
    ngrams_path: str | None = None

    def is_local(self) -> bool:
        parsed = urlparse(self.url)
        host = parsed.hostname or ""
        return host in {"localhost", "127.0.0.1", "::1"}


@dataclass(slots=True)
class ValidationThresholds:
    max_character_edit_ratio: float = 0.25
    max_changed_word_ratio: float = 0.25
    min_length_ratio: float = 0.75
    max_length_ratio: float = 1.25


@dataclass(slots=True)
class RoutingPolicy:
    auto_apply_rule_ids: set[str] = field(default_factory=lambda: {
        "ENGLISH_WORD_REPEAT_RULE",
        "WHITESPACE_RULE",
        "UPPERCASE_SENTENCE_START",
        "DOUBLE_PUNCTUATION",
        "SENTENCE_WHITESPACE",
    })
    qwen_route_rule_ids: set[str] = field(default_factory=set)
    suggest_only_rule_ids: set[str] = field(default_factory=lambda: {
        "STYLE",
    })
    ignored_rule_ids: set[str] = field(default_factory=set)
    high_confidence_issue_types: set[str] = field(default_factory=lambda: {
        "grammar",
        "misspelling",
        "typographical",
    })
    low_confidence_issue_types: set[str] = field(default_factory=lambda: {
        "style",
        "locale-violation",
    })


@dataclass(slots=True)
class AppConfig:
    languagetool: LanguageToolSettings
    validation: ValidationThresholds
    routing: RoutingPolicy
    models: dict[str, Any]
    qwen_model_name: str = "qwen"
    allow_model_only_mode: bool = False


def load_app_config() -> AppConfig:
    models = _load_models()

    languagetool = LanguageToolSettings(
        enabled=_env_bool("LANGUAGETOOL_ENABLED", True),
        url=os.getenv("LANGUAGETOOL_URL", "http://localhost:8081/v2/check"),
        language=os.getenv("LANGUAGETOOL_LANGUAGE", "en-US"),
        level=os.getenv("LANGUAGETOOL_LEVEL", "picky"),
        connect_timeout_seconds=_env_float(
            "LANGUAGETOOL_CONNECT_TIMEOUT_SECONDS",
            3.0,
        ),
        read_timeout_seconds=_env_float(
            "LANGUAGETOOL_READ_TIMEOUT_SECONDS",
            _env_float("LANGUAGETOOL_TIMEOUT_SECONDS", 10.0),
        ),
        retries=_env_int("LANGUAGETOOL_RETRIES", 1),
        backoff_seconds=_env_float("LANGUAGETOOL_BACKOFF_SECONDS", 0.5),
        ngrams_path=os.getenv("LANGUAGETOOL_NGRAMS_PATH"),
    )

    validation = ValidationThresholds(
        max_character_edit_ratio=_env_float(
            "VALIDATION_MAX_CHARACTER_EDIT_RATIO",
            0.25,
        ),
        max_changed_word_ratio=_env_float(
            "VALIDATION_MAX_CHANGED_WORD_RATIO",
            0.25,
        ),
        min_length_ratio=_env_float("VALIDATION_MIN_LENGTH_RATIO", 0.75),
        max_length_ratio=_env_float("VALIDATION_MAX_LENGTH_RATIO", 1.25),
    )

    routing = RoutingPolicy()

    return AppConfig(
        languagetool=languagetool,
        validation=validation,
        routing=routing,
        models=models,
        qwen_model_name=os.getenv("QWEN_MODEL_NAME", "qwen"),
        allow_model_only_mode=_env_bool("ALLOW_MODEL_ONLY_MODE", False),
    )

