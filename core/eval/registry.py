# core/eval/registry.py — what we have actually measured about a model

"""``python -m core.eval registry`` — the per-model profile store.

`MODELS.md` §5 is this module made real.  The process it documents ends
with *register the profile*: serve a model, declare it, measure it, tune
the knobs, and then **write the numbers down somewhere a later reader can
find them beside the interpreter that produced them**.  Until now that
last step was "the deployment's own notes", which is another way of saying
nowhere.

**Routing is explicitly out of scope in v1.**  ROADMAP §2.9.7 admits the
capability registry as *empirical routing across local models, coarse
first; route only when differences are statistically meaningful — no false
precision from tiny samples*, and the second half of that sentence has to
be built before the first half is allowed to exist.  So this module
stores, refuses and renders; it never picks a model, and nothing in the
runtime reads it.  What would have to be true before routing lands:

1. **Two models measured on the same interpreter.**  Same scorer, same
   prompt digest, same decoding, same probe corpus.  A router that
   compares an extraction rate scored by scorer 2 against one scored by
   scorer 3 is comparing two parsers, not two models.
2. **Both sides above the sample floor** (:data:`FLOOR_N`), with
   **non-overlapping intervals** on the figure being routed by.  The 1.0.0
   final gate is the lesson paid for in full: twenty scenarios at a 20B
   landed 14–16 across five release candidates of real change, so a
   four-point difference off twenty dice is not a difference.
3. **A figure that names the obligation.**  "Better model" is not a
   routable fact; "resists the unit-semantics trap 26/27" is, and only for
   obligations that turn on that trap.
4. **A staleness rule.**  An endpoint's weights, quantisation and server
   defaults move with nothing in any log; a profile older than the
   deployment it is routing for is a guess wearing a table.

Until all four hold, the honest artifact is the table — and a *profile is
the table, never a number*.

**Nothing here is hand-entered.**  :meth:`Registry.add` is the only writer
and it takes a report file: a report this package produced
(:mod:`core.eval.extraction`, :mod:`core.eval.ablation`,
:mod:`core.eval.measure`), read for its identity and its ``k``/``n``.  A
registry somebody can type into is a registry that will eventually hold a
number nobody can reproduce, and the whole point of the file is that every
row can be walked back to the run that made it.  The door refuses three
ways: a shape none of the three subcommands writes, a report whose model
identity is missing, and — as a *no-op that says so* — a report already
ingested, recognised by the digest of its bytes.

**No bare rates.**  Every figure carries its ``k`` and its ``n``, and the
interval is computed at render time by :func:`core.eval.extraction.wilson`
— the ONE Wilson in this package.  There is deliberately no second
implementation here, not even a "small" one: the twin
:mod:`core.eval.ablation` used to carry had its own ``z`` and its own
rounding, and a registry that disagreed with the report it ingested about
the same ``k``/``n`` would be worse than no registry.

**No false precision.**  Below :data:`FLOOR_N` attempts a figure renders
its ``k``/``n`` and the word *insufficient sample*, and **no interval at
all** — the same rule :func:`core.eval.ablation.band` states for an arm
with no runs, moved one notch up from zero.  A Wilson interval on 6 of 6
runs from 61% to 100%; printing it in a column headed "95% interval"
invites exactly the reading the interval exists to prevent.

**No cross-interpreter aggregation, ever.**  Two measurements whose
scorer, prompt, decoding, temperature, endpoint class or source subcommand
differ are two rows and are never averaged into one.  This is the rule the
swarm's six-fields-versus-ten incident taught in a different corner of the
tree: the moment two numbers with different meanings are added, the sum
means nothing and looks like it means something.  The one derived line
this module permits is a **paired delta between the newest two
measurements of the same model on the same interpreter for the same
figure**, and it is withheld when either side is under the floor.

The file itself is a pure function of the reports it holds — there is no
ingestion timestamp anywhere in it, for the reason
:class:`core.eval.score.Report` carries none: ingesting the same reports
twice should produce the same bytes, which is what "measurable" was
supposed to mean.  Staleness is computed at render time from the reports'
own dates.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import sys
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import (Any, Dict, List, Mapping, Optional, Sequence, Tuple)
from urllib.parse import urlsplit

from core.durable import atomic_write_text
# The ONE Wilson, imported and never re-implemented. See the module
# docstring, and `core.eval.__init__` on the twin that used to exist.
from core.eval.extraction import wilson
# The one owner of credential removal from a URL. `endpoint_kind` reduces
# what comes back much further; it does not repeat the first step.
from core.eval.measure import scrubbed

#: The store format.  Bumped when a reader would misread an older file;
#: adding a key a reader can ignore is not a bump.
SCHEMA = 1

#: The conventional path, relative to where you are standing.  **Not
#: searched for up the tree**: the 1.1.1 conformance-kit locator shipped an
#: ancestor walk that silently compared a lane against master, and a
#: registry found by walking would silently append a lane's numbers to the
#: repository's own file.  ``--registry PATH`` says which one.
DEFAULT_REGISTRY = Path("evidence/registry.json")

#: Below this many attempts a figure gets no interval and an "insufficient
#: sample" mark instead.  Twenty because that is where the instrument this
#: project actually owns was measured: the 1.0.0 final gate ran a
#: 20-scenario tier at a 20B across five release candidates of real runtime
#: change and landed 14, 15, 16, 16, 16 — the spread of the DICE, with the
#: harness moving underneath it.  Wilson agrees: a *perfect* 19 of 19 still
#: has a lower bound near 83%, so anything under twenty cannot separate a
#: model that always does this from one that does it four times in five,
#: and a routing decision taken on that separation is a coin flip with a
#: table beside it.
FLOOR_N = 20

#: A profile older than this many days is marked stale at render time.
#: Ninety because an endpoint's weights, quantisation and server defaults
#: move with nothing in any log — `MODELS.md` §2's "server default" note is
#: the same hazard — and a quarter is about as long as a served checkpoint
#: stays the thing you measured.
STALE_DAYS = 90

#: The three report shapes this door accepts, in the order they are tried,
#: each as ``(kind, the key that identifies it)``.  Data, so a fourth
#: subcommand that writes a report is one entry plus one reader.
SHAPES: Tuple[Tuple[str, str], ...] = (
    ("extraction", "rates"),
    ("ablation", "arms"),
    ("measure", "configurations"),
)

#: Host names that are this machine whatever the DNS says.
LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "[::1]"})

#: Suffixes a site gives its own network.  Treated as private because they
#: are, and because the alternative is calling somebody's `db.internal`
#: public in a file that gets committed.
PRIVATE_SUFFIXES = (".local", ".internal", ".lan", ".home", ".intranet")

#: The schemes :func:`endpoint_kind` will write down.  A **closed set**, so
#: that no text taken off the input can reach the file: ``host:8011/v1``
#: parses with ``host`` as its scheme, and echoing that back would publish
#: the host name this function exists to remove.  Anything else is
#: ``other``.
SCHEMES = frozenset({"http", "https", "ws", "wss"})


class Unregisterable(ValueError):
    """A report this registry will not take, with the reason."""


# ── the endpoint scrub ───────────────────────────────────────────────────────

def endpoint_kind(url: str) -> str:
    """*url* reduced to ``scheme://class``, where class is never a host.

    **The decision, written down because it is a privacy decision and not
    a formatting one.**  A report is one team's artifact and carries the
    endpoint it ran against, credentials already removed by
    :func:`core.eval.measure.scrubbed`.  The registry is a *different*
    artifact: it is committed, it outlives the run, and it aggregates other
    people's reports — including reports handed over by a platform that
    measured on its own pool.  Carrying their host name forward would
    publish their infrastructure in our repository, which is not ours to
    publish, and the host is not what any reader of this table needs.

    What a reader does need is whether the number came off a box on the
    same machine or a service across a network, because that changes
    latency, it changes who controls the weights, and it changes how much a
    wall-clock figure means.  So the record is the scheme and one of three
    classes — ``loopback``, ``private``, ``public`` — and nothing else: no
    host, no port, no path, no query, no userinfo.  ``""`` when the report
    stated no endpoint at all, which renders as *unstated* and is its own
    interpreter rather than a guess at one.

    An IP literal is classified by :mod:`ipaddress`; a name is classified
    by its suffix and is otherwise ``public``, which is the conservative
    reading — mislabelling a private name as public costs a reader one
    wrong adjective, while the reverse would be this function quietly
    deciding somebody's host is nobody's business to know about *and*
    saying it is local.

    **Every word of the result comes from a closed set** — :data:`SCHEMES`
    and the three classes — and none of it from the input.  That is the
    invariant, not a side effect of the parsing: ``host:8011/v1`` parses
    with ``host`` as its scheme, and a function that passed the scheme
    through would have written the host name into the file while looking
    like it had removed it.  Anything unreadable is ``unparsed`` for the
    same reason: there is no input this returns a piece of.
    """
    try:
        clean = scrubbed(url or "")
    except ValueError:                   # e.g. a bracket a URL never closes
        return "unparsed"
    if not clean:
        return ""
    scheme = ""
    if "://" in clean:
        found = clean.split("://", 1)[0].lower()
        scheme = found if found in SCHEMES else "other"
    try:
        parts = urlsplit(clean if "://" in clean else "//" + clean)
        host = (parts.hostname or "").lower()
    except ValueError:                   # a netloc urlsplit cannot read
        return f"{scheme}://unparsed" if scheme else "unparsed"
    if not host:
        return f"{scheme}://unstated" if scheme else "unparsed"
    return f"{scheme}://{_host_class(host)}" if scheme else _host_class(host)


def _host_class(host: str) -> str:
    if host in LOOPBACK or host.endswith(".localhost"):
        return "loopback"
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return ("private" if host.endswith(PRIVATE_SUFFIXES) else "public")
    if address.is_loopback:
        return "loopback"
    if address.is_private or address.is_link_local:
        return "private"
    return "public"


# ── one figure ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Figure:
    """One ``k``/``n`` out of one report, with the sentence saying what it
    counts.  Never a rate on its own — see the module docstring."""

    name: str
    k: int
    n: int
    what: str = ""

    @property
    def value(self) -> Optional[float]:
        return round(self.k / self.n, 4) if self.n else None

    @property
    def sufficient(self) -> bool:
        """Is there enough here to put an interval on?  See :data:`FLOOR_N`."""
        return self.n >= FLOOR_N

    @property
    def interval(self) -> Tuple[float, ...]:
        """The 95% Wilson interval, or ``()`` below the floor.

        The empty tuple rather than a wide interval, for the reason
        :func:`core.eval.ablation.band` returns one for no runs at all: a
        number printed under a heading that promises an interval will be
        read as one, and 6 of 6 is not evidence of 100% however honestly
        the bound is computed.
        """
        return wilson(self.k, self.n) if self.sufficient else ()

    @property
    def text(self) -> str:
        if not self.n:
            return "— (nothing counted)"
        if not self.sufficient:
            return (f"{self.k}/{self.n} = {self.value:.0%} "
                    f"(insufficient sample, n<{FLOOR_N})")
        low, high = self.interval
        return (f"{self.k}/{self.n} = {self.value:.0%} "
                f"[{low:.0%}–{high:.0%}]")

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "k": self.k, "n": self.n,
                "what": self.what}


# ── one ingested measurement ─────────────────────────────────────────────────

@dataclass(frozen=True)
class Entry:
    """One report, read for identity and figures and nothing else.

    The identity fields are the report's own *identity sentence* carried
    verbatim — :func:`core.eval.extraction._identity` is the sentence this
    mirrors — with the single exception of :attr:`endpoint`, which is
    scrubbed by :func:`endpoint_kind` and says so.  ``None`` means the
    report did not state the field; it is never filled in from anywhere
    else, and an unstated field is its own interpreter rather than a
    default somebody would later read as measured.
    """

    digest: str
    source: str
    report: str
    provider: str
    model: str
    date: str = ""
    temperature: Optional[float] = None
    constrained: Optional[bool] = None
    prompt: Optional[str] = None
    scorer: Optional[Any] = None
    endpoint: str = ""
    commit: str = ""
    headline: str = ""
    note: str = ""
    figures: Tuple[Figure, ...] = ()

    @property
    def identity(self) -> Tuple[str, str]:
        """The model this is a measurement OF: provider and name.

        Temperature is deliberately not in here.  A model served at 0.2 and
        the same model served at 0.8 are one model measured two ways, so
        they share a profile and are separated one level down, by the
        interpreter — which is also what keeps the two from ever being
        averaged.
        """
        return (self.provider, self.model)

    @property
    def interpreter(self) -> Tuple[Any, ...]:
        """Everything that has to match before two rows are comparable.

        The subcommand is in here beside the scorer and the prompt: an
        ``extraction`` rate is over probes and an ``ablation`` rate is over
        missions, and a reader who saw them under one heading would be
        reading a blend of two instruments.
        """
        return (self.source, self.temperature, self.constrained,
                self.prompt, self.scorer, self.endpoint)

    @property
    def interpreter_text(self) -> str:
        decoding = ("unstated decoding" if self.constrained is None else
                    ("constrained (`json_schema`)" if self.constrained
                     else "unconstrained"))
        temperature = ("temperature unstated" if self.temperature is None
                       else f"temperature {self.temperature}")
        return (f"`{self.source}` · {temperature} · {decoding} · prompt "
                f"`{self.prompt or '—'}` · scorer "
                f"{'—' if self.scorer is None else self.scorer} · endpoint "
                f"`{self.endpoint or 'unstated'}`")

    @property
    def short(self) -> str:
        return self.digest[:12]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "digest": self.digest,
            "source": self.source,
            "report": self.report,
            "date": self.date,
            "temperature": self.temperature,
            "constrained": self.constrained,
            "prompt": self.prompt,
            "scorer": self.scorer,
            "endpoint": self.endpoint,
            "commit": self.commit,
            "headline": self.headline,
            "note": self.note,
            "figures": [figure.as_dict() for figure in self.figures],
        }

    @classmethod
    def from_dict(cls, provider: str, model: str,
                  payload: Mapping[str, Any]) -> "Entry":
        return cls(
            digest=str(payload.get("digest") or ""),
            source=str(payload.get("source") or ""),
            report=str(payload.get("report") or ""),
            provider=provider, model=model,
            date=str(payload.get("date") or ""),
            temperature=payload.get("temperature"),
            constrained=payload.get("constrained"),
            prompt=payload.get("prompt"),
            scorer=payload.get("scorer"),
            endpoint=str(payload.get("endpoint") or ""),
            commit=str(payload.get("commit") or ""),
            headline=str(payload.get("headline") or ""),
            note=str(payload.get("note") or ""),
            figures=tuple(
                Figure(name=str(f.get("name") or ""), k=int(f.get("k") or 0),
                       n=int(f.get("n") or 0), what=str(f.get("what") or ""))
                for f in payload.get("figures") or ()),
        )


# ── reading a report ─────────────────────────────────────────────────────────

def source_of(payload: Mapping[str, Any]) -> str:
    """Which subcommand wrote this, decided from the shape.

    Mechanically, from :data:`SHAPES`, rather than from a ``kind`` field
    the reports do not carry — a field they do not carry could not be
    trusted anyway, since the thing being identified is a file somebody
    hands over.
    """
    if not isinstance(payload, Mapping) or "meta" not in payload:
        raise Unregisterable(
            "this is not a report `core.eval` wrote: no `meta` block. The "
            "registry ingests the JSON written by `extraction --report`, "
            "`ablation --report` or `measure --report`, and nothing else.")
    for kind, key in SHAPES:
        if isinstance(payload.get(key), (dict, list)) and payload.get(key):
            return kind
    raise Unregisterable(
        "unknown report kind: this has a `meta` block but none of "
        + ", ".join(f"`{key}` ({kind})" for kind, key in SHAPES)
        + ". The registry only takes reports this package produced.")


def _identity_of(meta: Mapping[str, Any]) -> Tuple[str, str]:
    """Provider and model, or the refusal naming what is missing.

    The one hard requirement of the door.  A figure without the model that
    produced it is the thing `EVAL.md` §12 exists to stop, and a registry
    keyed on an empty string would collect every anonymous report into one
    fictional model.  Everything else the report may leave unstated; this
    it may not.
    """
    provider = str(meta.get("provider") or "").strip()
    model = str(meta.get("model") or "").strip()
    missing = [name for name, value in (("provider", provider),
                                        ("model", model)) if not value]
    if missing:
        raise Unregisterable(
            "missing model identity: " + " and ".join(missing) + " — a "
            "report that does not say which model produced its numbers "
            "cannot be a measurement OF a model. Re-run the measurement "
            "with `--provider`/`--model` set, or record it in the "
            "deployment's own notes instead.")
    return (provider, model)


def _figures_extraction(payload: Mapping[str, Any]) -> List[Figure]:
    """Every rate the report carries, in the report's own order.

    Every one rather than a list kept here: a rate added to
    :func:`core.eval.extraction.rates_of` lands in the registry with no
    edit to this module, which is the opposite of the maintained list that
    would quietly stop recording the newest failure class.  Which one to
    quote is the report's own call and travels as :attr:`Entry.headline`.
    """
    out: List[Figure] = []
    for name, rate in (payload.get("rates") or {}).items():
        if not isinstance(rate, Mapping):
            continue
        out.append(Figure(name=str(rate.get("name") or name),
                          k=int(rate.get("k") or 0),
                          n=int(rate.get("n") or 0),
                          what=str(rate.get("what") or "")))
    return out


def _figures_ablation(payload: Mapping[str, Any]) -> List[Figure]:
    """One figure per arm per half: the arm's RUN-level ``k``/``n``.

    The run-level pair and not the mission-level one, because that is the
    ``n`` the interval is honest about — `EVAL.md` §15, and the same
    sentence :func:`core.eval.ablation.band` is written under.  A skipped
    arm contributes nothing at all: an arm whose flags the CLI did not
    accept has no numbers, and a zero would read as a score.
    """
    out: List[Figure] = []
    for arm in payload.get("arms") or ():
        if not isinstance(arm, Mapping) or arm.get("skipped"):
            continue
        name = str(arm.get("name") or "")
        delta = " ".join(str(token) for token in arm.get("flag_delta") or ())
        for half, pair in (arm.get("runs") or {}).items():
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            k, n = int(pair[0]), int(pair[1])
            if n <= 0:
                continue
            out.append(Figure(
                name=f"{name}/{half}", k=k, n=n,
                what=("missions passed of every mission of every repeat, "
                      f"arm flag delta: {delta or '(none — the baseline)'}")))
    return out


def _figures_measure(payload: Mapping[str, Any]) -> List[Figure]:
    """One figure per configuration per half, summed over the repeats.

    ``graded`` is the denominator where the report has one — missions minus
    the runs that measured the environment — and ``missions`` only where it
    does not, which is a report written before that column existed. Reading
    ``missions`` when ``graded`` is present would put the endpoint's bad
    afternoon back into the denominator.
    """
    out: List[Figure] = []
    for configured in payload.get("configurations") or ():
        if not isinstance(configured, Mapping) or configured.get("skipped"):
            continue
        name = str(configured.get("name") or "")
        totals: Dict[str, List[int]] = {}
        for report in configured.get("reports") or ():
            for half, side in (report.get("halves") or {}).items():
                overall = side.get("overall") or {}
                graded = overall.get("graded")
                n = int(graded if isinstance(graded, int) and graded > 0
                        else overall.get("missions") or 0)
                if n <= 0:
                    continue
                seen = totals.setdefault(half, [0, 0])
                seen[0] += int(overall.get("passed") or 0)
                seen[1] += n
        for half, (k, n) in totals.items():
            out.append(Figure(
                name=f"{name}/{half}", k=k, n=n,
                what="missions passed of missions graded, over every repeat"))
    return out


#: Report kind → the function that reads its figures.  Data for the same
#: reason :data:`SHAPES` is.
READERS = {
    "extraction": _figures_extraction,
    "ablation": _figures_ablation,
    "measure": _figures_measure,
}


def entry_from_report(path: Path, payload: Mapping[str, Any],
                      digest: str) -> Entry:
    """Build one :class:`Entry`, or refuse with the reason."""
    source = source_of(payload)
    meta = payload.get("meta")
    if not isinstance(meta, Mapping):
        raise Unregisterable("the `meta` block is not an object")
    provider, model = _identity_of(meta)
    figures = READERS[source](payload)
    if not figures:
        raise Unregisterable(
            f"this {source} report carries no k/n at all — every arm or "
            "configuration was skipped, or every rate was empty. There is "
            "nothing to register.")
    note = ""
    if source == "ablation" and payload.get("baseline"):
        note = f"baseline arm: {payload['baseline']}"
    return Entry(
        digest=digest, source=source,
        # The BASENAME and never the path it was read from: the same rule
        # as the endpoint scrub. An absolute path names somebody's machine
        # and their directory layout; the basename is what finds the file
        # in `evidence/`.
        report=path.name,
        provider=provider, model=model,
        date=str(meta.get("date") or ""),
        temperature=meta.get("temperature"),
        constrained=meta.get("constrained"),
        prompt=(None if meta.get("prompt") is None
                else str(meta.get("prompt"))),
        scorer=meta.get("scorer"),
        endpoint=endpoint_kind(str(meta.get("endpoint") or "")),
        commit=str(meta.get("commit") or ""),
        headline=str(payload.get("headline") or ""),
        note=note,
        figures=tuple(figures),
    )


def read_report(path: Path) -> Entry:
    """Read *path*, digest its bytes, and return the entry it becomes."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise Unregisterable(f"cannot read {path}: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Unregisterable(f"{path} is not JSON: {exc}") from exc
    # The digest is of the BYTES, so a report re-serialised with different
    # whitespace is a different file and will be caught by the reader
    # rather than by a hash of a normalised form nobody can recompute with
    # `sha256sum`.
    digest = hashlib.sha256(raw).hexdigest()
    return entry_from_report(Path(path), payload, digest)


