"""Capability-safe contract for domain applications built on sudofx."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import Context, Proposal
from .providers import Intelligence


class ApplicationProposalError(ValueError):
    """Application policy refused a proposal before kernel submission."""


class Application(Protocol):
    """Domain policy surface with no storage or kernel mutation capability."""

    application_id: str
    version: str

    def project_context(self, context: Context) -> Context: ...

    def validate_proposal(self, proposal: Proposal) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class ApplicationIntelligence:
    """Apply domain projection and policy while preserving the normal provider boundary."""

    application: Application
    intelligence: Intelligence

    def propose(self, context: Context) -> Proposal:
        proposal = self.intelligence.propose(self.application.project_context(context))
        reasons = self.application.validate_proposal(proposal)
        if reasons:
            raise ApplicationProposalError("; ".join(reasons))
        return proposal
