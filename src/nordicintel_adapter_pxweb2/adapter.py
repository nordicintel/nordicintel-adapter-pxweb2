"""NordicIntel adapter implementation for PxAPI v2 providers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

from nordicintel_core.jsonstat import JsonStatDataset
from nordicintel_core.models import (
    AsyncHttpClient,
    DiscoveryEntry,
    DiscoveryResult,
    DiscoveryScope,
    ExplicitSelection,
    LanguageMetadata,
    LanguageState,
    Link,
    MetadataFetchResult,
    PathElement,
    ProviderDefinition,
    TableCatalogMetadata,
    TableCategory,
    TimeUnit,
)

from .config import PxWebConfig, normalize_language, normalize_languages
from .endpoints import endpoint_url


class PxWebAdapter:
    """Translate PxAPI v2 responses into NordicIntel core contracts."""

    def __init__(
        self,
        provider: ProviderDefinition,
        secrets: Mapping[str, str],
        http: AsyncHttpClient,
    ) -> None:
        self.provider = provider
        self.secrets = dict(secrets)
        self.http = http
        self.config = PxWebConfig.from_provider(provider)
        # One adapter serves one job, so the service description is fetched at most once.
        self._service: Mapping[str, Any] | None = None

    async def resolve_languages(self, requested: Sequence[str] | None) -> list[str]:
        supported = await self._supported_languages()
        if requested is None:
            return supported
        normalized = normalize_languages(requested)
        unsupported = [language for language in normalized if language not in supported]
        if unsupported:
            raise ValueError(f"unsupported language(s) for {self.provider.id}: {unsupported}")
        return normalized

    async def discover(self, scope: DiscoveryScope) -> DiscoveryResult:
        """Enumerate the requested scope.

        A catalogue is not the same size in every language: PxAPI v2 omits a table
        entirely from a language it was never published in. Listing in whichever language
        a job happened to ask for first would therefore report a smaller inventory as if
        it were the whole provider, and absence-based retirement would delete every table
        missing from that language. The enumeration runs in the provider's default
        language for that reason, and only claims to be authoritative when that language
        is known.
        """
        if scope.native_table_id is not None:
            table = await self._get_table(scope.native_table_id, scope.languages[0])
            return DiscoveryResult(
                scope=scope, entries=[self._discovery_entry(table)], authoritative=False
            )

        if self.config.table_ids:
            entries = [
                self._discovery_entry(await self._get_table(native, scope.languages[0]))
                for native in self.config.table_ids
            ]
            # A deliberately partial inventory can never decide what has disappeared.
            return DiscoveryResult(scope=scope, entries=entries, authoritative=False)

        inventory_language = await self._inventory_language()
        entries_by_id: dict[str, DiscoveryEntry] = {}
        language = inventory_language or scope.languages[0]
        page_number = 1
        total_pages: int | None = None
        while total_pages is None or page_number <= total_pages:
            payload = await self._request_json(
                "GET",
                endpoint_url(self.config.base_api_url, "tables"),
                params={
                    "lang": language,
                    "includeDiscontinued": "true",
                    "pageNumber": page_number,
                    "pageSize": self.config.page_size,
                },
            )
            tables = _required_list(payload, "tables")
            for table in tables:
                entry = self._discovery_entry(_required_mapping_value(table, "table"))
                entries_by_id.setdefault(entry.native_table_id, entry)

            page = payload.get("page") if isinstance(payload, Mapping) else None
            if isinstance(page, Mapping) and isinstance(page.get("totalPages"), int):
                total_pages = page["totalPages"]
                page_number += 1
            else:
                break

        return DiscoveryResult(
            scope=scope,
            entries=list(entries_by_id.values()),
            authoritative=inventory_language is not None,
        )

    async def languages_to_refresh(
        self,
        entry: DiscoveryEntry,
        stored: Mapping[str, LanguageState],
        requested: Sequence[str],
        *,
        force: bool,
    ) -> list[str]:
        requested_languages = normalize_languages(requested)
        available = set(entry.available_languages or requested_languages)
        candidates = [language for language in requested_languages if language in available]
        if force:
            return candidates
        marker = entry.marker
        to_refresh: list[str] = []
        for language in candidates:
            state = stored.get(language)
            if (
                state is None
                or state.last_harvested_at is None
                or state.failed
                or marker is None
                or state.comparison_marker != marker
            ):
                to_refresh.append(language)
        return to_refresh

    async def fetch_metadata(
        self, entry: DiscoveryEntry, languages: Sequence[str]
    ) -> list[MetadataFetchResult]:
        results: list[MetadataFetchResult] = []
        for language in normalize_languages(languages):
            table = await self._get_table(entry.native_table_id, language)
            dataset_payload = await self._request_json(
                "GET",
                endpoint_url(self.config.base_api_url, "metadata", entry.native_table_id),
                params={"lang": language, "defaultSelection": "false"},
            )
            dataset = JsonStatDataset.from_mapping(
                _required_mapping_value(dataset_payload, "dataset")
            )
            metadata = LanguageMetadata(
                language=language,
                catalog=self._catalog_metadata(table),
                dataset=dataset,
            )
            results.append(
                MetadataFetchResult(
                    provider_id=self.provider.id,
                    native_table_id=entry.native_table_id,
                    metadata=metadata,
                    comparison_marker=self._comparison_marker(table),
                )
            )
        return results

    async def fetch_data(
        self, native_table_id: str, selection: ExplicitSelection
    ) -> JsonStatDataset:
        payload = await self._request_json(
            "POST",
            endpoint_url(self.config.base_api_url, "data", native_table_id),
            params={"lang": selection.language, "outputFormat": "json-stat2"},
            json={
                "selection": [
                    {
                        "variableCode": dimension.dimension_code,
                        "valueCodes": dimension.category_codes,
                    }
                    for dimension in selection.dimensions
                ]
            },
        )
        return JsonStatDataset.from_mapping(_required_mapping_value(payload, "dataset"))

    async def _supported_languages(self) -> list[str]:
        if self.config.languages:
            return list(self.config.languages)
        languages = _required_list(await self._service_config(), "languages")
        return normalize_languages(
            language["id"]
            if isinstance(language, Mapping) and isinstance(language.get("id"), str)
            else str(language)
            for language in languages
        )

    async def _inventory_language(self) -> str | None:
        """The language whose catalogue listing covers the whole provider.

        Returns None when the provider does not say which language that is, which makes
        any enumeration non-authoritative rather than guessing and retiring real tables.
        """
        if self.config.default_language is not None:
            return self.config.default_language
        value = (await self._service_config()).get("defaultLanguage")
        if isinstance(value, str) and value.strip():
            return normalize_language(value)
        return None

    async def _service_config(self) -> Mapping[str, Any]:
        if self._service is None:
            payload = await self._request_json(
                "GET", endpoint_url(self.config.base_api_url, "config")
            )
            self._service = _required_mapping_value(payload, "config")
        return self._service

    async def _get_table(self, native_table_id: str, language: str) -> Mapping[str, Any]:
        payload = await self._request_json(
            "GET",
            endpoint_url(self.config.base_api_url, "table", native_table_id),
            params={"lang": language},
        )
        return _required_mapping_value(payload, "table")

    async def _request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        auth_kwargs = self.config.auth.request_kwargs(self.secrets)
        kwargs = _merge_request_kwargs(auth_kwargs, kwargs)
        response = await self.http.request(method, url, retry_safe=True, **kwargs)
        payload = response.json()
        if isinstance(payload, str):
            return json.loads(payload)
        return payload

    def _discovery_entry(self, table: Mapping[str, Any]) -> DiscoveryEntry:
        return DiscoveryEntry(
            native_table_id=_required_str(table, "id"),
            available_languages=_available_languages(table),
            marker=self._comparison_marker(table),
        )

    def _comparison_marker(self, table: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "updated": table.get("updated"),
            "firstPeriod": table.get("firstPeriod"),
            "lastPeriod": table.get("lastPeriod"),
            "discontinued": table.get("discontinued"),
        }

    def _catalog_metadata(self, table: Mapping[str, Any]) -> TableCatalogMetadata:
        return TableCatalogMetadata(
            label=_required_str(table, "label"),
            description=_optional_str(table, "description"),
            source=_optional_str(table, "source"),
            updated=_required_str(table, "updated"),
            first_period=_required_str(table, "firstPeriod"),
            last_period=_required_str(table, "lastPeriod"),
            variable_names=[str(value) for value in _required_list(table, "variableNames")],
            links=[_link(value) for value in _required_list(table, "links")],
            sort_code=_optional_str(table, "sortCode"),
            tags=(
                [str(value) for value in table["tags"]]
                if isinstance(table.get("tags"), list)
                else None
            ),
            category=cast(TableCategory | None, _optional_str(table, "category")),
            discontinued=(
                table.get("discontinued") if isinstance(table.get("discontinued"), bool) else None
            ),
            subject_code=_optional_str(table, "subjectCode"),
            time_unit=cast(TimeUnit | None, _optional_str(table, "timeUnit")),
            paths=_paths(table.get("paths")),
        )


def _available_languages(table: Mapping[str, Any]) -> list[str] | None:
    """Read the languages a table exists in from the languages its own links point at.

    PxAPI v2 does not publish a table in every language a provider serves, and asking for
    a language it was never published in is a 404, not an empty result. Every language it
    does exist in appears as the ``hreflang`` of one of its links, so that set is what a
    worker should confine itself to. None means the response said nothing, and the
    requested languages stand.
    """
    links = table.get("links")
    if not isinstance(links, list):
        return None
    languages: list[str] = []
    for link in links:
        if not isinstance(link, Mapping):
            continue
        value = link.get("hreflang")
        if isinstance(value, str) and value.strip():
            language = normalize_language(value)
            if language not in languages:
                languages.append(language)
    return languages or None


def _merge_request_kwargs(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    merged = dict(second)
    for key, value in first.items():
        if (
            key == "params"
            and isinstance(value, Mapping)
            and isinstance(merged.get("params"), Mapping)
        ):
            merged["params"] = {**value, **merged["params"]}
        elif (
            key == "headers"
            and isinstance(value, Mapping)
            and isinstance(merged.get("headers"), Mapping)
        ):
            merged["headers"] = {**value, **merged["headers"]}
        else:
            merged.setdefault(key, value)
    return merged


def _required_mapping_value(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _required_list(mapping: Any, key: str) -> list[Any]:
    if not isinstance(mapping, Mapping) or not isinstance(mapping.get(key), list):
        raise ValueError(f"{key} must be a list")
    return list(mapping[key])


def _required_str(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_str(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    value = value.strip()
    return value or None


def _link(value: Any) -> Link:
    mapping = _required_mapping_value(value, "link")
    return Link(
        rel=_required_str(mapping, "rel"),
        hreflang=_required_str(mapping, "hreflang"),
        href=_required_str(mapping, "href"),
    )


def _paths(value: Any) -> list[list[PathElement]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("paths must be a list")
    paths: list[list[PathElement]] = []
    for path in value:
        if not isinstance(path, list):
            raise ValueError("each path must be a list")
        paths.append([_path_element(element) for element in path])
    return paths


def _path_element(value: Any) -> PathElement:
    mapping = _required_mapping_value(value, "path element")
    return PathElement(
        id=_required_str(mapping, "id"),
        label=_required_str(mapping, "label"),
        sort_code=_optional_str(mapping, "sortCode"),
    )