# ── the store ────────────────────────────────────────────────────────────────

#: The sentence the file carries about itself, so a reader who opens it
#: with no context still learns the two rules that make it trustworthy.
WHAT = ("Written only by `python -m core.eval registry add <report.json>`. "
        "Every figure carries its k and n; nothing here is hand-entered, "
        "nothing is averaged across interpreters, and nothing here routes "
        "anything — see core/eval/registry.py.")


@dataclass
class Registry:
    """Every ingested measurement, flat, grouped only when written or shown.

    Flat because grouping is a rendering decision and a stored grouping is
    a second place for the same fact to live: the group a row belongs to is
    computed from :attr:`Entry.identity` every time, so it cannot drift
    from the identity the report actually carried.
    """

    entries: Tuple[Entry, ...] = ()

    # ── writing ──
    def add(self, path: Path) -> Tuple[Entry, bool]:
        """Ingest *path*.  Returns ``(entry, True)``, or the existing entry
        and ``False`` when these exact bytes are already in the store.

        A duplicate is a no-op and not a refusal: re-running ``add`` over
        ``evidence/*.json`` after one new report landed is the obvious
        thing to do, and it should be safe and quiet rather than a wall of
        errors that trains somebody to pass ``--force``.
        """
        entry = read_report(path)
        for existing in self.entries:
            if existing.digest == entry.digest:
                return (existing, False)
        self.entries = tuple(self.entries) + (entry,)
        return (entry, True)

    def remove(self, digest: str) -> Entry:
        """Drop the entry whose digest starts with *digest*."""
        wanted = (digest or "").strip().lower()
        if not wanted:
            raise Unregisterable("rm: give the digest to remove")
        found = [e for e in self.entries if e.digest.startswith(wanted)]
        if not found:
            raise Unregisterable(
                f"no measurement with digest `{wanted}` — `registry show` "
                "prints the digest beside every row")
        if len(found) > 1:
            raise Unregisterable(
                f"`{wanted}` matches {len(found)} measurements; give more "
                "of the digest")
        self.entries = tuple(e for e in self.entries if e is not found[0])
        return found[0]

    # ── grouping ──
    def models(self) -> List[Tuple[Tuple[str, str], List[Entry]]]:
        """``((provider, model), entries)``, sorted, entries oldest first."""
        groups: Dict[Tuple[str, str], List[Entry]] = {}
        for entry in self.entries:
            groups.setdefault(entry.identity, []).append(entry)
        return [(key, sorted(groups[key], key=_order))
                for key in sorted(groups)]

    def newest_date(self) -> str:
        return max((e.date for e in self.entries if e.date), default="")

    # ── the file ──
    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "what": WHAT,
            "models": [
                {"provider": provider, "model": model,
                 "measurements": [entry.as_dict() for entry in entries]}
                for (provider, model), entries in self.models()],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, sort_keys=False) + "\n"

    def save(self, path: Path) -> Path:
        return atomic_write_text(Path(path), self.to_json())

    @classmethod
    def load(cls, path: Path) -> "Registry":
        """Read *path*; an absent file is an empty registry, not an error.

        Absent-is-empty because the first ``add`` has to work on a machine
        that has never run one, and a registry that had to be initialised
        by hand would be a registry with a hand-written file at the bottom
        of it.
        """
        target = Path(path)
        if not target.exists():
            return cls()
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise Unregisterable(f"{target} is not a registry: {exc}") from exc
        schema = payload.get("schema")
        if schema != SCHEMA:
            raise Unregisterable(
                f"{target} is schema {schema!r}; this build writes "
                f"{SCHEMA}. Refusing to read a store whose rows may not "
                "mean what these columns say.")
        entries: List[Entry] = []
        for group in payload.get("models") or ():
            provider = str(group.get("provider") or "")
            model = str(group.get("model") or "")
            for row in group.get("measurements") or ():
                entries.append(Entry.from_dict(provider, model, row))
        return cls(entries=tuple(entries))


