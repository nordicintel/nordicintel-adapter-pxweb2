# nordicintel-adapter-pxweb2

Harvesting adapter for the PxAPI v2 protocol.

The package implements the structural `nordicintel_core.models.NordicIntelAdapter`
protocol. Hosts inject a `ProviderDefinition`, resolved secrets, and the shared
`AsyncHttpClient`; the adapter performs no database access.

## Installing it in a host

The factory registers itself under the name a Provider row carries as its `adapter_type`:

```toml
[project.entry-points."nordicintel.adapters"]
pxweb2 = "nordicintel_adapter_pxweb2:factory"
```

A harvest worker resolves that name and nothing else, so a Provider whose `adapter_type`
is `pxweb2` is served by this package once it is installed alongside the worker.

## Provider configuration

```json
{
  "id": "scb",
  "adapter_type": "pxweb2",
  "config": {
    "base_api_url": "https://statistikdatabasen.scb.se/api/v2",
    "languages": ["sv", "en"],
    "default_language": "sv",
    "page_size": 1000,
    "request_interval_seconds": 0.34,
    "table_ids": ["TAB4707"]
  }
}
```

| Key | Meaning |
|---|---|
| `base_api_url` | Required. The PxAPI v2 root. |
| `languages` | Languages this provider serves. Read from `/config` when omitted. |
| `default_language` | The language whose catalogue is complete. Read from `/config` when omitted. |
| `page_size` | Table listing page size. |
| `table_ids` | Optional allowlist. Harvest only these tables; the inventory is then never authoritative. |
| `auth` | Optional `header_name`/`header_secret` or `query_param`/`query_secret`, resolved from the host's secrets. |

`request_interval_seconds` is read by the harvest worker rather than by this package: it
builds the HTTP client. It belongs in the same `config` object because an upstream quota
is a property of the provider. SCB publishes 30 calls per 10 seconds in `/config`.

## Two things PxAPI v2 forces on a harvester

**A catalogue is a different size in every language.** A table that was never published in
English is absent from the English listing entirely, and requesting it with `lang=en`
returns 404 rather than an empty result. Two consequences are load-bearing:

- The inventory is enumerated in the provider's **default** language, never in whichever
  language a job happened to request. Listing in English at SCB returns 3,315 of 5,253
  tables, and calling that authoritative would retire the other 1,878.
- Each entry reports `available_languages`, read from the `hreflang` of its own links, so
  a worker never asks for a language a table does not have.

If the default language cannot be determined, the enumeration is reported as
non-authoritative rather than guessed at.

**Discontinued tables stay in the inventory.** Discovery passes
`includeDiscontinued=true`: a table the publisher stopped updating still exists, and
absence-based retirement is about tables that are gone, not tables that are finished.

## Development

Core resolves from the sibling checkout via `[tool.uv.sources]`, so the usual commands
work with no manual install:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy
```
