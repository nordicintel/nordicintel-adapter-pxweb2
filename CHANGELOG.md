# Changelog

## Unreleased

- Register the factory in the `nordicintel.adapters` entry point group as `pxweb2`, so a
  harvest worker can resolve a Provider's `adapter_type` without importing a name the
  database supplied.
- Enumerate the catalogue in the provider's default language instead of the job's first
  requested language, and report the result as authoritative only when that language is
  known. A language-specific listing omits every table not published in it, so an
  English-scoped job at SCB previously described 3,315 of 5,253 tables as the complete
  provider inventory, which would have retired the other 1,878.
- Report each table's `available_languages` from the `hreflang` of its own links instead
  of echoing the requested languages. PxAPI v2 answers a request for a language a table
  was never published in with a 404, so 1,878 SCB tables would otherwise have failed in
  English on every run and stayed permanently `unavailable`.
- Add the optional `table_ids` provider configuration for bounded runs against a large
  catalogue. A restricted inventory is never authoritative.
- Fetch the service description at most once per job, and resolve core from the sibling
  checkout so `uv sync`, `uv run pytest` and `uv run mypy` work without a manual install.
