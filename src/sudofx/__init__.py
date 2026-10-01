"""
PUBLIC SUDOFX SURFACE
=====================

Only the stable concepts needed to embed the governed-work kernel are exported
here. Internal storage, hashing, rendering, and policy helpers remain reachable
from their owning modules but are intentionally absent from the convenience API.

Keeping this surface small prevents callers from mistaking an implementation
helper for a supported authority boundary. In particular, external code should
submit Proposals through Kernel rather than writing SQLite rows, applying replay
operations, or asking a provider to mutate state directly.

The package version describes the implementation release, not the durable
record schema. Replayed history is protected by explicit event structure and
governance semantics rather than an implicit dependency on this string.
"""

from .applications import (
    ApplicationAction,
    ApplicationContext,
    ApplicationDecision,
    ApplicationDefinition,
    ApplicationHost,
    ApplicationIntent,
    ApplicationPermissions,
    ApplicationRegistry,
    EffectRequest,
)
from .kernel import Kernel, RunResult
from .runtime import InvocationResult, Runtime
from .models import Context, Operation, Proposal, Receipt, SubmissionProvenance
from .providers import (
    CommandIntelligence,
    FakeIntelligence,
    FakeWorkIntelligence,
    Intelligence,
    ProviderError,
    ProviderQuotaError,
    ProviderTemporaryError,
)

__all__ = [
    "ApplicationAction",
    "ApplicationContext",
    "ApplicationDecision",
    "ApplicationDefinition",
    "ApplicationHost",
    "ApplicationIntent",
    "ApplicationPermissions",
    "ApplicationRegistry",
    "EffectRequest",
    "Context",
    "CommandIntelligence",
    "FakeIntelligence",
    "FakeWorkIntelligence",
    "Intelligence",
    "Kernel",
    "Operation",
    "Proposal",
    "ProviderError",
    "ProviderQuotaError",
    "ProviderTemporaryError",
    "Receipt",
    "RunResult",
]

__version__ = "0.1.0"
