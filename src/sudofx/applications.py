"""
SUDOFX APPLICATION CONTRACT
===========================

Applications add domain meaning above the kernel without becoming a second
authority. This module defines the smallest application-facing boundary needed
to register deterministic domain transitions while keeping SQLite, governance,
and replay owned by sudofx.

An application never receives a Record or database connection through this
contract. It declares identity, version, deterministic actions, and requested
external-effect capabilities. ApplicationHost turns an intent into one generic
apply_application operation; Kernel governance independently recomputes the
declared transition before the event may be accepted.

Accepted events store the verified resulting JSON state. Replay therefore does
not need installed application code and historical generic record integrity does
not depend on a plugin loader or a specific application still being present.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .kernel import Kernel
from .models import JsonValue, Operation, Proposal, Receipt, SubmissionProvenance


APPLICATION_PREFIX = "app:"


def application_key(application_id: str) -> str:
    """Return the reserved durable state key for one application."""
    return f"{APPLICATION_PREFIX}{application_id}"


@dataclass(frozen=True)
class ApplicationDecision:
    """Return deterministic domain permission plus the state that would follow."""

    accepted: bool
    next_state: JsonValue = None
    reasons: tuple[str, ...] = ()


ApplicationEvaluator = Callable[[JsonValue, JsonValue], ApplicationDecision]


@dataclass(frozen=True)
class ApplicationAction:
    """Bind one stable domain action name to deterministic evaluation."""

    name: str
    evaluate: ApplicationEvaluator


@dataclass(frozen=True)
class ApplicationDefinition:
    """Describe one installed application without granting it authority."""

    application_id: str
    version: str
    actions: tuple[ApplicationAction, ...]
    effect_capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.application_id.strip():
            raise ValueError("application_id must not be empty")
        if ":" in self.application_id:
            raise ValueError("application_id must not contain ':'")
        if not self.version.strip():
            raise ValueError("application version must not be empty")
        names = [action.name for action in self.actions]
        if not names or any(not name.strip() for name in names):
            raise ValueError("application must define at least one named action")
        if len(names) != len(set(names)):
            raise ValueError("application action names must be unique")
        if any(not capability.strip() for capability in self.effect_capabilities):
            raise ValueError("effect capability names must not be empty")

    def action(self, name: str) -> ApplicationAction | None:
        """Resolve one registered action without inventing fallback behavior."""
        return next((action for action in self.actions if action.name == name), None)


class ApplicationRegistry:
    """Hold the currently installed application policy set in process memory."""

    def __init__(self, definitions: tuple[ApplicationDefinition, ...] = ()) -> None:
        self._definitions: dict[str, ApplicationDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: ApplicationDefinition) -> None:
        if definition.application_id in self._definitions:
            raise ValueError(f"application already registered: {definition.application_id}")
        self._definitions[definition.application_id] = definition

    def get(self, application_id: str) -> ApplicationDefinition | None:
        return self._definitions.get(application_id)


@dataclass(frozen=True)
class ApplicationContext:
    """Bound one application to its durable state and global record revision."""

    application_id: str
    application_version: str
    revision: int
    state: JsonValue


@dataclass(frozen=True)
class ApplicationIntent:
    """Carry one untrusted domain-facing request before kernel governance."""

    proposal_id: str
    based_on_revision: int
    action: str
    payload: JsonValue = None
    rationale: str = ""


@dataclass(frozen=True)
class EffectRequest:
    """Describe an application-requested external effect without executing it."""

    application_id: str
    application_version: str
    capability: str
    payload: JsonValue


class ApplicationHost:
    """Translate application intent into the generic governed application action."""

    def __init__(
        self,
        kernel: Kernel,
        registry: ApplicationRegistry,
        application_id: str,
    ) -> None:
        definition = registry.get(application_id)
        if definition is None:
            raise ValueError(f"application is not registered: {application_id}")
        self.kernel = kernel
        self.registry = registry
        self.application_id = application_id

    @property
    def definition(self) -> ApplicationDefinition:
        definition = self.registry.get(self.application_id)
        if definition is None:
            raise ValueError(f"application is not registered: {self.application_id}")
        return definition

    def context(self) -> ApplicationContext:
        """Return only this application's durable domain state."""
        context = self.kernel.context()
        envelope = context.state.get(application_key(self.application_id))
        app_state: JsonValue = None
        if isinstance(envelope, dict):
            app_state = envelope.get("state")
        return ApplicationContext(
            application_id=self.application_id,
            application_version=self.definition.version,
            revision=context.revision,
            state=app_state,
        )

    def submit(
        self,
        intent: ApplicationIntent,
        *,
        provenance: SubmissionProvenance | None = None,
    ) -> Receipt:
        """Submit one application intent through ordinary Kernel governance."""
        definition = self.definition
        current = self.context().state
        action = definition.action(intent.action)
        decision = (
            action.evaluate(current, intent.payload)
            if action is not None
            else ApplicationDecision(
                False,
                reasons=(f"unknown application action: {intent.action}",),
            )
        )
        operation = Operation(
            "apply_application",
            self.application_id,
            {
                "application_id": self.application_id,
                "application_version": definition.version,
                "action": intent.action,
                "input": intent.payload,
                "next_state": decision.next_state,
            },
        )
        proposal = Proposal(
            proposal_id=intent.proposal_id,
            based_on_revision=intent.based_on_revision,
            operations=(operation,),
            rationale=intent.rationale,
        )
        return self.kernel.submit(proposal, provenance=provenance)

    def request_effect(self, capability: str, payload: JsonValue = None) -> EffectRequest:
        """Construct an unexecuted effect request only when the app declared it."""
        if capability not in self.definition.effect_capabilities:
            raise PermissionError(
                f"application {self.application_id} did not declare effect capability: {capability}"
            )
        return EffectRequest(
            application_id=self.application_id,
            application_version=self.definition.version,
            capability=capability,
            payload=payload,
        )
