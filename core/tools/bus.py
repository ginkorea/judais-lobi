# core/tools/bus.py — ToolBus registry and dispatch

import json as _json
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any

from core.bounding import bound_result
from core.tools.descriptors import (
    ToolDescriptor,
    SandboxProfile,
    SKIP_SANDBOX_ACTIONS,
    NETWORK_ACTIONS,
    summarize_input_schema,
)
from core.tools.capability import CapabilityEngine, CapabilityVerdict
from core.tools.executor import use_subprocess_runner
from core.tools.sandbox import (
    SandboxRunner,
    BwrapSandbox,
    build_sandbox_env,
    select_sandbox,
)


@dataclass
class ToolResult:
    """Structured result from a tool invocation."""
    exit_code: int
    stdout: str
    stderr: str
    tool_name: str
    granted_scopes: List[str] = field(default_factory=list)
    evidence: Optional[str] = None


class ToolBus:
    """Tool registry with capability gating and sandboxed execution.

    This docstring said "MCP-style" for a long time while nothing in the
    package spoke MCP.  Something does now, but not this file:
    ``core.tools.mcp_client`` is the real client and it *bridges into
    this bus* — a tool a server advertises becomes an ordinary
    ``ToolDescriptor`` registered here, so everything below applies to it
    unchanged.

    Dispatch path: register -> check capabilities -> execute -> result

    For multi-action tools, pass ``action=`` as a keyword argument to
    ``dispatch()``.  The bus resolves scopes from
    ``descriptor.action_scopes[action]`` when available, falling back to
    ``descriptor.required_scopes``.
    """

    #: Two constructor parameters were removed here on 16 Aug 2026, and the
    #: reason is recorded rather than left to be rediscovered.
    #:
    #: ``preflight_hook`` announced a high-risk action to a callable before
    #: dispatch.  **Nothing in the package ever passed one** — the only
    #: callers were its own tests — and by the time it was audited there were
    #: two real preflights on the path already: this bus's capability check,
    #: which refuses rather than announces, and
    #: :mod:`core.runtime.schema_check`, which validates a call's arguments
    #: against the server's own schema before a mission dispatches it.  A
    #: third hook nobody passes is not a control; it is a place a future
    #: caller puts one and believes the run is governed.
    #:
    #: ``god_mode`` took an object with ``is_panicked`` and blocked every
    #: dispatch while it was set.  Nothing constructed a ``GodModeSession``
    #: either, and the concept it implemented — everything allowed for a
    #: session, with a TTL and a panic switch — has an honest form now that
    #: is actually reachable: ``--profile god`` / ``JUDAIS_LOBI_PROFILE``,
    #: announced on ``mission_started.profile``, with ``ProfileMode.GOD``
    #: unchanged.  A panic switch whose only user is a test is a safety
    #: story a deployment can tell and not have.
    def __init__(
        self,
        capability_engine: Optional[CapabilityEngine] = None,
        sandbox: Optional[SandboxRunner] = None,
        audit: Any = None,
    ):
        self._descriptors: Dict[str, ToolDescriptor] = {}
        self._executors: Dict[str, Callable] = {}
        self._capability = capability_engine or CapabilityEngine()
        # Safe by default: a bus handed no sandbox picks one the way the CLI
        # and library callers do — bwrap where bubblewrap exists, none only
        # where it does not. A caller that wants no isolation says so by
        # passing ``NoneSandbox()`` explicitly, so the default is the safe
        # thing and the unsafe thing is a decision on the record. (Passing a
        # concrete sandbox skips the auto path entirely, including its read
        # of ``JUDAIS_LOBI_SANDBOX``.)
        self._sandbox = sandbox if sandbox is not None else select_sandbox()[0]
        self._audit = audit
        #: How many audit writes have failed on this bus.  Counted rather
        #: than swallowed: see :meth:`_log_audit`.
        self.audit_failures = 0
        #: Whatever the caller running this bus wants on **every** audit
        #: entry — a deployment's own standing columns, set once and left.
        #: A plain dict because the bus has no business knowing what any of
        #: them mean, and because a caller that never sets one costs nothing.
        #:
        #: A fact that changes *per dispatch* does not belong here and no
        #: longer lives here: the mission's step index rides
        #: :meth:`dispatch` as ``step=``.  Two child runs of one mission can
        #: dispatch at the same time now, and a per-call fact left in a dict
        #: on a shared bus is a column that is wrong rather than absent.
        self.audit_context: Dict[str, Any] = {}
        #: Sources that can bring this registry up to date on demand.  See
        #: :meth:`follow` and :meth:`resync`.  Empty on a bus whose tools
        #: are all compiled in, which is every bus that has no server
        #: behind it.
        self._sources: List[Callable[[], Any]] = []

    @property
    def capability_engine(self) -> CapabilityEngine:
        return self._capability

    @property
    def sandbox(self) -> SandboxRunner:
        return self._sandbox

    @property
    def sandbox_name(self) -> str:
        """The word for this bus's sandbox: ``"bwrap"`` or ``"none"``.

        Derived from the installed runner rather than remembered from how it
        was chosen, so there is one owner of the string and it cannot drift
        from the object actually enforcing (or not) the isolation. This is
        what ``mission_started`` announces, read the same way by the direct
        and the staged runner.
        """
        return "bwrap" if isinstance(self._sandbox, BwrapSandbox) else "none"

    @property
    def audit_ref(self) -> Optional[str]:
        """The audit file this bus is writing to, or ``None`` for no audit.

        The single owner of that string.  A mission carries it on
        ``mission_started.audit_ref`` and both runners read it from here
        rather than each resolving a path of its own — two resolutions of
        one fact is how a stream comes to name a file nothing wrote to.
        """
        path = getattr(self._audit, "path", None)
        return str(path) if path else None

    def register(self, descriptor: ToolDescriptor, executor: Callable) -> None:
        """Register a tool with its descriptor and executor."""
        self._descriptors[descriptor.tool_name] = descriptor
        self._executors[descriptor.tool_name] = executor

    def unregister(self, tool_name: str) -> bool:
        """Remove a tool. Returns whether it was registered.

        Registration used to be one-way, which was fine while every tool
        was compiled in and outlived the process.  It stopped being fine
        when tools began arriving from an MCP server at runtime: a
        server that withdraws one leaves a descriptor behind that
        ``list_tools`` still advertises and ``describe_tool`` still
        describes, so the model is offered a tool whose only possible
        answer is an error from the far end.

        Returns a bool instead of raising on an unregistered name: the
        caller is normally reconciling a *set* against this registry,
        and "it was already gone" is the ordinary case there.
        """
        existed = tool_name in self._descriptors
        self._descriptors.pop(tool_name, None)
        self._executors.pop(tool_name, None)
        return existed

    def dispatch(self, tool_name: str, *args: Any,
                 action: Optional[str] = None,
                 deadline_s: Optional[float] = None,
                 step: Optional[int] = None,
                 **kwargs: Any) -> ToolResult:
        """Dispatch a tool invocation through capability gating.

        Parameters
        ----------
        tool_name : str
            Registered tool name.
        action : str, optional
            For multi-action tools, the specific action to run.
            Scopes are resolved from ``descriptor.action_scopes[action]``
            when present.
        deadline_s : float, optional
            How long the *caller* still has, in seconds — a **ceiling** on
            this call's subprocess timeout, never a floor.  A sandboxed
            tool that would have run for its own 120 s is cut to whatever
            is left, so a run with a wall-clock budget cannot overshoot it
            by a tool's full timeout.  ``None`` is the ordinary case and
            changes nothing.

            Named here rather than forwarded, and that is the whole reason
            it is a parameter of this method.  Everything this signature
            does not name goes to the executor, and for an MCP tool the
            executor is a remote server: a caller that "just passed a
            timeout down" would be inventing an argument for somebody
            else's schema.  Consumed here, it reaches only the one layer
            that owns a timeout — the sandbox runner below — and an
            in-process tool that never touches a subprocess is unaffected,
            which is honest: this bounds the plane it can bound and does
            not pretend to bound the other.
        step : int, optional
            Which model turn asked for this call, for the audit entry's
            ``step`` column.  ``None`` — the ordinary case, and every
            caller that is not a mission — leaves the column absent.

            Named here for the same reason ``deadline_s`` is, and it
            replaces a worse arrangement.  The step used to be *left* in
            :attr:`audit_context`, a mutable dict on a bus that outlives
            the run, immediately before the dispatch it described.  One
            run at a time that was merely indirect; the moment two child
            runs of one mission dispatch at the same time, the second
            overwrites the first's number and both entries are stamped
            with whichever won — a column that is **wrong** rather than
            absent, which is the worse of the two.  Riding the call, it
            cannot be anything but this call's.

            :attr:`audit_context` stays and is still merged into every
            entry: it is how a caller puts its own *standing* columns on
            this bus's log.  What it no longer holds is a fact that
            changes per dispatch.
        *args, **kwargs
            Forwarded to the executor.  When *action* is given the executor
            receives ``(action, *args, **kwargs)``.
        """
        arguments = {"args": list(args), "kwargs": dict(kwargs)}

        if tool_name not in self._descriptors:
            message = f"Unknown tool: {tool_name}"
            # Audited like every other dispatch. A model naming a tool that
            # does not exist is a fact about the run worth keeping — it is
            # the shape of a mission spending its budget on protocol — and
            # an audit that only records the calls that got as far as the
            # capability check cannot show it.
            self._log_audit(tool_name, action, [], "unknown_tool",
                            arguments=arguments, reason=message,
                            exit_code=-1, step=step)
            return ToolResult(
                exit_code=-1,
                stdout="",
                stderr=_json.dumps({
                    "error": "unknown_tool",
                    "tool": tool_name,
                    "message": message,
                }),
                tool_name=tool_name,
            )

        descriptor = self._descriptors[tool_name]
        executor = self._executors[tool_name]

        # Resolve scopes: action-specific if available, else full required
        if action and descriptor.action_scopes:
            scopes_to_check = descriptor.action_scopes.get(
                action, descriptor.required_scopes,
            )
        else:
            scopes_to_check = descriptor.required_scopes

        # Per-action metadata. `HIGH_RISK_ACTIONS` is no longer read here:
        # its only consumer was the preflight hook removed above, and the
        # set stays declared in `core.tools.descriptors` — where it is
        # tested and where a caller that wants to warn on one can read it —
        # rather than being computed here for nobody.
        needs_network = (
            (tool_name, action) in NETWORK_ACTIONS if action
            else descriptor.requires_network
        )

        # Capability check
        verdict = self._capability.check(tool_name, scopes_to_check)
        if not verdict.allowed:
            denial = {
                "error": "capability_denied",
                "tool": tool_name,
                "action": action,
                "missing_scopes": verdict.denied_scopes,
                "message": verdict.reason,
            }
            result = ToolResult(
                exit_code=-1,
                stdout="",
                stderr=_json.dumps(denial),
                tool_name=tool_name,
                evidence=_json.dumps(denial),
            )
            self._log_audit(tool_name, action, scopes_to_check, "denied",
                            arguments=arguments, reason=verdict.reason,
                            exit_code=-1, step=step)
            return result

        # Network check
        if needs_network:
            net_scopes = (
                descriptor.network_scopes
                if not action else scopes_to_check
            )
            network_verdict = self._capability.check(tool_name, net_scopes)
            if not network_verdict.allowed:
                denial = {
                    "error": "network_denied",
                    "tool": tool_name,
                    "action": action,
                    "missing_scopes": network_verdict.denied_scopes,
                    "message": network_verdict.reason,
                }
                result = ToolResult(
                    exit_code=-1,
                    stdout="",
                    stderr=_json.dumps(denial),
                    tool_name=tool_name,
                    evidence=_json.dumps(denial),
                )
                self._log_audit(tool_name, action, scopes_to_check, "denied",
                                arguments=arguments, step=step,
                                reason=network_verdict.reason, exit_code=-1)
                return result

        # Execute
        started = time.perf_counter()
        try:
            runner = None
            if self._should_use_sandbox(tool_name, action, descriptor):
                runner = self._build_sandbox_runner(
                    descriptor.sandbox_profile, deadline_s)

            # Installed for the length of THIS call and nowhere else. See
            # `core.tools.executor._ambient_runner`: this used to be a
            # `setattr` onto the executor object with the old value put
            # back in a `finally`, and two dispatches on one bus — two
            # children of a run, two clients of `core.tools.serve` — could
            # interleave so that the second's restore handed the first's
            # tool the unsandboxed runner back mid-dispatch.
            with use_subprocess_runner(runner):
                if action:
                    result = executor(action, *args, **kwargs)
                else:
                    result = executor(*args, **kwargs)

            # Handle tuple returns (rc, out, err) and (rc, out, err, evidence).
            # The fourth element is for a tool whose answer is *typed* and
            # not only rendered — an MCP `structuredContent`, say. Without
            # somewhere to put it, a caller that needs one field of a
            # governed view has to parse it back out of the text the model
            # was shown, which is the parse a typed payload exists to avoid.
            if isinstance(result, tuple) and len(result) in (3, 4):
                rc, out, err = result[0], result[1], result[2]
                tool_result = ToolResult(
                    exit_code=rc,
                    stdout=str(out),
                    stderr=str(err),
                    tool_name=tool_name,
                    granted_scopes=list(scopes_to_check),
                    evidence=(str(result[3]) if len(result) == 4 and result[3]
                              else None),
                )
            else:
                # Handle string returns (legacy tools)
                tool_result = ToolResult(
                    exit_code=0,
                    stdout=str(result),
                    stderr="",
                    tool_name=tool_name,
                    granted_scopes=list(scopes_to_check),
                )

            self._log_audit(
                tool_name, action, scopes_to_check, "allowed",
                arguments=arguments, step=step,
                exit_code=tool_result.exit_code,
                duration_s=time.perf_counter() - started,
                bytes_out=(len(tool_result.stdout.encode("utf-8"))
                           + len(tool_result.stderr.encode("utf-8"))),
            )
            return tool_result
        except Exception as ex:
            self._log_audit(
                tool_name, action, scopes_to_check, "error",
                arguments=arguments, step=step,
                reason=f"{type(ex).__name__}: {ex}",
                exit_code=-1,
                duration_s=time.perf_counter() - started,
            )
            return ToolResult(
                exit_code=-1,
                stdout="",
                stderr=f"Tool execution error: {type(ex).__name__}: {ex}",
                tool_name=tool_name,
            )

    def _should_use_sandbox(
        self,
        tool_name: str,
        action: Optional[str],
        descriptor: ToolDescriptor,
    ) -> bool:
        if descriptor.skip_sandbox:
            return False
        if action and (tool_name, action) in SKIP_SANDBOX_ACTIONS:
            return False
        return True

    def _build_sandbox_runner(self, profile: SandboxProfile,
                              deadline_s: Optional[float] = None) -> Callable:
        """A ``run_subprocess``-shaped callable that runs inside the sandbox.

        *deadline_s* is :meth:`dispatch`'s ceiling, applied to whatever
        timeout the tool asks for — ``min``, never ``max``: a caller with
        eight seconds left must not be able to *extend* a tool that
        deliberately bounds itself at five.

        ``shell`` and ``executable`` are forwarded, not swallowed.  This
        accepted both from :func:`core.tools.executor.run_subprocess` and
        dropped them, leaving each sandbox to re-derive shell mode from
        ``isinstance(cmd, str)`` and to hard-code ``/bin/bash`` — so a
        tool configured with another interpreter got bash without being
        told, and an explicit ``shell=False`` on a string command was
        ignored.  Sandboxing a command must not change which command it
        is.
        """
        # The child environment is built here, once, from the profile — this
        # is the single place the sandbox layer decides what a tool's child
        # inherits of the host environment, and it means the same thing on
        # either backend because it is handed to ``execute(env=…)`` as data
        # rather than re-derived inside each sandbox from ``os.environ``.
        child_env = build_sandbox_env(profile)

        # ``shell=None`` rather than ``False``: ``run_subprocess`` always
        # passes the flag, but a caller that installs this runner directly
        # and never had an opinion should keep the sandbox's inference
        # rather than be told, by a default, that nothing is a shell.
        #
        # ``stdin`` is threaded through explicitly, not swallowed into
        # ``**_kwargs``: ``run_python`` sends its program on stdin so it
        # never appears in ``ps`` (the argv leak 0.8.2 fixed for the model
        # key), and a runner that dropped it would send the interpreter an
        # empty stdin and an empty program.
        def _runner(cmd, *, shell: Optional[bool] = None, timeout: int = 120,
                    executable: Optional[str] = None,
                    stdin: Optional[str] = None, **_kwargs):
            bounded = timeout
            if deadline_s is not None:
                # `max(1, …)` because a timeout of zero means "no timeout"
                # to most of the subprocess layer underneath, which is the
                # opposite of what a spent deadline is asking for. One
                # second is the smallest bound that still means a bound.
                bounded = max(1, min(int(timeout), int(deadline_s)))
            return self._sandbox.execute(
                cmd,
                profile=profile,
                timeout=bounded,
                shell=shell,
                executable=executable,
                env=child_env,
                stdin=stdin,
            )
        return _runner

    #: There were two more methods here once, and what they did is
    #: worth keeping written down because the shape is tempting.
    #:
    #: ``_apply_subprocess_runner`` walked the executor for the attributes a
    #: tool reads its runner off — ``subprocess_runner``,
    #: ``_subprocess_runner``, and the same on ``_engine`` and its
    #: ``_worktree``, which is how the patch tool's two objects were
    #: reached — assigned the sandbox runner onto each and returned the old
    #: values; ``_restore_subprocess_runner`` put them back in
    #: :meth:`dispatch`'s ``finally``.  It read as save-and-restore, which
    #: is a discipline; it *was* a write to state shared by every caller of
    #: this bus, which is a race.  Two dispatches interleaving —
    #: A-apply, B-apply, A-restore, B-executes — left B running with the
    #: original, **unsandboxed** runner, and a tool that spawns more than
    #: one child could cross that line halfway through its own work.  It
    #: also only ever reached the four attributes named above, so a tool
    #: that called :func:`~core.tools.executor.run_subprocess` from
    #: anywhere else was never sandboxed at all.
    #:
    #: Both problems have the same cause — the runner was a property of the
    #: *tool* rather than of the *call* — and one fix:
    #: :func:`core.tools.executor.use_subprocess_runner`.  Nothing shared is
    #: written, so nothing has to be restored, and no attribute has to be
    #: found.

    def follow(self, source: Callable[[], Any]) -> None:
        """Register something that can bring this registry up to date.

        A bus is a registry and not a client: it holds whatever was
        registered on it and has no idea where any of it came from.  That
        is fine until something registers *asynchronously* — a bridge that
        re-lists on its own thread when a server notifies it — because then
        :meth:`list_tools` answers with whatever had landed by the time it
        was asked, and a caller that has to decide **now** what the model
        may name is reading a cache with a race in it.

        So a source that can be asked says so here, and :meth:`resync` is
        the asking.  The bus still knows nothing about MCP, or threads, or
        what a re-list costs; it knows that some of its entries have an
        upstream and that an upstream can be pulled.
        """
        if callable(source):
            self._sources.append(source)

    def resync(self) -> bool:
        """Ask every followed source to bring this registry up to date, now.

        Returns whether the set of registered names is different
        afterwards — the one fact a caller can act on, and one this bus can
        state without knowing what a source is.

        **Bounded by the source, not here.**  A source that cannot answer
        in whatever time it gives itself is expected to return, leaving the
        last set standing: a step boundary that blocked on a server would
        be a worse failure than a catalogue one re-list behind.  A source
        that raises is treated the same way and for the same reason — a
        registry that cannot be refreshed is still a registry.
        """
        before = list(self._descriptors)
        for source in list(self._sources):
            try:
                source()
            except Exception:               # noqa: BLE001 - see docstring
                continue
        return list(self._descriptors) != before

    def list_tools(self) -> List[str]:
        """Return names of all registered tools."""
        return list(self._descriptors.keys())

    def describe_tool(self, name: str) -> dict:
        """Return a description dict for a tool."""
        desc = self._descriptors.get(name)
        if desc is None:
            return {"error": f"No such tool: {name}"}
        info = {
            "name": desc.tool_name,
            "description": desc.description,
            "required_scopes": list(desc.required_scopes),
            "requires_network": desc.requires_network,
        }
        if desc.action_scopes:
            info["actions"] = list(desc.action_scopes.keys())
        if desc.input_schema:
            # The schema itself, not only a rendering of it: a caller
            # building a native tool-call request needs the whole thing,
            # and a caller building a prompt wants the summary. Handing
            # out only the summary would make the prompt the authority on
            # a tool's arguments, which is how the two drift.
            info["input_schema"] = desc.input_schema
            info["arguments"] = summarize_input_schema(desc.input_schema)
        return info

    def get_descriptor(self, name: str) -> Optional[ToolDescriptor]:
        """Return the ToolDescriptor for a given tool name."""
        return self._descriptors.get(name)

    def get_executor(self, name: str) -> Optional[Callable]:
        """The callable registered under *name*, or ``None``.

        A read, beside :meth:`get_descriptor`, and it exists for exactly one
        caller: :mod:`core.tools.serve`, which publishes this bus over MCP
        and has to advertise each tool's *arguments*.  A compiled-in tool
        declares those in its own ``__call__`` and nowhere else — the
        descriptor's ``input_schema`` is empty for all of them — so the
        server reads the signature rather than carrying a second copy of
        every tool's parameter list.

        Handing out the executor is not handing out a way round the gate:
        every caller that *dispatches* still goes through
        :meth:`dispatch`, and a caller holding this bus could always have
        reached the same object.  Named as a getter to say that it is for
        looking at.
        """
        return self._executors.get(name)

    def _log_audit(
        self,
        tool_name: str,
        action: Optional[str],
        scopes: List[str],
        verdict: str,
        *,
        arguments: Optional[Dict[str, Any]] = None,
        reason: str = "",
        exit_code: Optional[int] = None,
        duration_s: Optional[float] = None,
        bytes_out: Optional[int] = None,
        step: Optional[int] = None,
    ) -> None:
        """Log a dispatch event to the audit logger if present.

        Everything beyond the four positional facts travels in
        :attr:`AuditEntry.detail` as one JSON object, rather than as new
        fields on the entry, and that is deliberate: ``detail`` is the
        field :meth:`core.policy.audit.AuditLogger._redact` runs over, so
        a credential passed as a tool *argument* is covered by the same
        pass that covers one pasted into a message.  A second field would
        be a second thing to remember to redact, and the one that got
        forgotten would be the one carrying the argument.

        ``arguments`` is bounded by :func:`core.bounding.bound_result` at
        the repository's one cap — an audit line is a record, not a
        transcript, and a tool handed a megabyte should not put a megabyte
        on every line of the log.

        :attr:`audit_context` is merged in first, so the caller's standing
        keys are there and the bus's own facts win any collision — the
        dispatch's own ``step`` included, which is why it is written after
        the merge and not before it.
        """
        if self._audit is None:
            return
        try:
            from core.contracts.schemas import AuditEntry
            rendered, truncated = bound_result(
                _json.dumps(arguments or {}, default=str, sort_keys=True))
            detail: Dict[str, Any] = dict(self.audit_context)
            if step is not None:
                detail["step"] = step
            detail["arguments"] = rendered
            if truncated:
                detail["arguments_truncated"] = True
            if reason:
                detail["reason"] = reason
            if exit_code is not None:
                detail["exit_code"] = exit_code
            if duration_s is not None:
                detail["duration_ms"] = round(duration_s * 1000, 3)
            if bytes_out is not None:
                detail["bytes_out"] = bytes_out
            self._audit.log(AuditEntry(
                event_type="tool_dispatch",
                tool_name=tool_name,
                action=action or "",
                scopes=list(scopes),
                verdict=verdict,
                detail=_json.dumps(detail, default=str, sort_keys=True),
            ))
        except Exception as ex:
            # Dispatch survives — an audit disk filling up must not kill a
            # tool call — but the failure is COUNTED and SAID. This was a
            # bare `pass` for four phases, which meant a bus whose logger
            # had been throwing since the first call looked exactly like a
            # bus whose tools nobody had used. Once to stderr, because the
            # second thousand copies of a full-disk message are what stop
            # anybody reading the first; the counter carries the rest, and
            # the CLI prints it when the mission ends.
            self.audit_failures += 1
            if self.audit_failures == 1:
                print(
                    f"⚠️  audit write FAILED ({type(ex).__name__}: {ex}); "
                    f"tool dispatch continues and this run is no longer "
                    f"fully recorded",
                    file=sys.stderr,
                )
