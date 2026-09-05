from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from nordicintel_core.models import (
    DimensionSelection,
    DiscoveryEntry,
    DiscoveryScope,
    ExplicitSelection,
    LanguageState,
    NordicIntelAdapter,
    ProviderDefinition,
)

from nordicintel_adapter_pxweb2 import PxWebAdapter, PxWebAdapterFactory


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class FakeHttp:
    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = routes
        self.calls: list[dict[str, Any]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        retry_safe: bool = False,
        **kwargs: Any,
    ) -> FakeResponse:
        self.calls.append(
            {"method": method, "url": url, "retry_safe": retry_safe, **kwargs}
        )
        return FakeResponse(self.routes[(method, url)])


def provider(config: dict[str, Any] | None = None) -> ProviderDefinition:
    return ProviderDefinition(
        id="scb",
        label="Statistics Sweden",
        adapter_type="pxweb2",
        config={
            "base_api_url": "https://example.test/api/v2/",
            "languages": ["sv", "en"],
            **(config or {}),
        },
    )


def table_payload(
    table_id: str = "TAB1", languages: tuple[str, ...] = ("sv", "en")
) -> dict[str, Any]:
    """One PxAPI v2 table, published in the given languages and no others."""
    return {
        "id": table_id,
        "label": "Population",
        "updated": "2025-03-04",
        "firstPeriod": "2024",
        "lastPeriod": "2025",
        "variableNames": ["region"],
        "links": [
            {
                "rel": "self" if index == 0 else "alternate",
                "hreflang": language,
                "href": f"https://example.test/{table_id}?lang={language}",
            }
            for index, language in enumerate(languages)
        ],
        "description": "Population table",
        "source": "SCB",
        "sortCode": "001",
        "tags": ["population"],
        "category": "public",
        "discontinued": False,
        "subjectCode": "BE",
        "timeUnit": "Annual",
        "paths": [[{"id": "BE", "label": "Population", "sortCode": "01"}]],
    }


def dataset_payload(values: list[Any] | None = None) -> dict[str, Any]:
    return {
        "version": "2.0",
        "class": "dataset",
        "label": "Population by region",
        "id": ["region"],
        "size": [2],
        "dimension": {
            "region": {
                "label": "Region",
                "category": {
                    "index": {"SE": 0, "18": 1},
                    "label": {"SE": "Sweden", "18": "Örebro"},
                },
            }
        },
        "value": [] if values is None else values,
    }


@pytest.mark.asyncio
async def test_adapter_matches_protocol_and_resolves_configured_languages() -> None:
    adapter = PxWebAdapter(
        provider({"languages": ["SV", " en ", "sv"]}), {}, FakeHttp({})
    )

    assert isinstance(adapter, NordicIntelAdapter)
    assert await adapter.resolve_languages(None) == ["sv", "en"]
    assert await adapter.resolve_languages(["EN", "sv", "en"]) == ["en", "sv"]


@pytest.mark.asyncio
async def test_factory_returns_protocol_compatible_adapter() -> None:
    adapter = await PxWebAdapterFactory().create(provider(), {}, FakeHttp({}))

    assert isinstance(adapter, NordicIntelAdapter)


@pytest.mark.asyncio
async def test_resolve_languages_can_fall_back_to_config_endpoint() -> None:
    http = FakeHttp(
        {
            ("GET", "https://example.test/api/v2/config"): {
                "languages": [
                    {"id": "SV", "label": "Swedish"},
                    {"id": "en", "label": "English"},
                ]
            }
        }
    )
    adapter = PxWebAdapter(provider({"languages": []}), {}, http)

    assert await adapter.resolve_languages(None) == ["sv", "en"]


@pytest.mark.asyncio
async def test_unsupported_language_is_rejected() -> None:
    adapter = PxWebAdapter(provider(), {}, FakeHttp({}))

    with pytest.raises(ValueError, match="unsupported language"):
        await adapter.resolve_languages(["da"])


def listing(*tables: dict[str, Any], language: str = "sv") -> dict[str, Any]:
    return {
        "language": language,
        "tables": list(tables),
        "page": {
            "pageNumber": 1,
            "pageSize": 1000,
            "totalElements": len(tables),
            "totalPages": 1,
        },
    }


@pytest.mark.asyncio
async def test_discover_pages_tables_and_marks_full_inventory_authoritative() -> None:
    http = FakeHttp(
        {
            ("GET", "https://example.test/api/v2/tables"): listing(
                table_payload("TAB1"), table_payload("TAB2", ("sv",))
            )
        }
    )
    adapter = PxWebAdapter(provider({"default_language": "sv"}), {}, http)

    result = await adapter.discover(DiscoveryScope(languages=["sv", "en"]))

    assert result.authoritative is True
    assert [entry.native_table_id for entry in result.entries] == ["TAB1", "TAB2"]
    # A table reports the languages it exists in, not the ones the job asked for.
    assert result.entries[0].available_languages == ["sv", "en"]
    assert result.entries[1].available_languages == ["sv"]
    # Discontinued tables stay in the inventory, or absence-based retirement would
    # delete every table the publisher merely stopped updating.
    assert http.calls[0]["params"]["includeDiscontinued"] == "true"


@pytest.mark.asyncio
async def test_the_inventory_is_listed_in_the_default_language_not_the_requested_one() -> None:
    http = FakeHttp(
        {("GET", "https://example.test/api/v2/tables"): listing(table_payload("TAB1"))}
    )
    adapter = PxWebAdapter(provider({"default_language": "sv"}), {}, http)

    result = await adapter.discover(DiscoveryScope(languages=["en"]))

    # An English listing omits every Swedish-only table. Enumerating in it and calling
    # the result authoritative would retire all of them.
    assert http.calls[0]["params"]["lang"] == "sv"
    assert result.authoritative is True