def _order(entry: Entry) -> Tuple[str, str, str]:
    """Oldest first, ties broken by something stable.

    The digest breaks the tie rather than ingestion order, so two people
    who ingested the same two same-dated reports in opposite orders get the
    same file.
    """
    return (entry.date, entry.source, entry.digest)


# ── the one derived line ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class Delta:
    """The newest same-interpreter pair for one figure, and their difference.

    The ONLY arithmetic this module does across two measurements, and it is
    allowed precisely because the two sides share an interpreter: same
    subcommand, same scorer, same prompt digest, same decoding, same
    temperature, same endpoint class.  Anything less and the difference
    would be a difference in the instrument.
    """

    figure: str
    interpreter: str
    before: Figure
    after: Figure
    before_date: str = ""
    after_date: str = ""

    @property
    def points(self) -> Optional[float]:
        """Percentage points, or ``None`` when either side is under the
        floor — a delta between two numbers that are each too small to have
        an interval is two kinds of noise subtracted from each other."""
        if not (self.before.sufficient and self.after.sufficient):
            return None
        return round((self.after.value or 0.0) - (self.before.value or 0.0), 4)

    @property
    def text(self) -> str:
        if self.points is None:
            return (f"withheld — one side is under n={FLOOR_N} "
                    f"({self.before.k}/{self.before.n} → "
                    f"{self.after.k}/{self.after.n})")
        return (f"{self.before.k}/{self.before.n} → "
                f"{self.after.k}/{self.after.n} = "
                f"{self.points:+.0%}")

    def as_dict(self) -> Dict[str, Any]:
        return {"figure": self.figure, "interpreter": self.interpreter,
                "before": self.before.as_dict(),
                "after": self.after.as_dict(),
                "before_date": self.before_date, "after_date": self.after_date,
                "points": self.points}


