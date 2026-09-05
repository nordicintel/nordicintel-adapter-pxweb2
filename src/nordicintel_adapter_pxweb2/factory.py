"""Factory entry point used by NordicIntel hosts."""

from __future__ import annotations

from collections.abc import Mapping

from nordicintel_core.models import (
    AsyncHttpClient,
    NordicIntelAdapter,
    ProviderDefinition,
)

from .adapter import PxWebAdapter


class PxWebAdapterFactory:
    """Create PxAPI v2 adapters for provider executions."""

    async def create(
        self,
        provider: ProviderDefinition,
        secrets: Mapping[str, str],
        http: AsyncHttpClient,
    ) -> NordicIntelAdapter:
        return PxWebAdapter(provider, secrets, http)
