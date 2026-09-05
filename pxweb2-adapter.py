"""Compatibility shim for the importable adapter package.

Use ``nordicintel_adapter_pxweb2.PxWebAdapter`` from application code.
"""

from nordicintel_adapter_pxweb2 import PxWebAdapter, PxWebAdapterFactory

__all__ = ["PxWebAdapter", "PxWebAdapterFactory"]
