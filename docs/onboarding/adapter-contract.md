# PxWeb2 adapter contract

## Purpose

This note explains what `nordicintel-adapter-pxweb2` currently implements, how it is meant to plug into the NordicIntel host stack, what configuration and behavior contracts it relies on, and where the main gaps still are.

## Evidence reviewed

### Adapter repo files

- `README.md`
- `pyproject.toml`
- `providers.json`
- `src/nordicintel_adapter_pxweb2/__init__.py`
- `src/nordicintel_adapter_pxweb2/config.py`
- `src/nordicintel_adapter_pxweb2/endpoints.py`
- `src/nordicintel_adapter_pxweb2/adapter.py`
- `src/nordicintel_adapter_pxweb2/factory.py`
- `tests/test_adapter.py`

### Cross-repo seam files inspected

These are not part of this repository, but they define the host-side contract this adapter is written against.

- In `nordicintel-core`: `src/nordicintel_core/models/adapters.py`, `README.md`
- In `nordicintel-harvest`: `README.md`, `src/nordicintel_harvest/registry.py`, `src/nordicintel_harvest/worker.py`

## What the adapter is, as a fact

- The package is a harvesting adapter for PxAPI v2 providers, not a standalone service. `README.md` states that hosts inject a `ProviderDefinition`, resolved secrets, and a shared `AsyncHttpClient`, and that the adapter performs no database access.
- `pyproject.toml` declares a `nordicintel.adapters` entry point named `pxweb2` that exports `nordicintel_adapter_pxweb2:factory`.
- `src/nordicintel_adapter_pxweb2/__init__.py` exposes a module-level `factory = PxWebAdapterFactory()` object, which matches that entry point contract.
- The implementation depends on `nordicintel-core[http]==0.2.0` according to `pyproject.toml`.

## How it plugs into core and harvest

### Facts

- The host-side adapter protocol lives in `nordicintel-core/src/nordicintel_core/models/adapters.py`. The required runtime shape is:
  - `AdapterFactory.create(provider, secrets, http) -> NordicIntelAdapter`
  - `NordicIntelAdapter.supported_languages()`
  - `NordicIntelAdapter.discover(scope)`
  - `NordicIntelAdapter.should_refresh(entry, stored, force=...)`
  - `NordicIntelAdapter.fetch_metadata(entry, language)`
  - `NordicIntelAdapter.fetch_data(native_table_id, selection)`
- `src/nordicintel_adapter_pxweb2/factory.py` implements that factory seam by returning `PxWebAdapter(provider, secrets, http)`.
- `nordicintel-harvest/src/nordicintel_harvest/registry.py` resolves installed adapter factories only from the `nordicintel.adapters` entry-point group; it does not import arbitrary modules named by database values.
- `nordicintel-harvest/src/nordicintel_harvest/worker.py` shows the runtime wiring: the worker loads the provider, resolves secrets, creates an HTTP client, wraps it in the shared `HttpClient`, and calls the adapter factory.
- `nordicintel-harvest/src/nordicintel_harvest/worker.py` also reads `provider.config.request_interval_seconds` on the host side when constructing the HTTP client. That means rate-limiting belongs to provider configuration, but the enforcement point is harvest infrastructure, not this package.

### Inference

- This package is intentionally “thin at the seam”: it owns PxAPI v2 translation and leaves scheduling, retries, DB writes, queueing, and ownership rules to `nordicintel-harvest` and `nordicintel-core`.
- The split is deliberate rather than accidental, because the README and code both avoid any DB or process lifecycle logic.

## Configuration contract expected by the adapter

### Facts from `README.md` and `src/nordicintel_adapter_pxweb2/config.py`

- `provider.config.base_api_url` is required.
- `provider.config.base_url` is accepted as a fallback alias in `PxWebConfig.from_provider(...)`.
- `provider.config.languages` is optional. If present, it is normalized to lowercase, whitespace-trimmed, deduplicated, and order-preserving.
- If `languages` is absent or empty, the adapter calls `/config` and derives languages from the upstream response.
- `provider.config.page_size` defaults to `1000` and must be a positive integer.
- `provider.config.auth` must be an object if supplied.
- `auth` supports two optional patterns:
  - `header_name` + `header_secret`
  - `query_param` + `query_secret`
- Secret names are resolved against the injected `secrets` mapping. Missing required secrets raise `ConfigurationError`.
- `README.md` documents `request_interval_seconds` in the same provider config object, but that key is not parsed by `PxWebConfig`; it is consumed by the harvest worker instead.

### Supplemental example

- `providers.json` contains provider-like records with fields such as `base_api_url`, `languages`, rate limits, and extension metadata for providers including `scb` and `ssb`.

### Inference / caution

- `providers.json` uses `api_type` rather than the runtime `adapter_type` name used elsewhere. Based on the inspected code, that file does not appear to be read directly by the package, so it is best treated as reference data or planning input unless another repo explicitly transforms it.

## Behavior the protocol and implementation force

### Language scoping

#### Facts

- `README.md` states that PxAPI v2 catalogues are language-specific and can differ in size.
- `nordicintel-core/src/nordicintel_core/models/adapters.py` says every method except `supported_languages()` and `fetch_data()` operates in the single language the job named.
- `src/nordicintel_adapter_pxweb2/adapter.py` implements discovery using `scope.language` for listing and for single-table lookup.
- `tests/test_adapter.py` verifies that discovery listing passes `lang=<scope language>` and that `supported_languages()` normalizes configured or upstream language IDs.

