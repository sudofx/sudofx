"""
PUBLIC SUDOFX SURFACE
=====================

Only stable concepts needed to embed governed work are exported here. Internal
storage, hashing, rendering, and policy helpers remain in their owning modules
so callers do not mistake an implementation helper for authority.

The matrix extension is intentionally exported here because applications may
share its deterministic experiment grammar. Matrix definitions grant no
database or provider authority; applications still persist results through
normal governed application actions.
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
from .generation import (
    GenerationProvider,
    GenerationRequest,
    GenerationResponse,
    GeminiGenerationProvider,
)
from .kernel import Kernel, RunResult
from .matrix import (
    CONTINUITY_MATRIX_V1,
    MatrixAxis,
    MatrixCoordinate,
    MatrixDefinition,
    MatrixValue,
    continuity_matrix,
)
from .runtime import (
    GovernanceRejectionError,
    InvocationBarrierError,
    InvocationLifecycle,
    InvocationResult,
    Runtime,
)
from .storage import ApplicationAccessError, ApplicationAccessState
from .models import Context, Operation, Proposal, Receipt, SubmissionProvenance
from .observability import build_application_observability
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
    "ApplicationAccessError",
    "ApplicationAccessState",
    "CONTINUITY_MATRIX_V1",
    "EffectRequest",
    "Context",
    "CommandIntelligence",
    "FakeIntelligence",
    "FakeWorkIntelligence",
    "GeminiGenerationProvider",
    "GenerationResponse",
    "GenerationRequest",
    "GenerationProvider",
    "Intelligence",
    "GovernanceRejectionError",
    "InvocationBarrierError",
    "InvocationLifecycle",
    "InvocationResult",
    "Kernel",
    "MatrixAxis",
    "MatrixCoordinate",
    "MatrixDefinition",
    "MatrixValue",
    "Operation",
    "Proposal",
    "ProviderError",
    "ProviderQuotaError",
    "ProviderTemporaryError",
    "Receipt",
    "RunResult",
    "SubmissionProvenance",
    "Runtime",
    "build_application_observability",
    "continuity_matrix",
]

__version__ = "0.1.0"
