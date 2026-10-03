"""Run one governed human -> fresh provider -> assistant Conversation turn."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from .application import (
    CONVERSATION_APPLICATION,
    bounded_context,
    private_assistant_descriptor,
    private_bounded_context,
    enforce_response_commitments,
    private_message_descriptor,
    validate_private_message,
)
from scripts.github_state import DATA, checkpoint, restore
from sudofx import (
    ApplicationHost,
    ApplicationIntent,
    ApplicationRegistry,
    Context,
    Kernel,
    Operation,
    Proposal,
    Runtime,
    SubmissionProvenance,
)
from sudofx.governance import Governance
from sudofx.providers import ProviderError, ProviderQuotaError, ProviderTemporaryError
from sudofx.record import Record


class ProjectedKernel:
    """Expose one bounded context while delegating submission to the real kernel."""

    def __init__(self, kernel: Kernel, context: Context) -> None:
        self.kernel = kernel
        self.projected_context = context

    def context(self, *, receipt_limit: int = 10, work_id: str | None = None) -> Context:
        if work_id is not None:
            raise ValueError("conversation projection does not accept work_id")
        return self.projected_context

    def submit(self, proposal: Proposal, *, provenance: SubmissionProvenance | None = None):
        return self.kernel.submit(proposal, provenance=provenance)


class ConversationIntelligence:
    """Call one semantic provider, then shape its text into a governed app proposal."""

    def __init__(
        self,
        *,
        current_state,
        provider_command: tuple[str, ...],
        private_mode: bool = False,
    ) -> None:
        self.current_state = current_state
        self.provider_command = provider_command
        self.private_mode = private_mode
        self.last_content: str | None = None

    def propose(self, context: Context) -> Proposal:
        request = json.dumps(
            {
                "revision": context.revision,
                "state": context.state,
                "recent_receipts": context.recent_receipts,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        completed = subprocess.run(
            self.provider_command,
            input=request,
            text=True,
            capture_output=True,
            timeout=100,
            check=False,
            env=os.environ.copy(),
        )
        if completed.returncode == 75:
            raise ProviderTemporaryError("conversation provider temporarily unavailable")
        if completed.returncode == 78:
            raise ProviderQuotaError("conversation provider quota exhausted")
        if completed.returncode != 0:
            raise ProviderError("conversation provider failed before returning a valid response")
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ProviderError("conversation provider returned invalid JSON") from error
        content = response.get("content") if isinstance(response, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("conversation provider returned no assistant content")
        self.last_content = content.strip()

        if self.private_mode:
            observations = response.get("observations", [])
            if "commitment_updates" in response:
                commitment_updates = response.get("commitment_updates", [])
            else:
                commitment_updates = []
                suffix = response.get("response_suffix", "")
                clear_suffix = response.get("clear_response_suffix", False)
                if clear_suffix is True:
                    commitment_updates.append({"op": "clear", "kind": "response_suffix"})
                if isinstance(suffix, str) and suffix.strip():
                    commitment_updates.append({
                        "op": "upsert",
                        "kind": "response_suffix",
                        "text": suffix,
                    })
            try:
                self.last_content = enforce_response_commitments(
                    self.current_state,
                    self.last_content,
                    commitment_updates,
                )
                payload = private_assistant_descriptor(
                    self.last_content,
                    observations,
                    commitment_updates,
                )
            except ValueError as error:
                raise ProviderError(str(error)) from error
            action_name = "private_assistant_message"
        else:
            # Legacy proof path retained for existing replay/process-replacement tests.
            payload = self.last_content
            action_name = "assistant_message"

        action = CONVERSATION_APPLICATION.action(action_name)
        assert action is not None
        decision = action.evaluate(self.current_state, payload)
        if not decision.accepted:
            raise ProviderError("assistant response violated conversation application policy")
        return Proposal(
            proposal_id=str(uuid.uuid4()),
            based_on_revision=context.revision,
            operations=(
                Operation(
                    "apply_application",
                    CONVERSATION_APPLICATION.application_id,
                    {
                        "application_id": CONVERSATION_APPLICATION.application_id,
                        "application_version": CONVERSATION_APPLICATION.version,
                        "action": action_name,
                        "input": payload,
                        "next_state": decision.next_state,
                    },
                ),
            ),
            rationale="Stateless provider response to bounded governed conversation context",
        )


def _kernel(path: Path = DATA) -> tuple[Kernel, ApplicationRegistry]:
    registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
    return Kernel(Record(path), Governance(application_registry=registry)), registry


def commit_human_turn(
    message: str,
    *,
    data_path: Path = DATA,
    provenance: SubmissionProvenance | None = None,
    private_mode: bool = False,
) -> None:
    """Commit one human-origin turn without invoking a provider."""
    kernel, registry = _kernel(data_path)
    host = ApplicationHost(kernel, registry, CONVERSATION_APPLICATION.application_id)
    payload = private_message_descriptor(message) if private_mode else message
    action = "private_human_message" if private_mode else "human_message"
    human = host.submit(
        ApplicationIntent(
            proposal_id=str(uuid.uuid4()),
            based_on_revision=host.context().revision,
            action=action,
            payload=payload,
            rationale="Authenticated operator conversation input",
        ),
        provenance=provenance or SubmissionProvenance("human", "operator", "conversation"),
    )
    if human.status != "accepted":
        raise RuntimeError(f"human conversation turn was rejected: {'; '.join(human.reasons)}")


def recover_failed_private_turn(
    *,
    data_path: Path,
    category: str,
) -> None:
    """Return a failed private turn to human-ready state without transcript storage."""
    kernel, registry = _kernel(data_path)
    host = ApplicationHost(kernel, registry, CONVERSATION_APPLICATION.application_id)
    failure = host.submit(
        ApplicationIntent(
            proposal_id=str(uuid.uuid4()),
            based_on_revision=host.context().revision,
            action="private_provider_failure",
            payload={"category": category},
            rationale="Close failed private provider turn without transcript persistence",
        ),
        provenance=SubmissionProvenance("system", "conversation", "provider-failure"),
    )
    if failure.status != "accepted":
        raise RuntimeError(
            f"failed conversation turn could not be recovered: {'; '.join(failure.reasons)}"
        )


def commit_assistant_turn(
    *,
    data_path: Path = DATA,
    provider_command: tuple[str, ...] | None = None,
    provenance: SubmissionProvenance | None = None,
    effect_barrier: Callable[[], None] | None = None,
    private_message: str | None = None,
) -> str:
    """Reopen SQLite, derive bounded context, invoke one provider, and govern its reply."""
    kernel, registry = _kernel(data_path)
    host = ApplicationHost(kernel, registry, CONVERSATION_APPLICATION.application_id)
    app_context = host.context()

    if private_message is None:
        projection = bounded_context(app_context.state)
    else:
        current = validate_private_message(private_message)
        projection = private_bounded_context(app_context.state)
        # The message crosses the intelligence boundary exactly once and is
        # included in the transient context fingerprint/byte receipt, but the
        # message body is never copied into authoritative semantic state.
        projection = {**projection, "current_message": current}

    bounded = Context(
        revision=app_context.revision,
        state={"app:conversation": projection},
        recent_receipts=(),
    )
    command = provider_command or (
        sys.executable,
        "-m",
        "applications.conversation.provider",
    )
    intelligence = ConversationIntelligence(
        current_state=app_context.state,
        provider_command=command,
        private_mode=private_message is not None,
    )
    runtime = Runtime(ProjectedKernel(kernel, bounded), kernel.record)
    runtime.run(
        intelligence,
        provenance=provenance or SubmissionProvenance(
            "model",
            "Google Gemini",
            os.environ.get("GEMINI_MODEL", ""),
        ),
        context_scope={"kind": "application", "application_id": "conversation"},
        effect_barrier=effect_barrier,
    )
    if intelligence.last_content is None:
        raise RuntimeError("conversation provider completed without a response")
    return intelligence.last_content


def run_private_turn(
    message: str,
    *,
    data_path: Path,
    provider_command: tuple[str, ...] | None = None,
) -> str:
    """Run one privacy-bounded turn against an explicitly supplied authority DB.

    This is the host-neutral Conversation execution seam used by private HTTP
    deployments. It performs no GitHub restore/checkpoint transport; the caller
    owns durability of the supplied SQLite database itself.
    """
    message = validate_private_message(message)
    commit_human_turn(message, data_path=data_path, private_mode=True)
    try:
        return commit_assistant_turn(
            data_path=data_path,
            provider_command=provider_command,
            private_message=message,
        )
    except Exception as error:
        try:
            recover_failed_private_turn(
                data_path=data_path,
                category=type(error).__name__,
            )
        except Exception:
            pass
        raise


def run_turn(message: str, *, provider_command: tuple[str, ...] | None = None) -> str:
    """Run the production privacy-bounded turn.

    Raw human/assistant text is transient. SQLite receives only message
    fingerprints, lengths, compact observations, governance receipts, and
    invocation lifecycle evidence.
    """
    message = validate_private_message(message)
    restored, schema_changed = restore()
    _ = restored
    if schema_changed:
        checkpoint()

    commit_human_turn(message, data_path=DATA, private_mode=True)
    checkpoint()
    try:
        response = commit_assistant_turn(
            data_path=DATA,
            provider_command=provider_command,
            effect_barrier=checkpoint,
            private_message=message,
        )
    except Exception:
        checkpoint()
        raise
    checkpoint()
    return response


def _write_summary(path: str | None) -> None:
    if not path:
        return
    Path(path).write_text(
        "# Governed conversation\n\n"
        "One privacy-bounded Conversation turn completed. Message and response "
        "contents are intentionally omitted from this disposable workflow summary.\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", required=True)
    parser.add_argument("--summary-file")
    parser.add_argument("--response-file")
    parser.add_argument(
        "--print-response",
        action="store_true",
        help="Print the transient response. Do not use on public/shared CI logs.",
    )
    args = parser.parse_args()
    response = run_turn(args.message)
    _write_summary(args.summary_file)
    if args.response_file:
        Path(args.response_file).write_text(response, encoding="utf-8")
    if args.print_response:
        print(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
