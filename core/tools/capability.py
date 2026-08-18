# core/tools/capability.py — Deny-by-default capability engine

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence, TYPE_CHECKING

from core.contracts.schemas import PermissionGrant, PolicyPack

if TYPE_CHECKING:
    from core.contracts.schemas import ProfileMode


@dataclass
class CapabilityVerdict:
    """Result of a capability check."""
    allowed: bool
    denied_scopes: List[str] = field(default_factory=list)
    reason: str = ""


class CapabilityEngine:
    """Deny-by-default capability checker.

    Checks tool invocations against:
    1. PolicyPack (static session-level permissions)
    2. Active PermissionGrants (dynamic, possibly time-scoped)

    Supports wildcard ``"*"`` in ``allowed_scopes`` — grants all scopes.
    """

    #: How a session grant is filed: no tool name, so it covers every tool
    #: that asks for the scope, and no expiry, so it lasts the process.  The
    #: two words are constants because :meth:`session_scopes` reads a grant
    #: back by them and a second spelling would be a grant nothing can find.
    SESSION = "session"
    OPERATOR = "operator"

    def __init__(self, policy: Optional[PolicyPack] = None):
        self._policy = policy or PolicyPack()
        self._grants: List[PermissionGrant] = []
        self._current_profile: Optional[str] = None
        #: The scope allowlist a role or a campaign step is narrowed to, or
        #: ``None`` for a plane that was never narrowed.
        #:
        #: **A context variable and not an attribute**, and that is a
        #: decision about concurrency rather than about style.  One engine
        #: is shared by every child of a run — it hangs off the bus, which
        #: is shared by identity so that two children cannot end up
        #: governed differently — and since lane D two children can run at
        #: the same time, each narrowed to *its own* step's scopes.  An
        #: attribute would mean the last narrow before the ``gather`` wins
        #: for everybody, which is a step silently running under a
        #: sibling's permissions.
        #:
        #: A :class:`~contextvars.ContextVar` is the exact shape of that
        #: fact: :func:`asyncio.gather` copies the context per task, so a
        #: narrow inside one child's coroutine is that child's; and
        #: :func:`asyncio.to_thread` — which is how a dispatch actually
        #: reaches the bus — copies the context into the worker thread, so
        #: the constraint is still in force where the check happens.  A
        #: synchronous caller (the kernel orchestrator, narrowing once per
        #: phase) sees exactly the attribute it saw before.
        #:
        #: Per instance and not per module: two engines in one process are
        #: two policies, and a shared variable would make them one.
        self._constraints: "ContextVar[Optional[frozenset]]" = ContextVar(
            f"judais_lobi_scope_constraints_{id(self):x}", default=None)

    @property
    def policy(self) -> PolicyPack:
        return self._policy

    @property
    def current_profile(self) -> Optional[str]:
        return self._current_profile

    def add_grant(self, grant: PermissionGrant) -> None:
        """Add a permission grant."""
        self._grants.append(grant)

    def check(self, tool_name: str, required_scopes: List[str]) -> CapabilityVerdict:
        """Check if all required scopes are satisfied by policy or active grants.

        Returns CapabilityVerdict(allowed=True) only if ALL required scopes
        are covered. Invocation-scoped grants are consumed on successful check.
        """
        if not required_scopes:
            return CapabilityVerdict(allowed=True, reason="no scopes required")

        # First, expire stale grants
        self.expire_stale_grants()

        denied = []
        invocation_grants_to_consume = []

        constraints = self._constraints.get()
        for scope in required_scopes:
            if constraints is not None and scope not in constraints:
                denied.append(scope)
                continue
            if self._is_scope_in_policy(scope):
                continue
            grant = self._find_active_grant(tool_name, scope)
            if grant is None:
                denied.append(scope)
            elif grant.grant_scope == "invocation":
                invocation_grants_to_consume.append(grant)

        if denied:
            return CapabilityVerdict(
                allowed=False,
                denied_scopes=denied,
                reason=self._denial_reason(denied),
            )

        # Consume invocation-scoped grants
        for grant in invocation_grants_to_consume:
            if grant in self._grants:
                self._grants.remove(grant)

        return CapabilityVerdict(allowed=True, reason="all scopes granted")

    def is_scope_granted(self, tool_name: str, scope: str) -> bool:
        """Check if a single scope is granted (by policy or active grant)."""
        constraints = self._constraints.get()
        if constraints is not None and scope not in constraints:
            return False
        if self._is_scope_in_policy(scope):
            return True
        return self._find_active_grant(tool_name, scope) is not None

    def set_scope_constraints(self, scopes: Optional[Sequence[str]]) -> None:
        """Set an allowlist of scopes to intersect with policy/grants.

        Reached through :meth:`~core.runtime.run.ToolPlane.narrow`, which is
        governance's one surface; called directly only by this class's own
        tests and by the kernel orchestrator's phase boundary.

        **In force for the current context**, which is the calling task and
        every thread :func:`asyncio.to_thread` starts from it — see
        :attr:`_constraints`.  A caller that narrows inside one child's
        coroutine narrows that child and no sibling; a caller that narrows
        synchronously narrows everything after it, which is what this method
        always did.
        """
        self._constraints.set(None if scopes is None
                              else frozenset(str(scope) for scope in scopes))

    def clear_scope_constraints(self) -> None:
        """Clear any scope constraints."""
        self._constraints.set(None)

    @property
    def scope_constraints(self) -> Optional[List[str]]:
        constraints = self._constraints.get()
        if constraints is None:
            return None
        return list(constraints)

    def grant_scopes(self, scopes: Iterable[str],
                     granted_by: str = OPERATOR) -> List[str]:
        """Pre-authorise *scopes* for this session.  Returns what was added.

        The object form of ``--grant``: :meth:`add_grant` takes one
        :class:`~core.contracts.schemas.PermissionGrant` at a time and every
        caller of it had to know the four fields that make a grant
        session-wide rather than per-tool or time-boxed.  This states them
        once — no ``tool_name``, so the grant covers whatever tool asks for
        the scope; no ``grant_duration_seconds``, so it lasts the process;
        ``grant_scope`` :data:`SESSION`, so :meth:`check` does not consume it
        on first use.

        It **widens**, where :meth:`set_scope_constraints` narrows, and the
        two compose in the order security wants: a constraint is checked
        first and a scope outside it is denied however it was granted, so a
        campaign step narrowed to ``fs.read`` cannot reach a granted
        ``http.read``.  A grant is not a way around least privilege; it is a
        way past the *profile*.

        Idempotent by scope: granting the same scope twice leaves one grant,
        because a grant is a permission and not a counter.
        """
        already = set(self.session_scopes())
        added: List[str] = []
        for scope in scopes:
            name = str(scope).strip()
            if not name or name in already:
                continue
            self.add_grant(PermissionGrant(
                tool_name="", scope=name, granted_by=str(granted_by),
                grant_scope=self.SESSION))
            already.add(name)
            added.append(name)
        return added

    def session_scopes(self) -> List[str]:
        """Every scope a session grant covers, sorted, once each.

        Derived from :attr:`_grants` rather than kept beside them: the
        opening frame's ``granted`` field, the refusal's "granted for this
        run" clause and the console line all read this, and a second list of
        what was granted is the second owner that comes to disagree with the
        engine actually doing the granting.
        """
        return sorted({
            grant.scope for grant in self._grants
            if grant.grant_scope == self.SESSION and not grant.tool_name
        })

    def list_active_grants(self) -> List[PermissionGrant]:
        """Return all non-expired grants."""
        self.expire_stale_grants()
        return list(self._grants)

    def expire_stale_grants(self) -> int:
        """Remove time-expired grants. Returns count of expired grants."""
        now = datetime.now(timezone.utc)
        expired = []
        for grant in self._grants:
            if grant.grant_duration_seconds is not None:
                expiry = grant.grant_issued_at.timestamp() + grant.grant_duration_seconds
                if now.timestamp() > expiry:
                    expired.append(grant)
        for grant in expired:
            self._grants.remove(grant)
        return len(expired)

    def load_grants(self, grants: List[PermissionGrant]) -> None:
        """Bulk-load grants for session replay.

        Replaces existing grants. Does not evaluate wall clock for
        time-scoped grants during replay — they are loaded as-is.
        """
        self._grants = list(grants)

    def revoke_all_grants(self) -> int:
        """Revoke all active grants. Returns the count of revoked grants."""
        count = len(self._grants)
        self._grants.clear()
        return count

    def set_profile(self, profile: "ProfileMode") -> None:
        """Replace the internal policy with one derived from *profile*.

        Requires ``core.policy.profiles.policy_for_profile`` — imported
        lazily to avoid circular imports.
        """
        from core.policy.profiles import policy_for_profile
        self._policy = policy_for_profile(profile)
        self._current_profile = profile.value

    def _denial_reason(self, denied: List[str]) -> str:
        """A refusal that names the missing scope *and* the fix.

        The message the model and the user see for a ``capability_denied``
        result. It used to be ``"denied scopes: shell.exec"`` — true, and
        useless: it named the fault and not the fix, so an operator whose
        ``lobi --shell`` was refused had no way, from the message, to learn
        that ``--profile dev`` grants it. :func:`core.policy.profiles.
        denial_reason` derives the lowest profile that includes each missing
        scope from ``PROFILE_SCOPES`` — never a hand-maintained list — so
        the named fix cannot drift from the table that decides the grant.

        Imported lazily for the same reason :meth:`set_profile` is: the
        policy package pulls this module in, and the import is only ever
        needed on the denial path.
        """
        from core.policy.profiles import denial_reason
        return denial_reason(denied, current_profile=self._current_profile,
                             granted=self.session_scopes())

    def _is_scope_in_policy(self, scope: str) -> bool:
        """Check if scope is allowed by the static policy.

        Supports wildcard ``"*"`` — if present, all scopes are allowed.
        """
        if "*" in self._policy.allowed_scopes:
            return True
        return scope in self._policy.allowed_scopes

    def _find_active_grant(self, tool_name: str, scope: str) -> Optional[PermissionGrant]:
        """Find a matching non-expired grant for tool_name + scope."""
        now = datetime.now(timezone.utc)
        for grant in self._grants:
            if grant.scope != scope:
                continue
            # Grant can be tool-specific or wildcard (empty tool_name)
            if grant.tool_name and grant.tool_name != tool_name:
                continue
            # Check time expiry
            if grant.grant_duration_seconds is not None:
                expiry = grant.grant_issued_at.timestamp() + grant.grant_duration_seconds
                if now.timestamp() > expiry:
                    continue
            return grant
        return None
