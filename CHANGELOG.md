# Changelog

## Unreleased

- Register the factory in the `nordicintel.adapters` entry point group as `pxweb2`, so a
  harvest worker can resolve a Provider's `adapter_type` without importing a name the
  database supplied.
- Follow core's language-scoped contract: `supported_languages`, `should_refresh` and a
  single-result `fetch_metadata`. Discovery lists the catalogue of `scope.language`, which
  is what makes "this table can be fetched in this language" a fact about the response
  rather than a per-table inference. The earlier design listed in whichever language a job
  asked for first and reported per-table `available_languages` read out of link
  `hreflang`s; both were guesses standing in for a scope the request should have carried.
- Fetch the service description at most once per job, and resolve core from the sibling
  checkout so `uv sync`, `uv run pytest` and `uv run mypy` work without a manual install.
