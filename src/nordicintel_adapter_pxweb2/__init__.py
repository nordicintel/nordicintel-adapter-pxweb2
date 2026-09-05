"""PxAPI v2 adapter for NordicIntel."""

from .adapter import PxWebAdapter
from .factory import PxWebAdapterFactory

#: The object a host loads from the ``nordicintel.adapters`` entry point group. A factory
#: holds no per-job state, so one instance serves every execution in a process.
factory = PxWebAdapterFactory()

__all__ = ["PxWebAdapter", "PxWebAdapterFactory", "factory"]