@pytest.mark.asyncio
async def test_an_inventory_without_a_known_default_language_is_not_authoritative() -> None:
    http = FakeHttp(
        {
            ("GET", "https://example.test/api/v2/config"): {
                "languages": [{"id": "sv"}, {"id": "en"}]
            },
            ("GET", "https://example.test/api/v2/tables"): listing(table_payload("TAB1")),
        }
    )
    adapter = PxWebAdapter(provider(), {}, http)

    result = await adapter.discover(DiscoveryScope(languages=["sv", "en"]))

    assert result.entries[0].native_table_id == "TAB1"
    assert result.authoritative is False


@pytest.mark.asyncio
async def test_a_configured_table_allowlist_is_never_authoritative() -> None:
    http = FakeHttp(
        {
            ("GET", "https://example.test/api/v2/tables/TAB1"): table_payload("TAB1"),
            ("GET", "https://example.test/api/v2/tables/TAB2"): table_payload("TAB2"),
        }
    )
    adapter = PxWebAdapter(
        provider({"default_language": "sv", "table_ids": ["TAB1", "TAB2"]}), {}, http
    )

    result = await adapter.discover(DiscoveryScope(languages=["sv"]))

    assert [entry.native_table_id for entry in result.entries] == ["TAB1", "TAB2"]
    assert result.authoritative is False
    # A bounded run must not enumerate the catalogue it deliberately skipped.
    assert all("/tables/TAB" in call["url"] for call in http.calls)


@pytest.mark.asyncio
async def test_single_table_discovery_is_not_authoritative() -> None:
    http = FakeHttp(
        {("GET", "https://example.test/api/v2/tables/TAB1"): table_payload("TAB1")}
    )
    adapter = PxWebAdapter(provider(), {}, http)

    result = await adapter.discover(
        DiscoveryScope(table_id="scb-tab1", native_table_id="TAB1", languages=["sv"])
    )

    assert result.authoritative is False
    assert [entry.native_table_id for entry in result.entries] == ["TAB1"]


@pytest.mark.asyncio
async def test_languages_to_refresh_uses_force_failures_missing_state_and_marker() -> (
    None
):
    adapter = PxWebAdapter(provider(), {}, FakeHttp({}))
    entry = await _entry(adapter)
    harvested_at = datetime(2026, 9, 5, tzinfo=UTC)

    assert await adapter.languages_to_refresh(entry, {}, ["sv", "en"], force=True) == [
        "sv",
        "en",
    ]
    assert await adapter.languages_to_refresh(entry, {}, ["sv", "en"], force=False) == [
        "sv",
        "en",
    ]
    assert (
        await adapter.languages_to_refresh(
            entry,
            {
                "sv": LanguageState(
                    language="sv",
                    comparison_marker=entry.marker,
                    last_harvested_at=harvested_at,
                ),
                "en": LanguageState(
                    language="en",
                    comparison_marker=entry.marker,
                    last_harvested_at=harvested_at,
                ),
            },
            ["sv", "en"],
            force=False,
        )
        == []
    )
    assert await adapter.languages_to_refresh(
        entry,
        {
            "sv": LanguageState(
                language="sv", comparison_marker=entry.marker, failed=True
            )
        },
        ["sv"],
        force=False,
    ) == ["sv"]


@pytest.mark.asyncio
async def test_fetch_metadata_returns_core_valid_metadata_only_result() -> None:
    http = FakeHttp(
        {
            ("GET", "https://example.test/api/v2/tables/TAB1"): table_payload("TAB1"),
            (
                "GET",
                "https://example.test/api/v2/tables/TAB1/metadata",
            ): dataset_payload(),
        }
    )
    adapter = PxWebAdapter(provider(), {}, http)

    results = await adapter.fetch_metadata(await _entry(adapter), ["sv"])

    assert len(results) == 1
    result = results[0]
    assert result.provider_id == "scb"
    assert result.native_table_id == "TAB1"
    assert result.metadata.language == "sv"
    assert result.metadata.catalog.label == "Population"
    assert result.metadata.dataset.value == []
    assert result.metadata.dataset.status is None
    assert result.comparison_marker == {
        "updated": "2025-03-04",
        "firstPeriod": "2024",
        "lastPeriod": "2025",
        "discontinued": False,
    }


@pytest.mark.asyncio
async def test_fetch_data_posts_explicit_selection_and_preserves_live_values() -> None:
    http = FakeHttp(
        {
            ("POST", "https://example.test/api/v2/tables/TAB1/data"): dataset_payload(
                [1.5, None]
            )
        }
    )
    adapter = PxWebAdapter(provider(), {}, http)

    dataset = await adapter.fetch_data(
        "TAB1",
        ExplicitSelection(
            table_id="scb-tab1",
            language="SV",
            dimensions=[
                DimensionSelection(dimension_code="region", category_codes=["SE", "18"])
            ],
        ),
    )

    assert dataset.value == [1.5, None]
    assert http.calls[0]["method"] == "POST"
    assert http.calls[0]["params"] == {"lang": "sv", "outputFormat": "json-stat2"}
    assert http.calls[0]["json"] == {
        "selection": [{"variableCode": "region", "valueCodes": ["SE", "18"]}]
    }


async def _entry(adapter: PxWebAdapter):
    table = table_payload("TAB1")
    return DiscoveryEntry(
        native_table_id="TAB1",
        available_languages=["sv", "en"],
        marker={
            "updated": table["updated"],
            "firstPeriod": table["firstPeriod"],
            "lastPeriod": table["lastPeriod"],
            "discontinued": table["discontinued"],
        },
    )