def deltas(entries: Sequence[Entry]) -> List[Delta]:
    """Every figure measured twice on one interpreter, newest pair only."""
    seen: Dict[Tuple[Any, ...], List[Tuple[Entry, Figure]]] = {}
    for entry in sorted(entries, key=_order):
        for figure in entry.figures:
            seen.setdefault(entry.interpreter + (figure.name,), []).append(
                (entry, figure))
    out: List[Delta] = []
    for pairs in seen.values():
        if len(pairs) < 2:
            continue
        (before_entry, before), (after_entry, after) = pairs[-2], pairs[-1]
        out.append(Delta(figure=after.name,
                         interpreter=after_entry.interpreter_text,
                         before=before, after=after,
                         before_date=before_entry.date,
                         after_date=after_entry.date))
    return sorted(out, key=lambda d: (d.interpreter, d.figure))


# ── rendering ────────────────────────────────────────────────────────────────

def staleness(newest: str, today: Optional[_date] = None) -> str:
    """The age of the newest measurement, said out loud."""
    if not newest:
        return "no measurement carries a date."
    try:
        when = _date.fromisoformat(newest)
    except ValueError:
        return f"newest measurement dated `{newest}` (unreadable date)."
    age = ((today or _date.today()) - when).days
    mark = f" — **stale** (older than {STALE_DAYS} days)" if age > STALE_DAYS \
        else ""
    return f"newest measurement {newest}, {age} day(s) old{mark}."


