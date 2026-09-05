"""Provider configuration parsing for the PxAPI v2 adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from nordicintel_core.errors import ConfigurationError
from nordicintel_core.models import ProviderDefinition


def normalize_language(value: str) -> str:
    """Normalize one language code at the adapter seam."""
    normalized = value.strip().lower()
    if not normalized:
        raise ConfigurationError("language codes must not be blank")
    return normalized


def normalize_languages(values: Iterable[str]) -> list[str]:
    """Normalize language codes while preserving first-seen order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        language = normalize_language(value)
        if language not in seen:
            normalized.append(language)
            seen.add(language)
    if not normalized:
        raise ConfigurationError("at least one language must be configured")
    return normalized


@dataclass(frozen=True, slots=True)
class AuthConfig:
    """Optional request authentication resolved from provider secrets."""

    header_name: str | None = None
    header_secret: str | None = None
    query_param: str | None = None
    query_secret: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> AuthConfig:
        if value is None:
            return cls()
        header_name = _optional_str(value, "header_name")
        header_secret = _optional_str(value, "header_secret")
        query_param = _optional_str(value, "query_param")
        query_secret = _optional_str(value, "query_secret")
        if bool(header_name) != bool(header_secret):
            raise ConfigurationError(
                "auth.header_name and auth.header_secret must be set together"
            )
        if bool(query_param) != bool(query_secret):
            raise ConfigurationError(
                "auth.query_param and auth.query_secret must be set together"
            )
        return cls(
            header_name=header_name,
            header_secret=header_secret,
            query_param=query_param,
            query_secret=query_secret,
        )

    def request_kwargs(self, secrets: Mapping[str, str]) -> dict[str, Any]:
        """Return safe HTTP keyword arguments for configured authentication."""
        kwargs: dict[str, Any] = {}
        if self.header_name and self.header_secret:
            kwargs["headers"] = {
                self.header_name: _required_secret(secrets, self.header_secret)
            }
        if self.query_param and self.query_secret:
            kwargs["params"] = {
                self.query_param: _required_secret(secrets, self.query_secret)
            }
        return kwargs


@dataclass(frozen=True, slots=True)
class PxWebConfig:
    """Runtime configuration for one PxAPI v2 provider."""

    base_api_url: str
    languages: tuple[str, ...]
    default_language: str | None = None
    page_size: int = 1000
    auth: AuthConfig = AuthConfig()

    @classmethod
    def from_provider(cls, provider: ProviderDefinition) -> PxWebConfig:
        config = provider.config
        base_api_url = _optional_str(config, "base_api_url") or _optional_str(
            config, "base_url"
        )
        if base_api_url is None:
            raise ConfigurationError("provider.config.base_api_url is required")
        base_api_url = base_api_url.strip().rstrip("/")
        if not base_api_url:
            raise ConfigurationError("provider.config.base_api_url must not be blank")

        languages_value = config.get("languages")
        languages = (
            tuple(normalize_languages(languages_value)) if languages_value else ()
        )
        default_language = _optional_str(config, "default_language")
        if default_language is not None:
            default_language = normalize_language(default_language)
        page_size = _positive_int(config.get("page_size", 1000), "page_size")
        auth_value = config.get("auth")
        if auth_value is not None and not isinstance(auth_value, Mapping):
            raise ConfigurationError(
                "provider.config.auth must be an object when supplied"
            )
        return cls(
            base_api_url=base_api_url,
            languages=languages,
            default_language=default_language,
            page_size=page_size,
            auth=AuthConfig.from_mapping(auth_value),
        )


def _optional_str(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"provider.config.{key} must be a string")
    value = value.strip()
    return value or None


def _positive_int(value: Any, key: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigurationError(f"provider.config.{key} must be a positive integer")
    return value


def _required_secret(secrets: Mapping[str, str], key: str) -> str:
    value = secrets.get(key)
    if value is None or not value:
        raise ConfigurationError(f"secret '{key}' is required")
    return value
