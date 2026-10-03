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
import hashlib
from typing import TYPE_CHECKING, Callable, Literal

if TYPE_CHECKING:
    from .kernel import Kernel
from .models import JsonValue, Operation, Proposal, Receipt, SubmissionProvenance
from .storage import canonical_json


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
    state_storage: Literal["snapshot", "event_log"] = "snapshot"

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
        if self.state_storage not in {"snapshot", "event_log"}:
            raise ValueError("application state_storage must be snapshot or event_log")

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


def application_state(
    definition: ApplicationDefinition,
    envelope: JsonValue,
) -> JsonValue:
    """Reconstruct one application state from its generic durable envelope."""
    if envelope is None:
        return None
    if not isinstance(envelope, dict):
        raise ValueError(f"application state envelope is invalid: {definition.application_id}")
    if envelope.get("application_id") != definition.application_id:
        raise ValueError(f"application state identity mismatch: {definition.application_id}")
    if envelope.get("application_version") != definition.version:
        raise ValueError(
            f"application migration required: stored {envelope.get('application_version')}, "
            f"registered {definition.version}"
        )

    storage = envelope.get("storage", "snapshot")
    if storage == "event_log" and "projection_state" in envelope:
        if definition.state_storage != "event_log":
            raise ValueError("application storage mode does not match registered definition")
        return envelope.get("projection_state")
    if storage == "snapshot":
        if definition.state_storage != "snapshot":
            raise ValueError("application storage mode does not match registered definition")
        return envelope.get("state")
    if storage != "event_log" or definition.state_storage != "event_log":
        raise ValueError("application storage mode does not match registered definition")

    events = envelope.get("events")
    if not isinstance(events, list):
        raise ValueError("application event log is invalid")
    state: JsonValue = None
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"application event {index} is invalid")
        action_name = event.get("action")
        result_digest = event.get("result_digest")
        if not isinstance(action_name, str) or not isinstance(result_digest, str):
            raise ValueError(f"application event {index} is incomplete")
        action = definition.action(action_name)
        if action is None:
            raise ValueError(f"application event uses unknown action: {action_name}")
        decision = action.evaluate(state, event.get("input"))
        if not decision.accepted:
            raise ValueError(f"application replay rejected historical action: {action_name}")
        expected = hashlib.sha256(canonical_json(decision.next_state).encode()).hexdigest()
        if expected != result_digest:
            raise ValueError(f"application replay drift detected at event {index}")
        state = decision.next_state
    return state

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
class ApplicationPermissions:
    """Deployment-granted capabilities that may only narrow app declarations."""

    effect_capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if any(not capability.strip() for capability in self.effect_capabilities):
            raise ValueError("granted effect capability names must not be empty")

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
        *,
        permissions: ApplicationPermissions | None = None,
    ) -> None:
        definition = registry.get(application_id)
        if definition is None:
            raise ValueError(f"application is not registered: {application_id}")
        self.kernel = kernel
        self.registry = registry
        self.application_id = application_id
        self.permissions = permissions or ApplicationPermissions()

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
        app_state = application_state(self.definition, envelope)
        return ApplicationContext(
            application_id=self.application_id,
            application_version=self.definition.version,
            revision=context.revision,
            state=app_state,
        )

    def audit_context(self) -> ApplicationContext:
        """Rebuild this application's state from semantic history for explicit audit."""
        revision, state = self.kernel.record.full_replay()
        envelope = state.get(application_key(self.application_id))
        app_state = application_state(self.definition, envelope)
        return ApplicationContext(
            application_id=self.application_id,
            application_version=self.definition.version,
            revision=revision,
            state=app_state,
        )

    def submit(
        self,
        intent: ApplicationIntent,
        *,
        provenance: SubmissionProvenance | None = None,
    ) -> Receipt:
        """Submit one application intent through the global access gate and Kernel."""
        access = self.kernel.application_access_state()
        if not access.enabled:
            from .storage import ApplicationAccessError
            raise ApplicationAccessError()
        definition = self.definition
        raw_context = self.kernel.context()
        envelope = raw_context.state.get(application_key(self.application_id))
        try:
            current = application_state(definition, envelope)
        except ValueError:
            # Submission still crosses the kernel boundary so version/storage/
            # replay mismatches become durable governed rejections rather than
            # disappearing as host-side exceptions before a receipt exists.
            decision = ApplicationDecision(False)
        else:
            action = definition.action(intent.action)
            decision = (
                action.evaluate(current, intent.payload)
                if action is not None
                else ApplicationDecision(
                    False,
                    reasons=(f"unknown application action: {intent.action}",),
                )
            )
        value: dict[str, JsonValue] = {
            "application_id": self.application_id,
            "application_version": definition.version,
            "action": intent.action,
            "input": intent.payload,
        }
        if definition.state_storage == "event_log":
            value["storage"] = "event_log"
            value["result_digest"] = hashlib.sha256(
                canonical_json(decision.next_state).encode()
            ).hexdigest()
            # This derived state is validated by governance but stripped before
            # semantic persistence. Storage may commit it only to the database
            # projection so normal fresh-process reads avoid replaying the
            # application's entire event history.
            value["projection_state"] = decision.next_state
        else:
            value["next_state"] = decision.next_state
        operation = Operation("apply_application", self.application_id, value)
        proposal = Proposal(
            proposal_id=intent.proposal_id,
            based_on_revision=intent.based_on_revision,
            operations=(operation,),
            rationale=intent.rationale,
        )
        return self.kernel.submit(
            proposal,
            provenance=provenance,
            application_access_generation=access.generation,
        )

    def request_effect(self, capability: str, payload: JsonValue = None) -> EffectRequest:
        """Construct an unexecuted effect request only when the app declared it."""
        if capability not in self.definition.effect_capabilities:
            raise PermissionError(
                f"application {self.application_id} did not declare effect capability: {capability}"
            )
        if capability not in self.permissions.effect_capabilities:
            raise PermissionError(
                f"deployment did not grant effect capability to {self.application_id}: {capability}"
            )
        return EffectRequest(
            application_id=self.application_id,
            application_version=self.definition.version,
            capability=capability,
            payload=payload,
        )