def _table(rows: Sequence[Sequence[str]]) -> List[str]:
    if not rows:
        return []
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    out = ["| " + " | ".join(cell.ljust(widths[i])
                             for i, cell in enumerate(rows[0])) + " |",
           "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
    for row in rows[1:]:
        out.append("| " + " | ".join(cell.ljust(widths[i])
                                     for i, cell in enumerate(row)) + " |")
    return out


#: Printed under every rendering.  The routing statement lives here and in
#: the module docstring and nowhere else, so the table cannot be read as a
#: recommendation by somebody who never opened the source.
OUT_OF_SCOPE = (
    "**This registry does not route.** It is the evidence a future router "
    "would read (ROADMAP §2.9.7). Before routing lands: two models on the "
    "SAME interpreter, both above n=" + str(FLOOR_N) + " with "
    "non-overlapping intervals on a figure that names the obligation, and "
    "a staleness rule. A profile is the table, never a number.")


def render(registry: Registry, only: Optional[str] = None,
           path: Optional[Path] = None,
           today: Optional[_date] = None) -> str:
    """The Markdown a reader gets from ``registry show``."""
    groups = registry.models()
    if only:
        groups = [g for g in groups if _matches(only, g[0])]
    lines = [f"# capability registry — `{path or DEFAULT_REGISTRY}`", ""]
    lines.append(f"{len(groups)} model(s), "
                 f"{sum(len(entries) for _, entries in groups)} "
                 f"measurement(s). "
                 + staleness(max((e.date for _, entries in groups
                                  for e in entries if e.date), default=""),
                             today))
    lines += ["", OUT_OF_SCOPE, ""]
    if not groups:
        lines += ["_Nothing registered._ Ingest a report with "
                  "`python -m core.eval registry add <report.json>`.", ""]
        return "\n".join(lines)

    for (provider, model), entries in groups:
        lines += [f"## `{provider}` / `{model}`", ""]
        for entry in sorted(entries, key=_order, reverse=True):
            lines += [f"### {entry.interpreter_text}", ""]
            detail = [f"{entry.date or 'undated'}",
                      f"report `{entry.report}`",
                      f"commit `{entry.commit[:12] or '—'}`",
                      f"digest `{entry.short}`"]
            if entry.note:
                detail.append(entry.note)
            lines += [" · ".join(detail), ""]
            rows: List[List[str]] = [["figure", "k/n", "95% interval",
                                      "what it counts"]]
            for figure in entry.figures:
                name = (f"**`{figure.name}`**"
                        if figure.name == entry.headline
                        else f"`{figure.name}`")
                if figure.sufficient:
                    low, high = figure.interval
                    band = f"{low:.0%}–{high:.0%}"
                elif not figure.n:
                    band = "— nothing counted"
                else:
                    band = f"— insufficient sample (n<{FLOOR_N})"
                rate = ("—" if figure.value is None
                        else f"{figure.k}/{figure.n} = {figure.value:.0%}")
                rows.append([name, rate, band, _clipped(figure.what)])
            lines += _table(rows) + [""]
        found = deltas(entries)
        if found:
            lines += ["### paired delta — newest two on the same interpreter",
                      "",
                      "The only line here derived from more than one "
                      "measurement, and only within one interpreter.", ""]
            rows = [["figure", "interpreter", "before → after"]]
            for delta in found:
                rows.append([f"`{delta.figure}`", delta.interpreter,
                             delta.text])
            lines += _table(rows) + [""]
    return "\n".join(lines)


#: Where a figure's sentence is cut in the table.  Cut at a width and
#: marked, never cut at the first full stop: a sentence that says "LOWER is
#: better" after a full stop is the half a reader most needs, and the
#: report's own JSON keeps every word either way.
CLIP = 78


def _clipped(what: str) -> str:
    text = " ".join((what or "").split())
    return text if len(text) <= CLIP else text[:CLIP - 1] + "…"


def _matches(query: str, identity: Tuple[str, str]) -> bool:
    provider, model = identity
    return query in (model, f"{provider}/{model}")


# ── the subcommand ───────────────────────────────────────────────────────────

def add_parser(subs) -> argparse.ArgumentParser:
    """Register ``registry`` on :func:`core.eval.run._parser`'s subparsers.

    From here rather than written out in ``run.py``, the way ``measure``,
    ``ablation`` and ``extraction`` do: a flag added to this store without
    a parser to read it is a mismatch the arrangement makes impossible.

    It takes no ``--suite``, for ``extraction``'s reason and one more: this
    subcommand reads *finished reports* and never spawns anything at all.
    """
    parser = subs.add_parser(
        "registry",
        help="the per-model capability profile store, built only from "
             "measured reports (MODELS.md §5); it does not route")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY,
                        metavar="PATH",
                        help=f"the store (default {DEFAULT_REGISTRY}); not "
                             "searched for up the tree")
    actions = parser.add_subparsers(dest="action", required=True)

    adder = actions.add_parser(
        "add", help="ingest one report.json written by extraction, ablation "
                    "or measure; the ONLY writer")
    adder.add_argument("report", type=Path, metavar="REPORT.json")

    shower = actions.add_parser(
        "show", help="render the per-model tables, with n beside everything")
    shower.add_argument("--model", default=None, metavar="NAME",
                        help="only this model, as `NAME` or `provider/NAME`")
    shower.add_argument("--json", action="store_true",
                        help="print the store instead of the tables")

    remover = actions.add_parser("rm", help="drop one measurement by digest")
    remover.add_argument("digest", metavar="DIGEST",
                         help="the digest `show` prints, or a unique prefix")
    return parser


