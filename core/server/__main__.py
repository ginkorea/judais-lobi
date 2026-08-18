# core/server/__main__.py — `python -m core.server`

"""The command line in front of :func:`core.server.create_app`.

Deliberately small.  Everything it can be asked is either *where the runs
are* — which :func:`core.server.resolve_store` answers through the same
resolver the mission CLI uses, so a deployment that has moved
``JUDAIS_LOBI_RUNS`` has thereby moved this — or one of the two operational
numbers, which have their reasons written on them in
:mod:`core.server.sse` and are exposed here so that an operator who has
raised a proxy's ceiling can raise the one that sits under it without
editing a file.

There is no ``--events``-style spec and no personality, because this
process does not run missions.  It reads a directory.

**A missing extra is a sentence and a non-zero exit, never a traceback.**
``EXIT_CONTRACT["diagnostic"]`` says stderr is where this harness puts prose
for a person, and a platform that spawned this gets that sentence and a
status it can test.  The refusal names the extra, in the same words
:func:`core.tools.mcp_client.require_mcp` uses for its own.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from core.durable import POLL_S, RUNS_ENV
from core.server import (
    DEFAULT_HOST, DEFAULT_PORT, ServerUnavailable, create_app, require_uvicorn,
    resolve_store,
)
from core.server.sse import HEARTBEAT_S, MAX_STREAMS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.server",
        description="Serve the judais-lobi run store as server-sent events. "
                    "Read-only.",
    )
    parser.add_argument(
        "--runs", default=None,
        help=f"the run store directory; default is ${RUNS_ENV}, which is "
             f"also where the mission CLI writes")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"default {DEFAULT_HOST} — loopback, because "
                             f"this package has no authentication")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"default {DEFAULT_PORT}")
    parser.add_argument(
        "--max-streams", type=int, default=MAX_STREAMS,
        help=f"concurrent event streams; default {MAX_STREAMS}. Set it BELOW "
             f"the connection ceiling of your reverse proxy and of uvicorn "
             f"itself, so the refusal is this process's 503 and not a proxy's "
             f"502")
    parser.add_argument(
        "--heartbeat", type=float, default=HEARTBEAT_S, metavar="SECONDS",
        help=f"comment line down an idle stream; default {HEARTBEAT_S}. Set "
             f"it BELOW the socket read timeout of your reverse proxy, or a "
             f"mission that thinks for longer than that has its followers cut")
    parser.add_argument(
        "--reconcile", action="store_true",
        help="close the logs of runs whose process died, while serving. Off "
             "by default: the staleness rule cannot tell a dead run from a "
             "slow one, and a watcher must not end a live run's stream")
    parser.add_argument("--log-level", default="info")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Refuse, or listen.  Returns the exit status.

    Every refusal is a sentence on stderr and a non-zero status: a missing
    extra, a store that is switched off, a directory that cannot be opened.
    None of them is a traceback, because the thing reading this process's
    stderr is as likely to be another program as a person.
    """
    args = build_parser().parse_args(argv)
    try:
        uvicorn = require_uvicorn()
        store = resolve_store(args.runs)
        app = create_app(store,
                         max_streams=args.max_streams,
                         heartbeat_s=args.heartbeat,
                         poll_s=POLL_S,
                         reconcile=args.reconcile)
    except ServerUnavailable as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except OSError as exc:
        sys.stderr.write(f"the run store could not be opened: {exc}\n")
        return 1

    sys.stderr.write(
        f"serving {store.root} on http://{args.host}:{args.port} — "
        f"read-only, {args.max_streams} streams, {args.heartbeat}s "
        f"heartbeat\n")
    uvicorn.run(app, host=args.host, port=args.port,
                log_level=args.log_level)
    return 0


if __name__ == "__main__":                      # pragma: no cover - the entry
    raise SystemExit(main())