#### Inference

- The adapter is designed for “one provider, one language inventory pass” rather than mixed-language discovery in a single run.

### Discovery behavior

#### Facts

- `src/nordicintel_adapter_pxweb2/adapter.py` calls `/tables` for provider-wide discovery and `/tables/{id}` for single-table discovery.
- Provider-wide discovery includes `includeDiscontinued=true`, `pageNumber`, and `pageSize` query parameters.
- The adapter deduplicates discovered entries by `native_table_id` before returning them.
- Discovery markers are composed from `updated`, `firstPeriod`, `lastPeriod`, and `discontinued`.
- `tests/test_adapter.py` verifies both provider-wide and single-table discovery behavior.

### Refresh decision

#### Facts

- `src/nordicintel_adapter_pxweb2/adapter.py` returns `True` from `should_refresh(...)` when:
  - `force=True`
  - there is no stored language state
  - `stored.last_harvested_at` is missing
  - the stored language previously failed
  - the stored comparison marker differs from the newly discovered one
- `tests/test_adapter.py` covers all of those cases.

### Metadata fetch behavior

#### Facts

- `src/nordicintel_adapter_pxweb2/adapter.py` fetches:
  - `/tables/{id}` for catalog-level table information
  - `/tables/{id}/metadata` with `defaultSelection=false` for JSON-stat metadata
- It returns a single `MetadataFetchResult` containing:
  - `provider_id`
  - `native_table_id`
  - `LanguageMetadata(language, catalog, dataset)`
  - `comparison_marker`
- `tests/test_adapter.py` verifies that language normalization happens, the catalog fields are mapped, the dataset payload is accepted, and the comparison marker matches the table-level metadata.

### Data fetch behavior

#### Facts

- `src/nordicintel_adapter_pxweb2/adapter.py` posts to `/tables/{id}/data`.
- It sends `lang=<selection.language>` and `outputFormat=json-stat2`.
- It converts `ExplicitSelection.dimensions` into the upstream JSON shape:
  - `selection[].variableCode`
  - `selection[].valueCodes`
- `tests/test_adapter.py` verifies that `None` values in the returned dataset are preserved.

### Endpoint rules encapsulated here

- `src/nordicintel_adapter_pxweb2/endpoints.py` centralizes endpoint construction for `config`, `tables`, `table`, `metadata`, `data`, and `codelist`.
- Native IDs are URL-quoted before being embedded in paths.

## Key source files and what they own

| File | Role |
|---|---|
| `src/nordicintel_adapter_pxweb2/config.py` | Validates provider configuration, language normalization, and optional auth setup. |
| `src/nordicintel_adapter_pxweb2/endpoints.py` | Encapsulates PxAPI v2 path construction and ID quoting rules. |
| `src/nordicintel_adapter_pxweb2/adapter.py` | Main translation layer from PxAPI v2 payloads into NordicIntel core contracts. |
| `src/nordicintel_adapter_pxweb2/factory.py` | Host-facing factory implementation for entry-point loading. |
| `src/nordicintel_adapter_pxweb2/__init__.py` | Exports `PxWebAdapter`, `PxWebAdapterFactory`, and the module-level `factory`. |
| `tests/test_adapter.py` | Contract-oriented unit tests using fake HTTP responses. |
| `README.md` | Best current prose explanation of how the package is intended to run. |

## What is covered by tests today

### Facts

`tests/test_adapter.py` covers:

- runtime compatibility with the structural `NordicIntelAdapter` protocol
- factory compatibility
- configured language normalization
- `/config` language fallback and caching
- provider-wide discovery semantics
- single-table lookup
- `should_refresh(...)` decision logic
- metadata fetch mapping
- explicit-selection data fetch mapping

### Inference

The current test suite is strongest on protocol shape and happy-path mapping, and lighter on failure-path behavior.

## Gaps, caveats, and open questions

### Facts

- No `TODO` or `FIXME` markers were found in the adapter `src/` tree during this review.
- `src/nordicintel_adapter_pxweb2/endpoints.py` supports a `codelist` endpoint, but the inspected adapter code in `src/nordicintel_adapter_pxweb2/adapter.py` does not currently call it.
- The package includes a reference `providers.json`, but no inspected source file in this repo uses it directly.

### Inferences

These are reasonable conclusions from the inspected files, but they are still interpretations rather than explicit guarantees:

- There is no evidence yet of live integration tests against a real PxAPI v2 provider; the inspected tests all use in-process fake HTTP responses.
- The test suite does not appear to cover invalid auth configurations, missing secrets, malformed upstream payloads, or multi-page discovery edge cases.
- Because `request_interval_seconds` is enforced in harvest, adapter behavior under shared multi-process upstream quotas is controlled more by host deployment and worker configuration than by this package alone.
- `providers.json` may be a planning or bootstrap input, but that is not established by the inspected code here.

## Bottom line

As of this review, `nordicintel-adapter-pxweb2` is an implemented adapter package with a clear and fairly disciplined seam:

- it registers itself as `pxweb2`
- it expects injected provider definition, secrets, and shared HTTP transport
- it translates PxAPI v2 catalog, metadata, and data responses into NordicIntel core models
- it assumes harvest/core own the queue, timing, persistence, and process behavior

The main remaining uncertainties are around production hardening rather than missing baseline implementation: real-provider integration coverage, failure-path coverage, and the status of auxiliary reference files such as `providers.json`.