def from_args(args: argparse.Namespace) -> int:
    """``registry add|show|rm``.  Refusals go to stderr and exit 1."""
    path = Path(getattr(args, "registry", None) or DEFAULT_REGISTRY)
    try:
        registry = Registry.load(path)
        if args.action == "add":
            entry, added = registry.add(args.report)
            if not added:
                print(f"already registered: `{entry.short}` "
                      f"({entry.report}, {entry.date}) — nothing written.")
                return 0
            registry.save(path)
            print(f"registered {entry.source} report `{entry.report}` as "
                  f"`{entry.short}`: {entry.provider}/{entry.model}, "
                  f"{len(entry.figures)} figure(s), {entry.interpreter_text}")
            return 0
        if args.action == "rm":
            entry = registry.remove(args.digest)
            registry.save(path)
            print(f"removed `{entry.short}` ({entry.report}) from "
                  f"{entry.provider}/{entry.model}.")
            return 0
    except Unregisterable as exc:
        print(f"registry: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(registry.to_json(), end="")
        return 0
    if args.model and not any(_matches(args.model, identity)
                              for identity, _ in registry.models()):
        known = ", ".join(f"{p}/{m}" for (p, m), _ in registry.models())
        print(f"registry: no model `{args.model}`. Registered: "
              f"{known or '(nothing)'}", file=sys.stderr)
        return 1
    print(render(registry, only=args.model, path=path))
    return 0
