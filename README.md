# nordicintel-adapter-pxweb2

Harvesting adapter for the PxAPI v2 protocol.

The package implements the structural `nordicintel_core.models.NordicIntelAdapter`
protocol. Hosts inject a `ProviderDefinition`, resolved secrets, and the shared
`AsyncHttpClient`; the adapter performs no database access.

See also [the onboarding note](docs/onboarding/adapter-contract.md) for a source-backed
walkthrough of the host boundary and current adapter behavior.

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
    "page_size": 1000,
    "request_interval_seconds": 0.34
  }
}
```

| Key | Meaning |
|---|---|
| `base_api_url` | Required. The PxAPI v2 root. |
| `languages` | Override for providers without a usable `/config`. Otherwise the provider is asked. |
| `page_size` | Table listing page size. |
| `auth` | Optional `header_name`/`header_secret` or `query_param`/`query_secret`, resolved from the host's secrets. |

`request_interval_seconds` is read by the harvest worker rather than by this package: it
builds the HTTP client. It belongs in the same `config` object because an upstream quota
is a property of the provider. SCB publishes 30 calls per 10 seconds in `/config`.

## What PxAPI v2 forces on a harvester

**A catalogue is a different size in every language.** A table never published in English
is absent from the English listing entirely, and requesting it with `lang=en` returns 404
rather than an empty result. At SCB that is 5,253 tables in Swedish and 3,315 in English.

This is why a run is scoped to one language. Discovery lists `lang={scope.language}`, so
every table it returns is one that can actually be fetched in that language — a fact about
the response rather than something the host has to infer per table. Two languages are two
runs over two catalogues.

What a provider publishes is discovered, never configured. There is no list of tables to
maintain anywhere: the catalogue listing is the only statement of what exists, and
`should_refresh` decides from the publisher's own marker what has changed since last time.

**Discontinued tables stay in the inventory.** Discovery passes `includeDiscontinued=true`.
A table the publisher has finished updating is still published, and `discontinued` is
carried through to core as the publisher's own attribute — never inferred, never
overwritten.

## Development

Core resolves from the sibling checkout via `[tool.uv.sources]`, so the usual commands
work with no manual install:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy
```
