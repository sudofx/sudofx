"""Small command-line surface for exercising the kernel."""

from __future__ import annotations

import argparse
import json
import uuid
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .kernel import Kernel
from .models import Operation, Proposal
from .record import Record
from .report import export_site


def _json_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sudofx")
    parser.add_argument("--record", type=Path, default=Path("data/sudofx.sqlite"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="initialize the durable record")
    subparsers.add_parser("show", help="show replayed state")
    subparsers.add_parser("history", help="show transition receipts")
    export_parser = subparsers.add_parser("export", help="build the static web interface")
    export_parser.add_argument("--output", type=Path, default=Path("site"))
    export_parser.add_argument("--repository", default="sudofx/sudofx")
    serve_parser = subparsers.add_parser("serve", help="build and serve the web interface locally")
    serve_parser.add_argument("--output", type=Path, default=Path("site"))
    serve_parser.add_argument("--repository", default="sudofx/sudofx")
    serve_parser.add_argument("--port", type=int, default=8000)
    set_parser = subparsers.add_parser("set", help="propose setting a key")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    delete_parser = subparsers.add_parser("delete", help="propose deleting a key")
    delete_parser.add_argument("key")
    create_parser = subparsers.add_parser("work-create", help="create a governed work item")
    create_parser.add_argument("work_id")
    create_parser.add_argument("objective")
    create_parser.add_argument("--constraint", action="append", default=[])
    advance_parser = subparsers.add_parser("work-advance", help="record accepted progress")
    advance_parser.add_argument("work_id")
    advance_parser.add_argument("result")
    advance_parser.add_argument("--obligation", action="append", default=[])
    complete_parser = subparsers.add_parser("work-complete", help="complete a work item")
    complete_parser.add_argument("work_id")
    complete_parser.add_argument("result")
    show_work_parser = subparsers.add_parser("work-show", help="show bounded work context")
    show_work_parser.add_argument("work_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.record.parent.mkdir(parents=True, exist_ok=True)
    kernel = Kernel(Record(args.record))
    if args.command == "init":
        print(json.dumps({"record": str(args.record), "revision": kernel.context().revision}))
        return 0
    if args.command == "show":
        context = kernel.context()
        print(json.dumps({"revision": context.revision, "state": context.state}, indent=2, sort_keys=True))
        return 0
    if args.command == "history":
        print(json.dumps(kernel.record.recent(100), indent=2, sort_keys=True))
        return 0
    if args.command == "work-show":
        context = kernel.context(work_id=args.work_id, receipt_limit=100)
        print(
            json.dumps(
                {"revision": context.revision, "state": context.state, "receipts": context.recent_receipts},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command in {"export", "serve"}:
        index = export_site(kernel, args.output, repository=args.repository)
        if args.command == "export":
            print(index)
            return 0
        handler = lambda *handler_args, **kwargs: SimpleHTTPRequestHandler(
            *handler_args, directory=str(args.output), **kwargs
        )
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
        print(f"Serving {index} at http://127.0.0.1:{args.port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0

    context = kernel.context()
    if args.command == "set":
        operation = Operation("set", args.key, _json_value(args.value))
    elif args.command == "delete":
        operation = Operation("delete", args.key)
    elif args.command == "work-create":
        operation = Operation(
            "create_work",
            args.work_id,
            {"objective": args.objective, "constraints": args.constraint},
        )
    elif args.command == "work-advance":
        operation = Operation(
            "advance_work",
            args.work_id,
            {"result": args.result, "open_obligations": args.obligation},
        )
    else:
        operation = Operation("complete_work", args.work_id, {"result": args.result})
    proposal = Proposal(str(uuid.uuid4()), context.revision, (operation,), "CLI proposal")
    receipt = kernel.submit(proposal)
    print(json.dumps(asdict(receipt), indent=2, sort_keys=True))
    return 0 if receipt.status == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
