"""PxAPI v2 endpoint helpers."""

from __future__ import annotations

from urllib.parse import quote

_VALID_ENDPOINTS = {"config", "tables", "table", "metadata", "data", "codelist"}


def endpoint_url(base_api_url: str, endpoint: str, native_id: str | None = None) -> str:
    """Build a PxAPI v2 endpoint URL without exposing path rules to callers."""
    if endpoint not in _VALID_ENDPOINTS:
        raise ValueError(f"invalid PxAPI v2 endpoint: {endpoint}")
    base = base_api_url.rstrip("/")
    if endpoint == "config":
        return f"{base}/config"
    if endpoint == "tables":
        return f"{base}/tables"
    if native_id is None or not native_id.strip():
        raise ValueError(
            f"endpoint '{endpoint}' requires a native table or codelist id"
        )
    quoted_id = quote(native_id, safe="")
    if endpoint == "table":
        return f"{base}/tables/{quoted_id}"
    if endpoint == "metadata":
        return f"{base}/tables/{quoted_id}/metadata"
    if endpoint == "data":
        return f"{base}/tables/{quoted_id}/data"
    return f"{base}/codelists/{quoted_id}"
