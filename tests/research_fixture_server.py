# tests/research_fixture_server.py — the local web the research tests read

"""A real HTTP server, on localhost, serving the ``research`` pack's fixtures.

The research tools reach the network, and a test that mocks the network
tests the mock.  So this is a genuine ``ThreadingHTTPServer`` on
``127.0.0.1`` with an ephemeral port, serving the pages committed at
``core/skills/library/research/fixtures/`` — the same files a person
serves with ``python -m http.server`` when they want to try the pack by
hand, so the tests and the documented one-liner are looking at one site.

**Served out of a staged copy**, through
:meth:`core.skills.library.Pack.stage_fixtures`, and never out of the
installed pack.  It costs one directory and it is the convention the
library sets for a reason that applies here too: a pack read out of a
zip-imported install has no directory to point a server at.

Nothing here leaves the machine.  Every test that uses it is
reproducible with no model, no key and no route off localhost.

Beyond the static files it serves five behaviours a static directory
cannot, each because a research tool has to have an answer for it:

``/moved.html``     a 302 to ``solar-array.html``: a citation must name
                    where the redirect landed, not where it started.
``/slow.html``      sleeps past any sane timeout.
``/binary.bin``     ``application/octet-stream``: there is something
                    there and it is not readable.
``/plain.txt``      ``text/plain``: readable, and not HTML.
``/huge.html``      a body past a small ``RESEARCH_MAX_PAGE_BYTES``.

``/retired.html`` is deliberately **absent** — the archive index links to
it, and the 404 is the point.
"""

from __future__ import annotations

import contextlib
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator, Optional

#: How big ``/huge.html`` is.  Comfortably past the smallest ceiling a
#: test would set and nowhere near a real page.
HUGE_BYTES = 2_000_000

#: How long ``/slow.html`` holds the connection.
SLOW_SECONDS = 5.0


class _Handler(SimpleHTTPRequestHandler):
    """The static site, plus the five behaviours named in the module doc."""

    def log_message(self, *_args):           # keep pytest output readable
        pass

    def do_GET(self):                                    # noqa: N802 (stdlib)
        path = self.path.split("?")[0]
        if path == "/moved.html":
            self.send_response(302)
            self.send_header("Location", "/solar-array.html")
            self.end_headers()
            return
        if path == "/slow.html":
            time.sleep(SLOW_SECONDS)
            self._body(b"<html><body><p>late</p></body></html>", "text/html")
            return
        if path == "/binary.bin":
            self._body(b"\x00\x01\x02\x03" * 64, "application/octet-stream")
            return
        if path == "/plain.txt":
            self._body(b"A plain text note. The reading is 71 units.",
                       "text/plain; charset=utf-8")
            return
        if path == "/huge.html":
            filler = b"<p>" + (b"x" * 900) + b"</p>\n"
            body = (b"<html><body><h1>Huge</h1>"
                    + filler * (HUGE_BYTES // len(filler))
                    + b"</body></html>")
            self._body(body, "text/html")
            return
        super().do_GET()

    def _body(self, payload: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class _Server(ThreadingHTTPServer):
    """`ThreadingHTTPServer`, quiet about a client that hung up.

    The timeout test aborts a request mid-body on purpose, and the stdlib
    answers a broken pipe by printing a traceback to stderr — in the
    middle of a green pytest run, which reads as a failure nobody can
    find. The disconnection is the thing under test; it is not news.
    `handle_error` is the SERVER's method and not the handler's, which is
    the mistake worth leaving a note about.
    """

    def handle_error(self, *_args):
        pass


def staged_site(destination: Optional[Path] = None) -> Path:
    """The pack's fixture pages, copied out, and the copy's path."""
    from core.skills import library

    target = Path(destination or tempfile.mkdtemp(prefix="research-site-"))
    return library.load("research").stage_fixtures(target)


@contextlib.contextmanager
def serving(directory: Optional[Path] = None) -> Iterator[str]:
    """Run the fixture site and yield its base URL, e.g. ``http://127.0.0.1:41234``.

    Port zero, so two test sessions on one machine do not collide and no
    test can depend on an address.  The URLs a mission cites therefore
    differ between runs, which is why every assertion about a citation in
    these tests matches the *path* and not the whole address.
    """
    root = Path(directory) if directory is not None else staged_site()
    server = _Server(
        ("127.0.0.1", 0), partial(_Handler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
