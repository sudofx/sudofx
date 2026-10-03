"""Private HTTP transport for the Conversation application.

SQLite remains authoritative and every semantic provider invocation is a fresh
subprocess. Raw message and response text cross this process only long enough
to serve the current HTTP request. The server persists no transcript and
exposes no observation contents through its status endpoint.
"""
from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from typing import Any
from urllib.parse import urlsplit

from sudofx import ApplicationAccessError, ApplicationHost, ApplicationRegistry, Kernel
from sudofx.governance import Governance
from sudofx.record import Record

from .application import CONVERSATION_APPLICATION, private_bounded_context
from .runtime import recover_failed_private_turn, run_private_turn


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
DEFAULT_DB = ROOT / ".data" / "conversation.sqlite"
MAX_REQUEST_BYTES = 16_384


class ConversationService:
    """Serialize governed turns around one explicitly owned SQLite record."""

    def __init__(self, data_path: Path, *, provider_command: tuple[str, ...] | None = None) -> None:
        self.data_path = data_path
        self.provider_command = provider_command
        self._lock = threading.Lock()
        self._recover_orphaned_turn()

    def _recover_orphaned_turn(self) -> None:
        """Close a half-finished turn left by a prior provider/process failure."""
        registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
        kernel = Kernel(Record(self.data_path), Governance(application_registry=registry))
        state = ApplicationHost(kernel, registry, "conversation").context().state
        projection = private_bounded_context(state)
        if projection["next_role"] == "assistant":
            recover_failed_private_turn(
                data_path=self.data_path,
                category="orphaned_provider_turn",
            )

    def status(self) -> dict[str, Any]:
        """Return privacy-safe continuity counts without observation contents."""
        registry = ApplicationRegistry((CONVERSATION_APPLICATION,))
        kernel = Kernel(Record(self.data_path), Governance(application_registry=registry))
        state = ApplicationHost(kernel, registry, "conversation").context().state
        projection = private_bounded_context(state)
        turn_count = int(projection["turn_count"])
        provider_configured = self.provider_command is not None or bool(
            os.environ.get("GEMINI_API_KEY", "").strip()
            and os.environ.get("GEMINI_MODEL", "").strip()
        )
        access = kernel.application_access_state()
        return {
            "turn_count": turn_count,
            "application_access_enabled": access.enabled,
            "application_access_generation": access.generation,
            "observation_count": int(projection["observation_count"]),
            "provider_invocations": turn_count // 2,
            "next_role": str(projection["next_role"]),
            "provider_configured": provider_configured,
            "provider_model": os.environ.get("GEMINI_MODEL", "").strip() or None,
            "transcript_persisted": False,
        }

    def converse(self, message: str) -> dict[str, Any]:
        """Run exactly one human -> fresh provider -> governed assistant turn."""
        with self._lock:
            content = run_private_turn(
                message,
                data_path=self.data_path,
                provider_command=self.provider_command,
            )
            return {"content": content, "status": self.status()}


def _handler(service: ConversationService):
    class Handler(SimpleHTTPRequestHandler):
        """Serve the chat shell and a same-origin JSON conversation endpoint."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(WEB), **kwargs)

        def end_headers(self) -> None:
            if self.path.startswith("/api/"):
                self.send_header("Cache-Control", "no-store")
                self.send_header("Pragma", "no-cache")
            super().end_headers()

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            requested = urlsplit(self.path)
            if requested.path == "/api/conversation/status":
                try:
                    self._json(200, service.status())
                except Exception:
                    self._json(500, {"error": "conversation status unavailable"})
                return
            if requested.path in {"/", "/conversation"}:
                self.path = "/conversation.html"
                if requested.query:
                    self.path += "?" + requested.query
            super().do_GET()

        def do_POST(self) -> None:
            if self.path != "/api/conversation":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._json(400, {"error": "invalid request length"})
                return
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self._json(413, {"error": "request too large"})
                return
            try:
                payload = json.loads(self.rfile.read(length))
                message = payload.get("message") if isinstance(payload, dict) else None
                if not isinstance(message, str):
                    raise ValueError("message must be text")
                if service.provider_command is None:
                    if not os.environ.get("GEMINI_API_KEY", "").strip():
                        self._json(503, {"error": "Gemini is not configured in this Codespace: GEMINI_API_KEY is missing"})
                        return
                    if not os.environ.get("GEMINI_MODEL", "").strip():
                        self._json(503, {"error": "Gemini is not configured in this Codespace: GEMINI_MODEL is missing"})
                        return
                self._json(200, service.converse(message))
            except ApplicationAccessError as error:
                self._json(503, {"error": error.code})
            except ValueError as error:
                self._json(400, {"error": str(error)})
            except Exception:
                self._json(502, {"error": "the fresh provider turn failed"})

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the private sudofx Conversation chat")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", type=Path, default=Path(os.environ.get("CONVERSATION_DB", DEFAULT_DB)))
    args = parser.parse_args()

    args.database.parent.mkdir(parents=True, exist_ok=True)
    service = ConversationService(args.database)
    server = ThreadingHTTPServer((args.host, args.port), _handler(service))
    print(f"Conversation: http://{args.host}:{args.port}/conversation")
    print(f"SQLite authority: {args.database}")
    print("Transcript persistence: OFF")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
